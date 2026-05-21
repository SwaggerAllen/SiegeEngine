"""Typed model for state JSON files.

State JSON is the canonical record of a scope's status, draft + review
metadata, approval, and the edge declarations downstream tiers read.
One file per scope under ``state/<tier>/[<parent_id>/]<id>.json``.

The schema lives at ``docs/migration/state-schema.md``. This module
mirrors it as typed dataclasses + helpers for load / dump / hash.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

SCHEMA_VERSION = 2

# Versions this server can parse. v1 = pre-phasing (no `scope.phase`);
# v2 adds the impl/fanin phase dimension. Parsing is version-tolerant;
# a writer emits v2 only for a phased (impl/fanin) scope, v1 otherwise,
# so the version tracks the artifact's scope shape, not a global epoch.
SUPPORTED_SCHEMA_VERSIONS: frozenset[int] = frozenset({1, 2})

Tier = Literal[
    "feature_expansion",
    "requirements",
    "sysarch",
    "comparch",
    "subcomparch",
    "impl",
    "fanin",
]

Status = Literal["absent", "drafted", "reviewed", "approved"]

ALL_TIERS: tuple[Tier, ...] = (
    "feature_expansion",
    "requirements",
    "sysarch",
    "comparch",
    "subcomparch",
    "impl",
    "fanin",
)


# Tiers whose scopes carry a phase dimension. The five arch tiers
# (feature_expansion … subcomparch) build whole, unphased; only impl
# and fanin partition across phases.
PHASED_TIERS: frozenset[str] = frozenset({"impl", "fanin"})


@dataclass(frozen=True)
class Scope:
    """Stable identifier for a tier artifact.

    For top-level tiers (feature_expansion, requirements, sysarch,
    comparch, fanin) only ``tier`` + ``comp_id`` are used; ``parent_id``
    and ``sub_id`` are None. For sub-tiers (subcomparch, impl), the
    ``parent_id`` points at the owning comparch and ``sub_id`` keys
    the sub.

    ``phase`` is set only for impl + fanin scopes (see ``PHASED_TIERS``)
    once impl-tier phasing is in play; it stays None for the five arch
    tiers and for any pre-phasing (schema v1) impl/fanin artifact. An
    impl scope is keyed by ``(parent_id, sub_id, phase)`` — one
    subcomponent can have several impl nodes, one per phase.
    """

    tier: Tier
    comp_id: str | None = None
    parent_id: str | None = None
    sub_id: str | None = None
    phase: int | None = None

    def key(self) -> tuple[str, ...]:
        """Hashable tuple form for caching / dedup.

        MUST include ``phase`` — ``GitView._states`` is keyed by this
        tuple, so two phased impl nodes for the same subcomponent would
        otherwise collide to one key and silently drop one.
        """
        return (
            self.tier,
            self.comp_id or "",
            self.parent_id or "",
            self.sub_id or "",
            "" if self.phase is None else f"p{self.phase}",
        )

    def _phase_seg(self) -> str:
        """``p<N>`` path segment for a phased scope, else empty."""
        return f"p{self.phase}" if self.phase is not None else ""

    def state_path(self) -> str:
        """Relative path to the state JSON file for this scope."""
        if self.tier == "impl" and self.phase is not None:
            return f"state/impl/{self.parent_id}/{self._phase_seg()}/{self.sub_id}.json"
        if self.tier == "fanin" and self.phase is not None:
            return f"state/fanin/{self.comp_id}/{self._phase_seg()}.json"
        if self.parent_id and self.sub_id:
            return f"state/{self.tier}/{self.parent_id}/{self.sub_id}.json"
        return f"state/{self.tier}/{self.comp_id}.json"

    def manifest_path(self) -> str:
        """Relative path to this scope's node manifest, under ``manifest/``.

        Mirrors ``state_path`` one-for-one. Only the single-node arch
        tiers (``feature_expansion``, ``requirements``) actually write
        a manifest today; the method is general so any tier that later
        declares sub-nodes gets a consistent path for free.
        """
        return "manifest/" + self.state_path()[len("state/") :]

    def body_path(self) -> str:
        """Conventional relative path to the body markdown."""
        if self.tier == "impl" and self.phase is not None:
            return f"impl/{self.parent_id}/subs/{self.sub_id}/{self._phase_seg()}/body.md"
        if self.tier == "fanin" and self.phase is not None:
            return f"fanin/{self.comp_id}/{self._phase_seg()}/body.md"
        if self.parent_id and self.sub_id:
            return f"{self.tier}/{self.parent_id}/subs/{self.sub_id}/body.md"
        return f"{self.tier}/{self.comp_id}/body.md"

    def review_path(self) -> str:
        if self.tier == "impl" and self.phase is not None:
            return f"impl/{self.parent_id}/subs/{self.sub_id}/{self._phase_seg()}/review.md"
        if self.tier == "fanin" and self.phase is not None:
            return f"fanin/{self.comp_id}/{self._phase_seg()}/review.md"
        if self.parent_id and self.sub_id:
            return f"{self.tier}/{self.parent_id}/subs/{self.sub_id}/review.md"
        return f"{self.tier}/{self.comp_id}/review.md"


@dataclass(frozen=True)
class DraftBlock:
    body_path: str
    body_sha256: str
    generated_at: str
    generator_metadata: dict[str, Any] = field(default_factory=dict)
    prior_review_text: str = ""


@dataclass(frozen=True)
class ReviewBlock:
    body_path: str
    body_sha256: str
    reviewed_at: str
    score: int | None
    reviewer_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ApprovalBlock:
    approved_at: str
    approved_by: str


@dataclass(frozen=True)
class State:
    """Parsed state JSON for one scope.

    The on-disk file maps directly to this shape; ``load_state`` /
    ``dump_state`` round-trip without information loss.
    """

    schema_version: int
    scope: Scope
    status: Status
    nonce: str
    draft: DraftBlock | None = None
    review: ReviewBlock | None = None
    approval: ApprovalBlock | None = None
    is_foundation: bool = False
    # Edge declarations — what this scope depends on / decomposes from.
    # Filled by the per-tier mint pass that creates the scope; consumed
    # by downstream tier readers. The shape is intentionally generic;
    # per-tier readers extract the keys they care about.
    edges: dict[str, list[str]] = field(default_factory=dict)
    # Free-form per-scope metadata (display name, role, kind, etc.)
    # Mirrors the per-tier columns the old Node table carried.
    meta: dict[str, Any] = field(default_factory=dict)


def now_iso() -> str:
    """UTC ISO-8601 with seconds precision."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def load_state(path: Path) -> State:
    """Read a state JSON file from disk."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    return parse_state(raw)


def parse_state(raw: dict[str, Any]) -> State:
    """Convert a raw dict (e.g. from `json.loads` or a git blob) to State."""
    version = raw.get("schema_version", SCHEMA_VERSION)
    if version not in SUPPORTED_SCHEMA_VERSIONS:
        raise ValueError(
            f"Unsupported state schema_version {version!r}; this server reads "
            f"{sorted(SUPPORTED_SCHEMA_VERSIONS)}"
        )
    scope_raw = raw["scope"]
    scope = Scope(
        tier=scope_raw["tier"],
        comp_id=scope_raw.get("comp_id"),
        parent_id=scope_raw.get("parent_id"),
        sub_id=scope_raw.get("sub_id"),
        # Absent on v1 files → None → pre-phasing semantics.
        phase=scope_raw.get("phase"),
    )
    draft_raw = raw.get("draft")
    draft = (
        DraftBlock(
            body_path=draft_raw["body_path"],
            body_sha256=draft_raw["body_sha256"],
            generated_at=draft_raw.get("generated_at", ""),
            generator_metadata=draft_raw.get("generator_metadata", {}),
            prior_review_text=draft_raw.get("prior_review_text", ""),
        )
        if draft_raw
        else None
    )
    review_raw = raw.get("review")
    review = (
        ReviewBlock(
            body_path=review_raw["body_path"],
            body_sha256=review_raw["body_sha256"],
            reviewed_at=review_raw.get("reviewed_at", ""),
            score=review_raw.get("score"),
            reviewer_metadata=review_raw.get("reviewer_metadata", {}),
        )
        if review_raw
        else None
    )
    approval_raw = raw.get("approval")
    approval = (
        ApprovalBlock(
            approved_at=approval_raw["approved_at"],
            approved_by=approval_raw["approved_by"],
        )
        if approval_raw
        else None
    )
    return State(
        schema_version=version,
        scope=scope,
        status=raw["status"],
        nonce=raw.get("nonce", ""),
        draft=draft,
        review=review,
        approval=approval,
        is_foundation=raw.get("is_foundation", False),
        edges=raw.get("edges", {}),
        meta=raw.get("meta", {}),
    )


def dump_state(state: State) -> dict[str, Any]:
    """Serialize State to a JSON-ready dict. Stable key order."""
    out: dict[str, Any] = {
        "schema_version": state.schema_version,
        "scope": {
            "tier": state.scope.tier,
            "comp_id": state.scope.comp_id,
            "parent_id": state.scope.parent_id,
            "sub_id": state.scope.sub_id,
            "phase": state.scope.phase,
        },
        "status": state.status,
        "nonce": state.nonce,
        "is_foundation": state.is_foundation,
    }
    if state.draft:
        out["draft"] = asdict(state.draft)
    if state.review:
        out["review"] = asdict(state.review)
    if state.approval:
        out["approval"] = asdict(state.approval)
    if state.edges:
        out["edges"] = state.edges
    if state.meta:
        out["meta"] = state.meta
    return out


def write_state(state: State, path: Path) -> None:
    """Write a State to disk as canonical JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(dump_state(state), indent=2, sort_keys=True) + "\n"
    path.write_text(payload, encoding="utf-8")
