"""Stage 2 (LLM part): flag administrative / contentless messages with Haiku.

Admin messages (meeting reminders, auto-generated bot posts, bare "+1" replies)
are flagged so they can be excluded from summarization. We batch one request per
message and parse a tiny JSON verdict.
"""
from __future__ import annotations

from ..config import get_settings
from ._json import extract_json
from .batch import BatchRequest

_SYSTEM = (
    "You are a classifier for IETF mailing-list messages. Decide whether a message "
    "is ADMINISTRATIVE/contentless (meeting reminders, agenda bot posts, automated "
    "notifications, bare '+1'/'agreed' with no substance) or SUBSTANTIVE (contains "
    "technical discussion, positions, questions, or arguments). "
    'Respond with ONLY a JSON object: {"admin": true|false, "reason": "<short>"}.'
)


def build_request(message_id: str, subject: str | None, body: str, model: str | None = None) -> BatchRequest:
    model = model or get_settings().llm.model_categorization
    user = f"Subject: {subject or '(none)'}\n\nBody:\n{(body or '').strip()[:4000]}"
    return BatchRequest(
        custom_id=f"prefilter::{message_id}",
        params={
            "model": model,
            "max_tokens": 100,
            "system": _SYSTEM,
            "messages": [{"role": "user", "content": user}],
        },
    )


def parse_result(text: str | None) -> bool:
    """Return True if the message is administrative. Defaults to False (keep it)."""
    data = extract_json(text)
    if isinstance(data, dict):
        return bool(data.get("admin", False))
    return False
