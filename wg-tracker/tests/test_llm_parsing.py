from wgtracker.costs import estimate_cost
from wgtracker.llm import categorize, prefilter, summarize
from wgtracker.llm._json import extract_json


def test_extract_json_from_fence():
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_extract_json_embedded():
    assert extract_json('here you go: [{"topic":"x","confidence":0.9}] done')[0]["topic"] == "x"


def test_prefilter_parse():
    assert prefilter.parse_result('{"admin": true, "reason": "agenda"}') is True
    assert prefilter.parse_result('{"admin": false}') is False
    assert prefilter.parse_result("garbage") is False  # fail-open


def test_summarize_parse_normalizes_invalid_enums():
    text = """{
      "summary": "Alice raised concerns; Bob disagreed.",
      "key_positions": [{"position":"keep format","holder":"Bob","context":"simplicity"}],
      "consensus_state": "totally_made_up",
      "status": "weird"
    }"""
    out = summarize.parse_result(text)
    assert out.summary.startswith("Alice")
    assert out.consensus_state == "no_consensus"  # invalid -> safe default
    assert out.status == "active"
    assert out.key_positions[0]["holder"] == "Bob"


def test_categorize_parse_filters_unknown_and_low_conf():
    text = '[{"topic":"federation","confidence":0.8},{"topic":"bogus","confidence":0.9},{"topic":"extensions","confidence":0.1}]'
    pairs = categorize.parse_result(text, {"federation", "extensions"})
    assert ("federation", 0.8) in pairs
    assert all(name != "bogus" for name, _ in pairs)
    assert all(name != "extensions" for name, _ in pairs)  # below 0.3 threshold


def test_batch_discount_applied():
    full = estimate_cost("claude-sonnet-4-6", 1_000_000, 0, batch=False)
    batched = estimate_cost("claude-sonnet-4-6", 1_000_000, 0, batch=True)
    assert round(batched, 6) == round(full * 0.5, 6)
