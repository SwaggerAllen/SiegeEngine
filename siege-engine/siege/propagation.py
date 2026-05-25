"""Propagation records — the v3 spec's per-iteration worklist primitive.

Background: an approved upstream change creates downstream staleness.
A propagation record snapshots the stale set as a worklist of scopes —
each entry a ``(scope, status)`` pair — so the user / skill chain has a
durable "what still needs regen" memory. As each downstream node gets
regenerated and approved, the skill flips that entry's status; once
every entry is ``done`` (or explicitly ``skipped``), the propagation
rolls up to ``complete``.

The record extends the existing batch primitive: same on-disk shape
discipline, same "resume by gap-fill" idea, but per-entry status
instead of one rolled-up status. The two coexist — batches stay the
unit for one-shot operations (regen all, reset all); propagations are
the iteration-loop unit for downstream regen campaigns where progress
is mid-drain visible.

File layout: ``state/propagations/<id>.json``. Loaded back via direct
git-tree reads from ``GitView`` — they aren't tier-shaped so they
don't live in the state index. ``open-propagation`` /
``update-propagation-entry`` / ``list-propagations`` are the CLI
write + read tail; the dashboard reads via ``tools.list_propagations``.

The "lean toward extend" decision (v3-spec.md §Open questions): when
upstream changes mid-drain, an open propagation gets new entries
appended rather than opening a second record. That logic lives in
the caller (``/regen_below`` etc.); this module just exposes the
``add_entries`` / ``update_entry`` primitives the caller uses.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from siege.state import Scope, mint_nonce, now_iso

PROPAGATION_SCHEMA_VERSION = 1

# Per-entry status. Pending is the default for a freshly-snapshotted
# entry; in_progress flips while a skill is mid-regen; done is the
# terminal success; skipped is the terminal "user excluded" / "node
# vanished" state. Roll-up to the parent record's status reads these
# four values only.
EntryStatus = str  # one of: pending | in_progress | done | skipped
_TERMINAL = frozenset({"done", "skipped"})


@dataclass(frozen=True)
class WorklistEntry:
    scope: Scope
    status: EntryStatus = "pending"
    # Free-form note — captures e.g. "skipped: approved with score 91"
    # or "in_progress since <iso>". Optional, not load-bearing.
    note: str | None = None


@dataclass(frozen=True)
class Propagation:
    """One propagation record.

    ``op_type`` mirrors the existing batch convention (free-form
    string identifying what kicked it off — ``regen_below_threshold``,
    ``regen_downstream``, etc.) so the dashboard can show both
    records side-by-side without per-record knowledge.
    """

    schema_version: int
    propagation_id: str
    started_at: str
    op_type: str
    worklist: list[WorklistEntry]
    tier: str | None = None
    threshold: int | None = None
    source_scope: Scope | None = None
    # Optional free-form context the caller wants to pin to the
    # record (the batch_id this propagation rode in on, the user
    # comment that kicked off /regen_below, …). Not load-bearing.
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def status(self) -> str:
        """Rolled-up record status from the worklist entries.

        ``complete`` when every entry is in ``_TERMINAL`` (i.e. done
        or skipped); ``open`` otherwise. An empty worklist is
        ``complete`` (degenerate but harmless — the record had
        nothing to drain).
        """
        if not self.worklist:
            return "complete"
        if all(e.status in _TERMINAL for e in self.worklist):
            return "complete"
        return "open"

    @property
    def counts(self) -> dict[str, int]:
        out = {"pending": 0, "in_progress": 0, "done": 0, "skipped": 0}
        for e in self.worklist:
            out[e.status] = out.get(e.status, 0) + 1
        return out


def mint_propagation_id() -> str:
    return f"prop_{mint_nonce()}"


def new_propagation(
    op_type: str,
    worklist: list[WorklistEntry],
    *,
    tier: str | None = None,
    threshold: int | None = None,
    source_scope: Scope | None = None,
    meta: dict[str, Any] | None = None,
    propagation_id: str | None = None,
) -> Propagation:
    return Propagation(
        schema_version=PROPAGATION_SCHEMA_VERSION,
        propagation_id=propagation_id or mint_propagation_id(),
        started_at=now_iso(),
        op_type=op_type,
        worklist=worklist,
        tier=tier,
        threshold=threshold,
        source_scope=source_scope,
        meta=dict(meta) if meta else {},
    )


# ---------------- JSON round-trip ----------------


def dump_propagation(prop: Propagation) -> dict[str, Any]:
    """Serialize a propagation to a JSON-ready dict."""
    payload: dict[str, Any] = {
        "schema_version": prop.schema_version,
        "propagation_id": prop.propagation_id,
        "started_at": prop.started_at,
        "op_type": prop.op_type,
        "tier": prop.tier,
        "threshold": prop.threshold,
        "source_scope": asdict(prop.source_scope) if prop.source_scope else None,
        "worklist": [_dump_entry(e) for e in prop.worklist],
        "meta": dict(prop.meta),
        # The rolled-up status is derived but serialized too so the
        # dashboard / list endpoint can filter without rehydrating.
        "status": prop.status,
        "counts": prop.counts,
    }
    return payload


def _dump_entry(entry: WorklistEntry) -> dict[str, Any]:
    out: dict[str, Any] = {
        "scope": asdict(entry.scope),
        "status": entry.status,
    }
    if entry.note is not None:
        out["note"] = entry.note
    return out


def load_propagation(payload: dict[str, Any]) -> Propagation:
    """Parse a propagation back from its on-disk JSON shape."""
    source_raw = payload.get("source_scope")
    return Propagation(
        schema_version=int(payload["schema_version"]),
        propagation_id=str(payload["propagation_id"]),
        started_at=str(payload["started_at"]),
        op_type=str(payload["op_type"]),
        tier=payload.get("tier"),
        threshold=payload.get("threshold"),
        source_scope=Scope(**source_raw) if source_raw else None,
        worklist=[_load_entry(e) for e in payload.get("worklist", [])],
        meta=dict(payload.get("meta", {})),
    )


def _load_entry(payload: dict[str, Any]) -> WorklistEntry:
    return WorklistEntry(
        scope=Scope(**payload["scope"]),
        status=str(payload.get("status", "pending")),
        note=payload.get("note"),
    )


def propagation_path(repo_root: Path, propagation_id: str) -> Path:
    return repo_root / "state" / "propagations" / f"{propagation_id}.json"


def write_propagation(repo_root: Path, prop: Propagation) -> Path:
    """Materialize a propagation to the on-disk state tree.

    Callers are responsible for ``git add`` / commit — this writer
    just lays the file down so the rest of the chain (and the
    dashboard's git-tree reader) sees it once committed.
    """
    path = propagation_path(repo_root, prop.propagation_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(dump_propagation(prop), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def read_propagation(repo_root: Path, propagation_id: str) -> Propagation:
    """Read a propagation back from the on-disk state tree."""
    path = propagation_path(repo_root, propagation_id)
    payload = json.loads(path.read_text(encoding="utf-8"))
    return load_propagation(payload)


# ---------------- Mutation helpers ----------------


def update_entry(
    prop: Propagation,
    scope: Scope,
    *,
    status: EntryStatus,
    note: str | None = None,
) -> Propagation:
    """Return a new ``Propagation`` with the matching entry's status
    flipped.

    Match is by ``Scope.key()`` so callers don't have to pass an
    object-identical Scope. Missing entries are an error — the caller
    has a stale worklist if the entry isn't there.
    """
    target_key = scope.key()
    matched = False
    new_entries: list[WorklistEntry] = []
    for entry in prop.worklist:
        if entry.scope.key() == target_key:
            matched = True
            new_entries.append(
                WorklistEntry(
                    scope=entry.scope, status=status, note=note if note is not None else entry.note
                )
            )
        else:
            new_entries.append(entry)
    if not matched:
        raise KeyError(f"scope {target_key!r} not in propagation worklist")
    return Propagation(
        schema_version=prop.schema_version,
        propagation_id=prop.propagation_id,
        started_at=prop.started_at,
        op_type=prop.op_type,
        worklist=new_entries,
        tier=prop.tier,
        threshold=prop.threshold,
        source_scope=prop.source_scope,
        meta=prop.meta,
    )


def add_entries(prop: Propagation, entries: list[WorklistEntry]) -> Propagation:
    """Return a new ``Propagation`` with extra entries appended (the
    "extend an open record on mid-drain upstream change" path).

    Skips entries whose scope is already in the worklist so re-running
    the same compute helper on a partially-drained record is a no-op
    on the already-present scopes.
    """
    have = {e.scope.key() for e in prop.worklist}
    additions = [e for e in entries if e.scope.key() not in have]
    if not additions:
        return prop
    return Propagation(
        schema_version=prop.schema_version,
        propagation_id=prop.propagation_id,
        started_at=prop.started_at,
        op_type=prop.op_type,
        worklist=prop.worklist + additions,
        tier=prop.tier,
        threshold=prop.threshold,
        source_scope=prop.source_scope,
        meta=prop.meta,
    )
