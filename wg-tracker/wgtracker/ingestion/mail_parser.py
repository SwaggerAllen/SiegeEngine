"""Parse RFC 5322 messages into a normalized structure.

Handles broken headers and weird encodings defensively: a message that can't be
parsed cleanly is salvaged where possible and skipped (with logging) where not.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.header import decode_header, make_header
from email.message import Message as EmailMessage
from email.utils import getaddresses, parsedate_to_datetime

from ..logging_conf import get_logger

log = get_logger(__name__)

_MSGID_RE = re.compile(r"<([^<>]+)>")
_ARCHIVED_AT_RE = re.compile(r"<(https?://[^<>\s]+)>")


@dataclass
class ParsedMessage:
    message_id: str
    from_address: str | None
    from_name: str | None
    subject: str | None
    date: datetime | None
    archive_url: str | None
    in_reply_to: str | None
    references: list[str] = field(default_factory=list)
    body_original: str = ""


def _decode(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return value


def _norm_msgid(raw: str | None) -> str | None:
    if not raw:
        return None
    m = _MSGID_RE.search(raw)
    if m:
        return m.group(1).strip()
    return raw.strip().strip("<>") or None


def _parse_references(value: str | None) -> list[str]:
    if not value:
        return []
    return [m.group(1).strip() for m in _MSGID_RE.finditer(value)]


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        return None
    if dt is None:
        return None
    # Normalize to timezone-aware UTC.
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _extract_body(msg: EmailMessage) -> str:
    """Return the best-effort plain-text body."""
    if msg.is_multipart():
        # Prefer text/plain parts; fall back to first text/* part.
        plain_parts: list[str] = []
        fallback_parts: list[str] = []
        for part in msg.walk():
            ctype = part.get_content_type()
            if part.get_content_maintype() != "text":
                continue
            if part.get("Content-Disposition", "").startswith("attachment"):
                continue
            decoded = _decode_payload(part)
            if decoded is None:
                continue
            if ctype == "text/plain":
                plain_parts.append(decoded)
            else:
                fallback_parts.append(decoded)
        if plain_parts:
            return "\n".join(plain_parts)
        return "\n".join(fallback_parts)
    return _decode_payload(msg) or ""


def _decode_payload(part: EmailMessage) -> str | None:
    try:
        payload = part.get_payload(decode=True)
        if payload is None:
            return None
        charset = part.get_content_charset() or "utf-8"
        return payload.decode(charset, errors="replace")
    except (LookupError, ValueError, TypeError) as exc:
        log.debug("payload decode fallback", extra={"error": str(exc)})
        try:
            return part.get_payload(decode=True).decode("utf-8", errors="replace")  # type: ignore[union-attr]
        except Exception:
            return None


def parse_message(msg: EmailMessage) -> ParsedMessage | None:
    """Parse one email into a ParsedMessage, or None if unusable (no Message-ID)."""
    message_id = _norm_msgid(msg.get("Message-ID"))
    if not message_id:
        log.warning("message missing Message-ID, skipping")
        return None

    from_name, from_address = None, None
    addrs = getaddresses([msg.get("From", "")])
    if addrs:
        raw_name, raw_addr = addrs[0]
        from_name = _decode(raw_name) or None
        from_address = (raw_addr or "").lower() or None

    archived_at = msg.get("Archived-At")
    archive_url = None
    if archived_at:
        m = _ARCHIVED_AT_RE.search(archived_at)
        archive_url = m.group(1) if m else archived_at.strip().strip("<>")

    return ParsedMessage(
        message_id=message_id,
        from_address=from_address,
        from_name=from_name,
        subject=_decode(msg.get("Subject")),
        date=_parse_date(msg.get("Date")),
        archive_url=archive_url,
        in_reply_to=_norm_msgid(msg.get("In-Reply-To")),
        references=_parse_references(msg.get("References")),
        body_original=_extract_body(msg),
    )
