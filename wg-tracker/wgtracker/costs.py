"""Cost accounting for LLM calls.

Every call is logged to processing_log with token counts and an estimated USD
cost. Batch API gets a 50% discount, applied here when use_batch_api is true.
"""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import get_settings
from .models import ProcessingLog, ProcessingStage

BATCH_DISCOUNT = 0.5


def estimate_cost(model: str, input_tokens: int, output_tokens: int, batch: bool) -> float:
    pricing = get_settings().llm.pricing.get(model)
    if pricing is None:
        return 0.0
    cost = (
        input_tokens / 1_000_000 * pricing.input_per_mtok
        + output_tokens / 1_000_000 * pricing.output_per_mtok
    )
    if batch:
        cost *= BATCH_DISCOUNT
    return round(cost, 6)


def log_llm_call(
    session: Session,
    *,
    stage: ProcessingStage,
    model: str,
    input_tokens: int,
    output_tokens: int,
    batch: bool,
    working_group: str | None = None,
    target_id: str | None = None,
    status: str = "ok",
    detail: dict | None = None,
) -> ProcessingLog:
    entry = ProcessingLog(
        created_at=datetime.now(UTC),
        stage=stage,
        working_group=working_group,
        target_id=target_id,
        status=status,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=estimate_cost(model, input_tokens, output_tokens, batch),
        detail=detail,
    )
    session.add(entry)
    return entry


def log_event(
    session: Session,
    *,
    stage: ProcessingStage,
    status: str,
    working_group: str | None = None,
    target_id: str | None = None,
    detail: dict | None = None,
) -> ProcessingLog:
    """Log a non-LLM pipeline event (ingestion, errors, skips) with zero cost."""
    entry = ProcessingLog(
        created_at=datetime.now(UTC),
        stage=stage,
        working_group=working_group,
        target_id=target_id,
        status=status,
        model=None,
        input_tokens=0,
        output_tokens=0,
        cost_usd=0.0,
        detail=detail,
    )
    session.add(entry)
    return entry


def total_spend(session: Session) -> float:
    return float(session.execute(select(func.coalesce(func.sum(ProcessingLog.cost_usd), 0.0))).scalar_one())


def spend_by_stage(session: Session) -> list[dict]:
    rows = session.execute(
        select(
            ProcessingLog.stage,
            func.coalesce(func.sum(ProcessingLog.cost_usd), 0.0),
            func.coalesce(func.sum(ProcessingLog.input_tokens), 0),
            func.coalesce(func.sum(ProcessingLog.output_tokens), 0),
            func.count(ProcessingLog.id),
        ).group_by(ProcessingLog.stage)
    ).all()
    return [
        {
            "stage": stage.value if hasattr(stage, "value") else str(stage),
            "cost_usd": round(float(cost), 4),
            "input_tokens": int(in_tok),
            "output_tokens": int(out_tok),
            "calls": int(calls),
        }
        for stage, cost, in_tok, out_tok, calls in rows
    ]
