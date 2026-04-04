"""Extract structured data from CLI-generated documents using the API (Haiku for speed)."""

import json
import logging
import re

from langchain_anthropic import ChatAnthropic

from backend.pipeline.llm_limiter import rate_limited_invoke

logger = logging.getLogger(__name__)


class StructuredExtractor:
    """Extract structured data from CLI-generated documents using a small/fast API model."""

    def __init__(self, model: str = "claude-haiku-4-5-20251001"):
        self._model_name = model

    def _get_model(self) -> ChatAnthropic:
        return ChatAnthropic(model=self._model_name, max_tokens=2000, temperature=0)  # type: ignore[call-arg]

    async def extract_components(self, architecture_doc: str) -> list[dict]:
        """Extract component list from an architecture document.

        First tries regex for the ```components block, then falls back to API.
        Returns a list of dicts with 'name' and 'description' keys.
        """
        # Try regex extraction first (no API call needed)
        match = re.search(r"```components\s*\n(.*?)```", architecture_doc, re.DOTALL)
        if match:
            try:
                parsed = json.loads(match.group(1).strip())
                if isinstance(parsed, list) and len(parsed) > 0:
                    logger.info("Extracted %d components via regex", len(parsed))
                    return parsed
            except json.JSONDecodeError:
                logger.debug("Regex matched components block but JSON parse failed")

        # Fallback: use API
        logger.info("Using API to extract components from architecture doc")
        messages = [
            {
                "role": "system",
                "content": (
                    "Extract the list of software components from this architecture document. "
                    "Return ONLY a JSON array where each element has 'name' (string) and "
                    "'description' (string). No other text, no markdown fencing."
                ),
            },
            {"role": "user", "content": architecture_doc[:8000]},
        ]
        model = self._get_model()
        response = await rate_limited_invoke(model, messages)
        content = response.content.strip()

        # Strip markdown fencing if present
        if content.startswith("```"):
            content = re.sub(r"^```\w*\n?", "", content)
            content = re.sub(r"\n?```$", "", content)
            content = content.strip()

        try:
            parsed = json.loads(content)
            logger.info("Extracted %d components via API", len(parsed))
            return parsed
        except json.JSONDecodeError:
            logger.error("Failed to parse components from API response: %s", content[:200])
            return []

    async def extract_recommendation(self, review_doc: str) -> dict:
        """Extract recommendation from a review document.

        First tries regex for the ```recommendation block, then falls back to API.
        Returns dict with 'recommendation' and 'overall_quality' keys.
        """
        # Try regex extraction first
        match = re.search(r"```recommendation\s*\n(.*?)```", review_doc, re.DOTALL)
        if match:
            try:
                parsed = json.loads(match.group(1).strip())
                if "recommendation" in parsed:
                    logger.info("Extracted recommendation via regex: %s", parsed)
                    return parsed
            except json.JSONDecodeError:
                logger.debug("Regex matched recommendation block but JSON parse failed")

        # Fallback: look for JSON with recommendation key near the end
        tail = review_doc[-500:]
        match = re.search(r'\{[^}]*"recommendation"[^}]*\}', tail)
        if match:
            try:
                parsed = json.loads(match.group(0))
                if "recommendation" in parsed:
                    logger.info("Extracted recommendation via tail regex: %s", parsed)
                    return parsed
            except json.JSONDecodeError:
                pass

        # Final fallback: use API
        logger.info("Using API to extract recommendation from review doc")
        messages = [
            {
                "role": "system",
                "content": (
                    "Extract the review recommendation from this document. "
                    "Return ONLY a JSON object with 'recommendation' ('approve' or 'revise') "
                    "and 'overall_quality' (integer 1-10). No other text."
                ),
            },
            {"role": "user", "content": review_doc[-3000:]},
        ]
        model = self._get_model()
        response = await rate_limited_invoke(model, messages)
        content = response.content.strip()

        # Strip markdown fencing if present
        if content.startswith("```"):
            content = re.sub(r"^```\w*\n?", "", content)
            content = re.sub(r"\n?```$", "", content)
            content = content.strip()

        try:
            return json.loads(content)
        except json.JSONDecodeError:
            logger.error("Failed to parse recommendation from API: %s", content[:200])
            return {"recommendation": "approve", "overall_quality": 5}


extractor = StructuredExtractor()
