"""Stage 4: per-thread summarization with Sonnet 4.6 via the Batch API.

The prompt is engineered around the spec's hardest requirement: distinguish
"what was said" from "what the WG concluded". The model is told never to assert
consensus without explicit signal, and to attribute positions to people.

Referenced-draft metadata (name, version, title, abstract) is injected so the
summary can describe what the thread argued *about* a draft, not merely that it
was mentioned.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..config import get_settings
from ._json import extract_json
from .batch import BatchRequest

VALID_CONSENSUS = {
    "clear_consensus",
    "emerging_consensus",
    "active_debate",
    "no_consensus",
    "single_voice",
}
VALID_STATUS = {"active", "concluded", "abandoned"}

_SYSTEM = """You summarize a single IETF working-group email thread for a structured archive.

CRITICAL RULES:
- Distinguish what was SAID from what the working group CONCLUDED. Do NOT write
  "the WG decided X" unless there is an explicit consensus call or clear, stated
  agreement in the thread. Prefer "X was advocated by <name>, with <name> raising
  <concern>".
- Attribute positions to specific participants by display name or email.
- Be concise and factual. Do not invent drafts, names, or outcomes.
- If the thread references drafts, ground your summary in what was argued about
  those drafts using the provided draft metadata.

Respond with ONLY a JSON object of this exact shape:
{
  "summary": "<2-5 sentence neutral description of what was discussed>",
  "key_positions": [
    {"position": "<the stance>", "holder": "<name or email>", "context": "<why/qualifier>"}
  ],
  "consensus_state": "clear_consensus | emerging_consensus | active_debate | no_consensus | single_voice",
  "status": "active | concluded | abandoned"
}"""


@dataclass
class ThreadSummary:
    summary: str
    key_positions: list[dict]
    consensus_state: str
    status: str


def _format_drafts(drafts: list[dict]) -> str:
    if not drafts:
        return "(none referenced)"
    lines = []
    for d in drafts:
        abstract = (d.get("abstract") or "").strip()[:500]
        ver = d.get("current_version") or ""
        lines.append(
            f"- {d['draft_name']} {ver}: {d.get('title') or '(no title)'}\n  {abstract}"
        )
    return "\n".join(lines)


def _format_messages(messages: list[dict], max_chars: int = 40_000) -> str:
    blocks = []
    used = 0
    for m in messages:
        who = m.get("from_name") or m.get("from_address") or "unknown"
        date = m.get("date") or ""
        body = (m.get("body_cleaned") or "").strip()
        block = f"--- From: {who}  Date: {date} ---\n{body}\n"
        if used + len(block) > max_chars:
            blocks.append("--- [thread truncated for length] ---")
            break
        blocks.append(block)
        used += len(block)
    return "\n".join(blocks)


def build_request(
    thread_id: str,
    subject: str,
    working_group: str,
    messages: list[dict],
    drafts: list[dict],
    model: str | None = None,
) -> BatchRequest:
    model = model or get_settings().llm.model_summarization
    user = (
        f"Working group: {working_group}\n"
        f"Thread subject: {subject}\n\n"
        f"Referenced drafts:\n{_format_drafts(drafts)}\n\n"
        f"Thread messages (quoted text and signatures already stripped):\n\n"
        f"{_format_messages(messages)}"
    )
    return BatchRequest(
        custom_id=f"summarize::{thread_id}",
        params={
            "model": model,
            "max_tokens": 1500,
            "system": _SYSTEM,
            "messages": [{"role": "user", "content": user}],
        },
    )


def parse_result(text: str | None) -> ThreadSummary | None:
    data = extract_json(text)
    if not isinstance(data, dict):
        return None
    consensus = str(data.get("consensus_state", "")).strip()
    if consensus not in VALID_CONSENSUS:
        consensus = "no_consensus"
    status = str(data.get("status", "")).strip()
    if status not in VALID_STATUS:
        status = "active"
    positions = data.get("key_positions") or []
    if not isinstance(positions, list):
        positions = []
    # Normalize each position to the expected keys.
    norm_positions = []
    for p in positions:
        if isinstance(p, dict):
            norm_positions.append(
                {
                    "position": str(p.get("position", "")).strip(),
                    "holder": str(p.get("holder", "")).strip(),
                    "context": str(p.get("context", "")).strip(),
                }
            )
    return ThreadSummary(
        summary=str(data.get("summary", "")).strip(),
        key_positions=norm_positions,
        consensus_state=consensus,
        status=status,
    )
