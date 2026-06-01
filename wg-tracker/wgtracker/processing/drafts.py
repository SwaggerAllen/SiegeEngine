"""Draft cross-reference: detect draft/RFC references in message bodies and sync
metadata from the IETF Datatracker.

Reference forms handled (per spec):
  - bare:        draft-ietf-mls-extensions
  - versioned:   draft-ietf-mls-extensions-04
  - RFC:         RFC 9420 / RFC9420
  - datatracker: https://datatracker.ietf.org/doc/draft-ietf-mls-extensions/
  - archived id: https://www.ietf.org/archive/id/draft-ietf-mls-extensions-04.html
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime

import httpx

from ..config import get_settings
from ..logging_conf import get_logger

log = get_logger(__name__)

# A draft name is draft-<stuff>, lowercase letters/digits/hyphens. We match the
# full token greedily, then peel an optional trailing -NN version in
# ``_split_version`` (a lazy regex would stop at "draft-ietf").
_DRAFT_RE = re.compile(
    r"\bdraft-[a-z0-9]+(?:-[a-z0-9]+)*\b",
    re.IGNORECASE,
)
_RFC_RE = re.compile(r"\bRFC[\s\-]?(\d{3,5})\b", re.IGNORECASE)
_VERSION_SUFFIX_RE = re.compile(r"-(\d{2})$")


@dataclass
class DraftReference:
    draft_name: str  # base name, version stripped
    versions: set[str] = field(default_factory=set)  # e.g. {"-04"}


def _split_version(token: str) -> tuple[str, str | None]:
    """Return (base_name, version_or_None) for a draft token."""
    m = _VERSION_SUFFIX_RE.search(token)
    if m:
        return token[: m.start()], "-" + m.group(1)
    return token, None


def extract_references(text: str) -> dict[str, DraftReference]:
    """Extract all draft references (keyed by base draft name) from a message body.

    RFC NNNN references are normalized to the pseudo draft name ``rfc<NNNN>`` so
    they can be cross-referenced too (the datatracker resolves these).
    """
    refs: dict[str, DraftReference] = {}
    if not text:
        return refs

    for m in _DRAFT_RE.finditer(text):
        token = m.group(0).lower().rstrip("-.")
        base, version = _split_version(token)
        ref = refs.setdefault(base, DraftReference(draft_name=base))
        if version:
            ref.versions.add(version)

    for m in _RFC_RE.finditer(text):
        name = f"rfc{m.group(1)}"
        refs.setdefault(name, DraftReference(draft_name=name))

    return refs


# ---------------------------------------------------------------------------
# Datatracker metadata sync
# ---------------------------------------------------------------------------


@dataclass
class DraftMetadata:
    draft_name: str
    title: str | None = None
    current_version: str | None = None
    working_group: str | None = None
    status: str | None = None
    rfc_number: str | None = None
    authors: list[str] = field(default_factory=list)
    abstract: str | None = None
    datatracker_url: str | None = None
    versions: list[dict] = field(default_factory=list)


class DatatrackerClient:
    """Minimal Datatracker API client with retry/backoff. Injectable for tests."""

    def __init__(self, base: str | None = None, client: httpx.Client | None = None):
        s = get_settings()
        self.base = (base or s.drafts.datatracker_api_base).rstrip("/") + "/"
        self.cfg = s.ingestion
        self._client = client
        self._owns = client is None

    def __enter__(self) -> DatatrackerClient:
        if self._client is None:
            self._client = httpx.Client(
                timeout=self.cfg.request_timeout_seconds,
                follow_redirects=True,
                headers={"User-Agent": "wg-tracker/0.1"},
            )
        return self

    def __exit__(self, *exc) -> None:
        if self._owns and self._client is not None:
            self._client.close()

    def _get_json(self, path: str, params: dict) -> dict | None:
        url = self.base + path
        attempt = 0
        while True:
            try:
                resp = self._client.get(url, params=params)  # type: ignore[union-attr]
                resp.raise_for_status()
                return resp.json()
            except (httpx.HTTPError, httpx.TimeoutException) as exc:
                attempt += 1
                if attempt > self.cfg.max_retries:
                    log.warning(
                        "datatracker fetch failed", extra={"url": url, "error": str(exc)}
                    )
                    return None
                time.sleep(self.cfg.backoff_base_seconds ** attempt)

    def fetch_draft(self, draft_name: str) -> DraftMetadata | None:
        """Fetch metadata for a draft (or rfcNNNN pseudo-name)."""
        is_rfc = draft_name.startswith("rfc")
        params = {"name": draft_name, "format": "json"}
        data = self._get_json("doc/document/", params)
        if not data:
            return None
        objects = data.get("objects") or []
        if not objects:
            return None
        obj = objects[0]
        version = obj.get("rev")
        meta = DraftMetadata(
            draft_name=draft_name,
            title=obj.get("title"),
            current_version=f"-{version}" if version and not version.startswith("-") else version,
            status=(obj.get("states") or [None])[0] if obj.get("states") else obj.get("std_level"),
            abstract=obj.get("abstract"),
            datatracker_url=f"https://datatracker.ietf.org/doc/{draft_name}/",
            rfc_number=draft_name[3:] if is_rfc else obj.get("rfc"),
        )
        # working group group ref looks like "/api/v1/group/group/<id>/"; the slug
        # is often embedded in the draft name (draft-ietf-<wg>-...).
        meta.working_group = _infer_wg(draft_name)
        return meta


def _infer_wg(draft_name: str) -> str | None:
    parts = draft_name.split("-")
    if len(parts) >= 3 and parts[0] == "draft" and parts[1] == "ietf":
        return parts[2]
    return None


def utcnow() -> datetime:
    return datetime.now(UTC)
