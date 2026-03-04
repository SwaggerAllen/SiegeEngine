import json
import logging
import re

from langchain_anthropic import ChatAnthropic

from backend.pipeline.llm_limiter import rate_limited_invoke

logger = logging.getLogger(__name__)


def parse_components_from_content(content: str) -> list[dict]:
    """Try to parse components from a tagged code block or raw JSON array."""
    # Try ```components block first
    pattern = r"```components\s*\n(.*?)```"
    match = re.search(pattern, content, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    # Fallback: find JSON array with "key" fields
    pattern = r'\[[\s\S]*?"key"[\s\S]*?\]'
    match = re.search(pattern, content)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    return []


async def llm_extract_components(content: str, model_name: str) -> list[dict]:
    """Ask the LLM to extract components from architecture content."""
    model = ChatAnthropic(
        model=model_name,
        temperature=0.0,
        max_tokens=4096,
    )
    messages = [
        {
            "role": "system",
            "content": (
                "Extract the list of components from the following system architecture document. "
                "Return ONLY a JSON array of objects, each with a 'key' (snake_case identifier) "
                "and 'name' (human-readable name). Example: "
                '[{"key": "auth_service", "name": "Authentication Service"}]. '
                "Return ONLY the JSON array, no other text."
            ),
        },
        {"role": "user", "content": content[:8000]},
    ]
    response = await rate_limited_invoke(model, messages)
    text = response.content
    # Strip markdown fences if present
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0]
    elif "```" in text:
        text = text.split("```")[1].split("```")[0]
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        logger.warning("Failed to parse LLM component extraction response")
        return []


def _sorted_keys(components: list[dict]) -> list[str]:
    """Return sorted list of component keys."""
    return sorted(c.get("key", "") for c in components)


def components_match(a: list[dict], b: list[dict]) -> bool:
    """Check if two component lists have the same keys (order-independent)."""
    return _sorted_keys(a) == _sorted_keys(b)


def majority_vote(a: list[dict], b: list[dict], c: list[dict]) -> list[dict]:
    """Return the result from whichever two of three lists agree on keys."""
    keys_a = _sorted_keys(a)
    keys_b = _sorted_keys(b)
    keys_c = _sorted_keys(c)

    if keys_a == keys_b:
        return a
    if keys_a == keys_c:
        return a
    if keys_b == keys_c:
        return b

    # No exact match — pick the pair with the most overlap
    overlap_ab = len(set(keys_a) & set(keys_b))
    overlap_ac = len(set(keys_a) & set(keys_c))
    overlap_bc = len(set(keys_b) & set(keys_c))
    best = max(overlap_ab, overlap_ac, overlap_bc)
    if best == overlap_ab:
        return a
    if best == overlap_ac:
        return a
    return b


async def extract_components_robust(content: str, model_name: str) -> list[dict]:
    """
    Robust component extraction: parse, then verify with a second LLM call.
    If results disagree, run a third call as tiebreaker.
    All results are sorted by key before comparison.
    """
    # 1. Parse attempt from the generated content
    result_1 = parse_components_from_content(content)

    # 2. If parse fails, ask LLM to extract
    if not result_1:
        result_1 = await llm_extract_components(content, model_name)

    # 3. Second independent extraction
    result_2 = await llm_extract_components(content, model_name)

    # 4. Sort both by key, then compare
    result_1.sort(key=lambda c: c.get("key", ""))
    result_2.sort(key=lambda c: c.get("key", ""))

    if components_match(result_1, result_2):
        logger.info("Component extraction: 2 runs agree (%d components)", len(result_1))
        return result_1

    # 5. Tiebreaker: third extraction
    logger.info("Component extraction: mismatch, running tiebreaker")
    result_3 = await llm_extract_components(content, model_name)
    result_3.sort(key=lambda c: c.get("key", ""))

    # 6. Majority vote
    winner = majority_vote(result_1, result_2, result_3)
    logger.info("Component extraction: tiebreaker resolved (%d components)", len(winner))
    return winner
