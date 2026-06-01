"""Fetch mailing-list archives from the IETF mail archive.

mailarchive.ietf.org exposes a full mbox export per list:
    https://mailarchive.ietf.org/arch/export/mbox/?email_list=<name>
optionally time-bounded with `gbt` (greater-than) / `lbt` (less-than) ISO dates.

The HTTP layer is isolated behind ``Fetcher`` so the parsing/threading logic can
be tested without the network, and so transient archive outages are retried with
exponential backoff (logged, never fatal).
"""
from __future__ import annotations

import gzip
import re
import time
from collections.abc import Iterator
from email.message import Message as EmailMessage

import httpx

from ..config import IngestionConfig, get_settings
from ..logging_conf import get_logger

log = get_logger(__name__)

EXPORT_BASE = "https://mailarchive.ietf.org/arch/export/mbox/"


class ArchiveUnavailable(RuntimeError):
    """Raised after retries are exhausted; callers log and continue."""


class Fetcher:
    """Thin retrying HTTP wrapper. Injectable for tests."""

    def __init__(self, cfg: IngestionConfig | None = None, client: httpx.Client | None = None):
        self.cfg = cfg or get_settings().ingestion
        self._client = client
        self._owns_client = client is None

    def __enter__(self) -> Fetcher:
        if self._client is None:
            self._client = httpx.Client(
                timeout=self.cfg.request_timeout_seconds,
                follow_redirects=True,
                headers={"User-Agent": "wg-tracker/0.1 (IETF WG activity tracker)"},
            )
        return self

    def __exit__(self, *exc) -> None:
        if self._owns_client and self._client is not None:
            self._client.close()

    def get(self, url: str, params: dict | None = None) -> bytes:
        attempt = 0
        while True:
            try:
                resp = self._client.get(url, params=params)  # type: ignore[union-attr]
                resp.raise_for_status()
                return resp.content
            except (httpx.HTTPError, httpx.TimeoutException) as exc:
                attempt += 1
                if attempt > self.cfg.max_retries:
                    raise ArchiveUnavailable(f"{url} failed after {attempt} attempts: {exc}") from exc
                delay = self.cfg.backoff_base_seconds ** attempt
                log.warning(
                    "archive fetch retry",
                    extra={"url": url, "attempt": attempt, "delay": delay, "error": str(exc)},
                )
                time.sleep(delay)


def export_url_params(email_list: str, since_iso: str | None = None) -> tuple[str, dict]:
    params: dict[str, str] = {"email_list": email_list}
    if since_iso:
        # `gbt` = "greater-than" bound on the message date.
        params["gbt"] = since_iso
    return EXPORT_BASE, params


def _maybe_gunzip(content: bytes) -> bytes:
    if content[:2] == b"\x1f\x8b":  # gzip magic
        return gzip.decompress(content)
    return content


def iter_mbox_messages(mbox_bytes: bytes) -> Iterator[EmailMessage]:
    """Yield email.message.Message objects from raw mbox content.

    Malformed individual messages are skipped (logged), never fatal.
    """
    raw = _maybe_gunzip(mbox_bytes)
    from email import message_from_bytes

    for idx, chunk in enumerate(_split_mbox(raw)):
        try:
            yield message_from_bytes(chunk)
        except Exception as exc:  # malformed message — skip, don't crash
            log.warning("skipping malformed mbox message", extra={"index": idx, "error": str(exc)})


# An mbox "From_" separator looks like: ``From <addr> Mon Jan 01 00:00:00 2025``.
# Matching the trailing weekday/month avoids splitting on body lines that merely
# start with "From " (the classic unescaped-From mbox hazard).
_FROM_LINE_RE = re.compile(rb"^From \S+ [A-Z][a-z]{2} [A-Z][a-z]{2} ")


def _split_mbox(raw: bytes) -> list[bytes]:
    """Split mbox bytes into individual RFC822 message chunks on the 'From_' line."""
    lines = raw.split(b"\n")
    chunks: list[list[bytes]] = []
    current: list[bytes] = []
    for line in lines:
        if _FROM_LINE_RE.match(line):
            if current:
                chunks.append(current)
            current = [line]
        else:
            current.append(line)
    if current:
        chunks.append(current)
    return [b"\n".join(c) for c in chunks if any(x.strip() for x in c)]


def fetch_list_mbox(email_list: str, since_iso: str | None, fetcher: Fetcher) -> bytes:
    url, params = export_url_params(email_list, since_iso)
    log.info("fetching archive", extra={"email_list": email_list, "since": since_iso})
    return fetcher.get(url, params=params)
