"""Tests for backend.pipeline.llm_limiter – rate limiting and retry logic."""

from unittest.mock import AsyncMock, patch

import pytest
from anthropic import RateLimitError
from httpx import Request, Response

from backend.pipeline.llm_limiter import rate_limited_invoke


def _make_rate_limit_error():
    """Create a RateLimitError for testing."""
    request = Request("POST", "https://api.anthropic.com/v1/messages")
    response = Response(429, request=request)
    return RateLimitError(message="rate limited", response=response, body=None)


class TestRateLimitedInvoke:
    async def test_successful_invocation(self):
        model = AsyncMock()
        model.ainvoke.return_value = "result"

        result = await rate_limited_invoke(model, ["msg"])
        assert result == "result"
        model.ainvoke.assert_awaited_once_with(["msg"])

    @patch("backend.pipeline.llm_limiter.asyncio.sleep", new_callable=AsyncMock)
    async def test_retries_on_rate_limit(self, mock_sleep):
        model = AsyncMock()
        model.ainvoke.side_effect = [_make_rate_limit_error(), "ok"]

        result = await rate_limited_invoke(model, ["msg"])
        assert result == "ok"
        assert model.ainvoke.await_count == 2
        mock_sleep.assert_awaited_once()

    @patch("backend.pipeline.llm_limiter.asyncio.sleep", new_callable=AsyncMock)
    async def test_raises_after_max_retries(self, mock_sleep):
        model = AsyncMock()
        model.ainvoke.side_effect = _make_rate_limit_error()

        with pytest.raises(RateLimitError):
            await rate_limited_invoke(model, ["msg"])

    async def test_non_rate_limit_error_not_retried(self):
        model = AsyncMock()
        model.ainvoke.side_effect = ValueError("bad input")

        with pytest.raises(ValueError, match="bad input"):
            await rate_limited_invoke(model, ["msg"])
        assert model.ainvoke.await_count == 1
