"""Per-tier context readers.

Each tier has its own module exposing two functions:

    build_generation_context(view, scope) -> dict
    build_review_context(view, scope, draft_sha) -> dict

Both return a JSON-serializable dict that the MCP tool surface returns
verbatim to the calling skill. The skill threads the dict into the
LLM prompt; the prompt itself is shipped with the plugin (under
``.claude-plugin/prompts/``), keyed by the same tier name.

The substrate ``_base.py`` carries cross-tier helpers — sibling
enumeration, parent-state lookup, fragment extraction from body
markdown — so per-tier modules stay small.

Dependency on the per-tier ``meta`` and ``edges`` blocks: every state
JSON written by a draft skill MUST include the precomputed metadata
its downstream readers expect. The shape of those blocks is part of
the per-tier contract, documented in each tier's module docstring.
"""

from siege.tiers import (
    _base,
    comparch,
    fanin,
    feature_expansion,
    impl,
    requirements,
    subcomparch,
    sysarch,
)

GENERATION_BUILDERS = {
    "feature_expansion": feature_expansion.build_generation_context,
    "requirements": requirements.build_generation_context,
    "sysarch": sysarch.build_generation_context,
    "comparch": comparch.build_generation_context,
    "subcomparch": subcomparch.build_generation_context,
    "impl": impl.build_generation_context,
    "fanin": fanin.build_generation_context,
}

REVIEW_BUILDERS = {
    "feature_expansion": feature_expansion.build_review_context,
    "requirements": requirements.build_review_context,
    "sysarch": sysarch.build_review_context,
    "comparch": comparch.build_review_context,
    "subcomparch": subcomparch.build_review_context,
    "impl": impl.build_review_context,
    "fanin": fanin.build_review_context,
}

__all__ = ["_base", "GENERATION_BUILDERS", "REVIEW_BUILDERS"]
