"""Thin wrapper over the Anthropic Message Batches API.

Usage pattern:
    reqs = [BatchRequest(custom_id="thread-123", params={...}), ...]
    runner = BatchRunner()
    batch_id = runner.submit(reqs)
    results = runner.wait_and_collect(batch_id)   # {custom_id: BatchResult}

The wrapper is import-safe without the anthropic package installed and without an
API key; it only requires them at submit time. ``poll_interval`` is short in
tests via the constructor.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from ..config import get_settings
from ..logging_conf import get_logger

log = get_logger(__name__)


@dataclass
class BatchRequest:
    custom_id: str
    params: dict[str, Any]  # Messages API params: model, max_tokens, system, messages, ...


@dataclass
class BatchResult:
    custom_id: str
    succeeded: bool
    text: str | None
    input_tokens: int
    output_tokens: int
    error: str | None = None


class BatchRunner:
    def __init__(self, poll_interval: float = 30.0, max_wait_seconds: float = 60 * 60 * 24):
        self.poll_interval = poll_interval
        self.max_wait_seconds = max_wait_seconds
        self._client = None

    def _get_client(self):
        if self._client is None:
            from anthropic import Anthropic  # imported lazily

            key = get_settings().anthropic_api_key
            if not key:
                raise RuntimeError("ANTHROPIC_API_KEY is not set; cannot submit a batch.")
            self._client = Anthropic(api_key=key)
        return self._client

    def submit(self, requests: list[BatchRequest]) -> str:
        client = self._get_client()
        payload = [
            {"custom_id": r.custom_id, "params": r.params} for r in requests
        ]
        batch = client.messages.batches.create(requests=payload)
        log.info("submitted batch", extra={"batch_id": batch.id, "count": len(requests)})
        return batch.id

    def wait_and_collect(self, batch_id: str) -> dict[str, BatchResult]:
        client = self._get_client()
        waited = 0.0
        while True:
            batch = client.messages.batches.retrieve(batch_id)
            if batch.processing_status == "ended":
                break
            if waited >= self.max_wait_seconds:
                raise TimeoutError(f"batch {batch_id} did not finish within budget")
            time.sleep(self.poll_interval)
            waited += self.poll_interval

        results: dict[str, BatchResult] = {}
        for entry in client.messages.batches.results(batch_id):
            results[entry.custom_id] = _parse_result(entry)
        log.info("collected batch results", extra={"batch_id": batch_id, "count": len(results)})
        return results


def _parse_result(entry: Any) -> BatchResult:
    cid = entry.custom_id
    result = entry.result
    rtype = getattr(result, "type", None)
    if rtype == "succeeded":
        msg = result.message
        text = "".join(
            block.text for block in msg.content if getattr(block, "type", None) == "text"
        )
        return BatchResult(
            custom_id=cid,
            succeeded=True,
            text=text,
            input_tokens=msg.usage.input_tokens,
            output_tokens=msg.usage.output_tokens,
        )
    err = getattr(result, "error", None)
    return BatchResult(
        custom_id=cid,
        succeeded=False,
        text=None,
        input_tokens=0,
        output_tokens=0,
        error=str(err) if err else rtype,
    )
