"""Stage 5: topic categorization with Haiku via the Batch API.

Given the thread summary + first messages and the configured taxonomy, return
the relevant topics with confidence scores. Cheap by design so re-categorization
on taxonomy changes doesn't require re-summarization.
"""
from __future__ import annotations

from ..config import Topic, get_settings
from ._json import extract_json
from .batch import BatchRequest

_SYSTEM = """You categorize an IETF working-group thread against a FIXED topic taxonomy.

Rules:
- Only use topic names from the provided taxonomy. Never invent new topics.
- A thread may match multiple topics or none.
- Give each match a confidence in [0,1]. Only include topics with confidence >= 0.3.

Respond with ONLY a JSON array:
[{"topic": "<taxonomy name>", "confidence": <0..1>}, ...]"""


def _format_taxonomy(topics: list[Topic]) -> str:
    return "\n".join(
        f"- {t.name}: {t.description} (keywords: {', '.join(t.keywords)})" for t in topics
    )


def build_request(
    thread_id: str,
    summary: str,
    sample_text: str,
    topics: list[Topic] | None = None,
    model: str | None = None,
) -> BatchRequest:
    settings = get_settings()
    topics = topics if topics is not None else settings.topics
    model = model or settings.llm.model_categorization
    user = (
        f"Taxonomy:\n{_format_taxonomy(topics)}\n\n"
        f"Thread summary:\n{summary}\n\n"
        f"Sample of thread content:\n{sample_text[:6000]}"
    )
    return BatchRequest(
        custom_id=f"categorize::{thread_id}",
        params={
            "model": model,
            "max_tokens": 400,
            "system": _SYSTEM,
            "messages": [{"role": "user", "content": user}],
        },
    )


def parse_result(text: str | None, valid_names: set[str]) -> list[tuple[str, float]]:
    """Return [(topic_name, confidence)] filtered to valid taxonomy names."""
    data = extract_json(text)
    out: list[tuple[str, float]] = []
    if isinstance(data, list):
        for item in data:
            if not isinstance(item, dict):
                continue
            name = str(item.get("topic", "")).strip()
            if name not in valid_names:
                continue
            try:
                conf = float(item.get("confidence", 0))
            except (TypeError, ValueError):
                conf = 0.0
            conf = max(0.0, min(1.0, conf))
            if conf >= 0.3:
                out.append((name, conf))
    return out
