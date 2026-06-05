"""Writer-side CLI invoked by skills.

Skills compose the artifact body with the LLM, then shell out to this
CLI to materialize the state JSON file and (optionally) commit + push.
Keeps the JSON-shape discipline inside Python so prompts don't have
to hand-write valid JSON.

Write subcommands (work on the local working tree; the calling skill
does the `git add` / `commit` / `push`):

    write-draft    — write state JSON (+ id ledger) for a `drafted` transition
    write-review   — write state JSON + review.md for a `reviewed` transition
    write-approval — flip `reviewed` to `approved`
    mark-drafted   — re-sync state to a hand-edited body (back to `drafted`)
    repair-drift   — recompute body_sha256 fields, bump nonce
    mint-plan      — materialize phased impl stubs from state/plan.json
    mint-batch     — write a state/batches/<id>.json
    mint-nonce     — emit a fresh ULID-shaped nonce on stdout (utility)

Read subcommands (project the committed git tree at ``--ref``, default
``HEAD``; replace the retired MCP read tools):

    get-state             — state JSON for a scope (+ drift)
    get-context           — generation context bundle for a scope
    get-review-context    — review context bundle for a scope
    compute-plan          — the phasing plan projection
    get-structure-summary — a tier's per-node + aggregate metrics
    get-review-summary    — a tier's score histogram + worst-N intros
    list-scopes               — enumerate a tier's scopes from the id ledgers
    list-batches              — list state/batches/<id>.json files
    list-propagations         — list state/propagations/<id>.json files
    open-propagation          — write a fresh propagation record
    update-propagation-entry  — flip one worklist entry's status
    compute-downstream        — preview a top-down worklist from a source scope

The write subcommands keep ``import siege.cli`` pure-stdlib; the read
subcommands defer their ``siege.projection`` imports (which pull
``pydantic`` / ``bs4``) so a core-only install still runs the writers.

Run with ``python -m siege.cli <subcommand> --help`` for per-command
flags.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from siege.git_view import GitView

from siege.manifest import (
    DECOMPOSING_TIERS,
    Manifest,
    derive_manifest,
    load_manifest,
    write_manifest,
)
from siege.state import (
    ALL_TIERS,
    PHASED_TIERS,
    ApprovalBlock,
    DraftBlock,
    ReviewBlock,
    Scope,
    State,
    dump_state,
    mint_nonce,
    now_iso,
    parse_state,
    sha256_text,
    write_state,
)
from siege.validate import validate_artifact


def _scope_from_args(args: argparse.Namespace) -> Scope:
    return Scope(
        tier=args.tier,
        comp_id=args.comp_id,
        parent_id=args.parent_id,
        sub_id=args.sub_id,
        phase=args.phase,
    )


def _schema_version_for(scope: Scope) -> int:
    """Schema version a freshly-minted state file should carry.

    v2 only for a phased impl/fanin scope (one that actually uses the
    ``phase`` dimension); v1 for everything else, so the version
    tracks the artifact's scope shape rather than a global epoch.
    """
    if scope.tier in PHASED_TIERS and scope.phase is not None:
        return 2
    return 1


def _existing_state(repo_root: Path, scope: Scope) -> State | None:
    path = repo_root / scope.state_path()
    if not path.exists():
        return None
    return parse_state(json.loads(path.read_text(encoding="utf-8")))


def cmd_write_draft(args: argparse.Namespace) -> int:
    repo_root = Path(args.repo).resolve()
    scope = _scope_from_args(args)
    body_path = Path(args.body_path)
    body_abs = repo_root / body_path
    if not body_abs.exists():
        print(f"error: body file does not exist: {body_abs}", file=sys.stderr)
        return 2
    body_bytes = body_abs.read_bytes()
    body_sha = hashlib.sha256(body_bytes).hexdigest()

    # Validate (warnings only — actual error fail blocks the commit)
    val = validate_artifact(tier=args.tier, body=body_bytes.decode("utf-8"))
    if not val["ok"]:
        print(f"validate failed: {val['errors']}", file=sys.stderr)
        return 3

    prior = _existing_state(repo_root, scope)
    prior_review_text = args.prior_review_text or (
        prior.draft.prior_review_text if prior and prior.draft else ""
    )
    edges = dict(prior.edges) if prior else {}
    meta = dict(prior.meta) if prior else {}

    state = State(
        schema_version=_schema_version_for(scope),
        scope=scope,
        status="drafted",
        nonce=mint_nonce(),
        draft=DraftBlock(
            body_path=str(body_path),
            body_sha256=body_sha,
            generated_at=now_iso(),
            generator_metadata={
                "thinking_effort": args.thinking_effort or "default",
                "batch_id": args.batch_id or "",
            },
            prior_review_text=prior_review_text,
        ),
        is_foundation=(prior.is_foundation if prior is not None else bool(args.is_foundation)),
        edges=edges,
        meta=meta,
    )
    state_path = repo_root / scope.state_path()
    write_state(state, state_path)

    out: dict[str, Any] = {"state_path": str(state_path), "body_sha256": body_sha}
    # Decomposing tiers also materialize a slim identity ledger derived
    # from the body — feature_expansion / requirements / sysarch /
    # comparch (self-skips every other tier).
    if scope.tier in DECOMPOSING_TIERS:
        ids_path = repo_root / scope.ids_path()
        prior_manifest = load_manifest(ids_path) if ids_path.exists() else None
        manifest = derive_manifest(scope, body_bytes.decode("utf-8"), body_sha, prior_manifest)
        write_manifest(ids_path, manifest)
        out["ids_path"] = str(ids_path)
        out["node_count"] = len(manifest.nodes)
    print(json.dumps(out))
    return 0


def _extract_review(review_text: str) -> tuple[int, str]:
    """Lenient score + intro extraction from a ``<review>`` body.

    Deliberately *not* the strict ``parsers.review_xml.parse_review``
    (which the server projection uses): a real review may legitimately
    omit a finding section, and the write path only needs the score +
    intro. Mirrors the regex the retired ``review-*`` skill heredocs
    used, so the materialized state JSON is unchanged.
    """
    m = re.search(r"<score>\s*(\d+)\s*</score>", review_text)
    if not m:
        raise ValueError("<score> missing or unparseable in review")
    score = int(m.group(1))
    if not 0 <= score <= 100:
        raise ValueError(f"<score> out of range 0-100: {score}")
    intro_m = re.search(r"<intro>(.*?)</intro>", review_text, re.DOTALL)
    intro = (intro_m.group(1) if intro_m else "").strip()
    if not intro:
        raise ValueError("<intro> missing or empty in review")
    return score, intro


def cmd_write_review(args: argparse.Namespace) -> int:
    repo_root = Path(args.repo).resolve()
    scope = _scope_from_args(args)
    review_path = Path(args.review_path)
    review_abs = repo_root / review_path
    if not review_abs.exists():
        print(f"error: review file does not exist: {review_abs}", file=sys.stderr)
        return 2
    review_text = review_abs.read_text(encoding="utf-8")
    try:
        score, intro = _extract_review(review_text)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3

    prior = _existing_state(repo_root, scope)
    if prior is None or prior.status != "drafted":
        found = prior.status if prior else "absent"
        print(f"error: scope must be in 'drafted' status, found {found}", file=sys.stderr)
        return 2

    state = State(
        schema_version=prior.schema_version,
        scope=scope,
        status="reviewed",
        nonce=mint_nonce(),
        draft=prior.draft,
        review=ReviewBlock(
            body_path=str(review_path),
            body_sha256=sha256_text(review_text),
            reviewed_at=now_iso(),
            score=score,
            reviewer_metadata={},
        ),
        is_foundation=prior.is_foundation,
        edges=prior.edges,
        meta=prior.meta,
    )
    state_path = repo_root / scope.state_path()
    write_state(state, state_path)
    print(
        json.dumps(
            {
                "state_path": str(state_path),
                "score": score,
                "intro_first_sentence": intro.split(".", 1)[0],
            }
        )
    )
    return 0


def cmd_write_approval(args: argparse.Namespace) -> int:
    repo_root = Path(args.repo).resolve()
    scope = _scope_from_args(args)
    prior = _existing_state(repo_root, scope)
    if prior is None or prior.status != "reviewed":
        found = prior.status if prior else "absent"
        print(
            f"error: scope must be in 'reviewed' status, found {found}",
            file=sys.stderr,
        )
        return 2

    state = State(
        schema_version=prior.schema_version,
        scope=scope,
        status="approved",
        nonce=mint_nonce(),
        draft=prior.draft,
        review=prior.review,
        approval=ApprovalBlock(approved_at=now_iso(), approved_by=args.approver),
        is_foundation=prior.is_foundation,
        edges=prior.edges,
        meta=prior.meta,
    )
    state_path = repo_root / scope.state_path()
    write_state(state, state_path)
    print(json.dumps({"state_path": str(state_path), "approved_by": args.approver}))
    return 0


def cmd_repair_drift(args: argparse.Namespace) -> int:
    repo_root = Path(args.repo).resolve()
    scope = _scope_from_args(args)
    prior = _existing_state(repo_root, scope)
    if prior is None:
        print("error: no state to repair", file=sys.stderr)
        return 2

    changes: dict[str, dict[str, str]] = {}
    new_draft = prior.draft
    if prior.draft:
        body_abs = repo_root / prior.draft.body_path
        if body_abs.exists():
            actual = hashlib.sha256(body_abs.read_bytes()).hexdigest()
            if actual != prior.draft.body_sha256:
                changes["draft"] = {"old": prior.draft.body_sha256, "new": actual}
                new_draft = DraftBlock(
                    body_path=prior.draft.body_path,
                    body_sha256=actual,
                    generated_at=prior.draft.generated_at,
                    generator_metadata=prior.draft.generator_metadata,
                    prior_review_text=prior.draft.prior_review_text,
                )
    new_review = prior.review
    if prior.review:
        review_abs = repo_root / prior.review.body_path
        if review_abs.exists():
            actual = hashlib.sha256(review_abs.read_bytes()).hexdigest()
            if actual != prior.review.body_sha256:
                changes["review"] = {"old": prior.review.body_sha256, "new": actual}
                new_review = ReviewBlock(
                    body_path=prior.review.body_path,
                    body_sha256=actual,
                    reviewed_at=prior.review.reviewed_at,
                    score=prior.review.score,
                    reviewer_metadata=prior.review.reviewer_metadata,
                )

    # Re-derive the identity ledger for the decomposing tiers — it is
    # derived from the body, so a drifted body (or a ledger that
    # predates the format) leaves it stale. Idempotent: an unchanged
    # ledger rewrites byte-identically.
    ledger_rebuilt = False
    if scope.tier in DECOMPOSING_TIERS and new_draft is not None:
        body_abs = repo_root / new_draft.body_path
        if body_abs.exists():
            ids_path = repo_root / scope.ids_path()
            prior_manifest = load_manifest(ids_path) if ids_path.exists() else None
            manifest = derive_manifest(
                scope,
                body_abs.read_text(encoding="utf-8"),
                new_draft.body_sha256,
                prior_manifest,
            )
            write_manifest(ids_path, manifest)
            ledger_rebuilt = True

    if not changes:
        print(json.dumps({"changed": False, "ledger_rebuilt": ledger_rebuilt}))
        return 0

    state = State(
        schema_version=prior.schema_version,
        scope=scope,
        status=prior.status,
        nonce=mint_nonce(),
        draft=new_draft,
        review=new_review,
        approval=prior.approval,
        is_foundation=prior.is_foundation,
        edges=prior.edges,
        meta=prior.meta,
    )
    state_path = repo_root / scope.state_path()
    write_state(state, state_path)
    print(json.dumps({"changed": True, "deltas": changes, "ledger_rebuilt": ledger_rebuilt}))
    return 0


def cmd_mint_batch(args: argparse.Namespace) -> int:
    repo_root = Path(args.repo).resolve()
    batch_id = args.batch_id or f"batch_{mint_nonce()}"
    payload: dict[str, Any] = {
        "schema_version": 1,
        "batch_id": batch_id,
        "op_type": args.op_type,
        "tier": args.tier,
        "scopes": json.loads(args.scopes_json) if args.scopes_json else [],
        "status": "pending",
        "started_at": now_iso(),
    }
    if args.threshold is not None:
        payload["threshold"] = args.threshold
    path = repo_root / "state" / "batches" / f"{batch_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"batch_id": batch_id, "state_path": str(path)}))
    return 0


def cmd_mint_nonce(_args: argparse.Namespace) -> int:
    print(mint_nonce())
    return 0


def cmd_open_propagation(args: argparse.Namespace) -> int:
    """Materialize a fresh ``state/propagations/<id>.json``.

    The worklist is supplied as JSON because each entry is a
    ``(scope, status)`` pair and the scope itself has up to five
    fields — easier to round-trip through JSON than to flatten
    onto a wide CLI surface. The skill that calls this will
    typically compute the worklist via ``get-project-graph`` or
    ``get-review-summary`` and pass the result in.
    """
    from siege.propagation import (
        WorklistEntry,
        compute_downstream_worklist,
        compute_plan_change_worklist,
        new_propagation,
        write_propagation,
    )

    repo_root = Path(args.repo).resolve()
    source_scope = Scope(**json.loads(args.source_scope_json)) if args.source_scope_json else None

    explicit_worklist = args.worklist_json and args.worklist_json != "[]"
    mutex_count = sum(
        bool(x) for x in (args.from_source_scope_json, args.from_plan_change, explicit_worklist)
    )
    if mutex_count > 1:
        raise SystemExit(
            "--from-source-scope-json, --from-plan-change, and --worklist-json are mutually "
            "exclusive"
        )

    if args.from_source_scope_json:
        # Compute-and-open shortcut: skip the explicit worklist JSON,
        # the source-of-truth is the source scope itself. The walk
        # emits one entry per existing downstream scope.
        from siege.git_view import local_view  # noqa: PLC0415 — keep lazy

        view = local_view(repo_root, "HEAD")
        compute_source = Scope(**json.loads(args.from_source_scope_json))
        entries = compute_downstream_worklist(view, compute_source)
        if source_scope is None:
            source_scope = compute_source
    elif args.from_plan_change:
        # Plan-change shortcut: diff the live plan projection against
        # existing impl state files; emit one entry per impl whose
        # closure_resp_ids changed (status=pending), plus impls the
        # current plan no longer covers (status=skipped, note="dropped
        # by plan"). Cold-start impls (planned but no state file yet)
        # are not emitted — those are /run_tier work, not regen work.
        from siege.git_view import local_view  # noqa: PLC0415 — keep lazy

        view = local_view(repo_root, "HEAD")
        entries = compute_plan_change_worklist(view)
    else:
        raw_entries = json.loads(args.worklist_json) if args.worklist_json else []
        entries = [
            WorklistEntry(
                scope=Scope(**e["scope"]),
                status=str(e.get("status", "pending")),
                note=e.get("note"),
            )
            for e in raw_entries
        ]
    meta = json.loads(args.meta_json) if args.meta_json else None
    prop = new_propagation(
        op_type=args.op_type,
        worklist=entries,
        tier=args.tier,
        threshold=args.threshold,
        source_scope=source_scope,
        meta=meta,
        propagation_id=args.propagation_id or None,
    )
    path = write_propagation(repo_root, prop)
    print(
        json.dumps(
            {
                "propagation_id": prop.propagation_id,
                "state_path": str(path),
                "status": prop.status,
                "counts": prop.counts,
            }
        )
    )
    return 0


def cmd_update_propagation_entry(args: argparse.Namespace) -> int:
    """Flip one worklist entry's status in an existing propagation.

    Reads the on-disk record, swaps the matching entry, rewrites.
    The skill calls this once per drained scope so progress is
    visible mid-batch (and resumable if the orchestrator dies).
    """
    from siege.propagation import (
        read_propagation,
        update_entry,
        write_propagation,
    )

    repo_root = Path(args.repo).resolve()
    scope = Scope(**json.loads(args.scope_json))
    prop = read_propagation(repo_root, args.propagation_id)
    updated = update_entry(prop, scope, status=args.status, note=args.note)
    write_propagation(repo_root, updated)
    print(
        json.dumps(
            {
                "propagation_id": updated.propagation_id,
                "status": updated.status,
                "counts": updated.counts,
            }
        )
    )
    return 0


def cmd_compute_downstream(args: argparse.Namespace) -> int:
    """Walk the tier chain top-down from a source scope and print the
    worklist (one entry per existing downstream scope).

    Standalone read — useful for previewing what an ``open-propagation
    --from-source-scope-json`` would emit before actually writing the
    record. Skills can also pipe this into a separate processing step
    if they want to filter / modify the worklist before opening.
    """
    from dataclasses import asdict  # noqa: PLC0415 — keep lazy

    from siege.propagation import compute_downstream_worklist

    view = _open_local_view(args)
    source = Scope(**json.loads(args.source_scope_json))
    entries = compute_downstream_worklist(view, source)
    out = {
        "ref": view.ref,
        "ref_head_sha": view.head_sha,
        "source_scope": asdict(source),
        "worklist": [{"scope": asdict(e.scope), "status": e.status} for e in entries],
    }
    print(json.dumps(out, indent=2))
    return 0


def cmd_list_propagations(args: argparse.Namespace) -> int:
    """Enumerate ``state/propagations/<id>.json`` files."""
    from siege.propagation import dump_propagation, load_propagation

    view = _open_local_view(args)
    out: list[dict[str, Any]] = []
    for path in view.clone.ls_tree(view.head_sha, "state/propagations/"):
        if not path.endswith(".json"):
            continue
        try:
            data = json.loads(view.clone.show_blob(view.head_sha, path).decode("utf-8"))
            prop = load_propagation(data)
        except Exception:  # noqa: BLE001 — skip malformed
            continue
        if args.status and prop.status != args.status:
            continue
        out.append(dump_propagation(prop))
    print(
        json.dumps(
            {"ref": view.ref, "ref_head_sha": view.head_sha, "propagations": out},
            indent=2,
        )
    )
    return 0


def _resync_drafted_state(repo_root: Path, scope: Scope, body_bytes: bytes) -> dict[str, Any]:
    """Flip a scope back to ``drafted`` against the body bytes on disk.

    Shared between ``mark-drafted`` (body was hand-edited out of band)
    and the ``add-*`` / ``remove-*`` substrate-edit commands (body was
    just mutated by this same CLI call). Both paths produce the same
    result: new body sha, fresh ``generated_at`` + nonce, status back
    to ``drafted``, ``review`` / ``approval`` cleared, and — for the
    decomposing tiers — the identity ledger re-derived from the
    current body so add/remove ops surface immediately.

    Requires an existing scope with a prior ``draft`` block; the
    caller validates that. Returns the JSON-ready summary dict the
    callers print on stdout.
    """
    prior = _existing_state(repo_root, scope)
    assert prior is not None and prior.draft is not None
    body_sha = hashlib.sha256(body_bytes).hexdigest()
    state = State(
        schema_version=prior.schema_version,
        scope=scope,
        status="drafted",
        nonce=mint_nonce(),
        draft=DraftBlock(
            body_path=prior.draft.body_path,
            body_sha256=body_sha,
            generated_at=now_iso(),
            generator_metadata=prior.draft.generator_metadata,
            prior_review_text=prior.draft.prior_review_text,
        ),
        is_foundation=prior.is_foundation,
        edges=prior.edges,
        meta=prior.meta,
    )
    state_path = repo_root / scope.state_path()
    write_state(state, state_path)

    out: dict[str, Any] = {"state_path": str(state_path), "body_sha256": body_sha}
    if scope.tier in DECOMPOSING_TIERS:
        ids_path = repo_root / scope.ids_path()
        prior_manifest = load_manifest(ids_path) if ids_path.exists() else None
        manifest = derive_manifest(scope, body_bytes.decode("utf-8"), body_sha, prior_manifest)
        write_manifest(ids_path, manifest)
        out["ids_path"] = str(ids_path)
        out["node_count"] = len(manifest.nodes)
    return out


def cmd_mark_drafted(args: argparse.Namespace) -> int:
    repo_root = Path(args.repo).resolve()
    scope = _scope_from_args(args)
    prior = _existing_state(repo_root, scope)
    if prior is None or prior.draft is None:
        print("error: mark-drafted needs an existing scope with a draft", file=sys.stderr)
        return 2
    body_abs = repo_root / prior.draft.body_path
    if not body_abs.exists():
        print(f"error: body file does not exist: {body_abs}", file=sys.stderr)
        return 2
    out = _resync_drafted_state(repo_root, scope, body_abs.read_bytes())
    print(json.dumps(out))
    return 0


# ---------------- substrate-edit subcommands ----------------
#
# Mechanical add/remove operations against a feature_expansion or
# requirements body. The CLI does the surgery + ledger resync; the
# calling skill handles the LLM-free framing and the git commit. No
# auto-propagation — the user invokes ``/propagate_downstream`` after
# batching whatever edits they want.

# Per-tier block grammar — what wraps the list, what each child is, and
# the inner ``<name>`` carry-forward key. Both decomposing-root tiers
# (feature_expansion / requirements) use this shape; sysarch / comparch
# have richer block grammars and aren't supported by the mechanical
# editors (use the ``modify-*`` skills instead).
_BLOCK_GRAMMAR: dict[str, dict[str, str]] = {
    "feature_expansion": {
        "wrapper": "features",
        "child": "feature",
        "id_prefix": "feat_",
    },
    "requirements": {
        "wrapper": "requirements",
        "child": "responsibility",
        "id_prefix": "resp_",
    },
}


def _substrate_root_scope(repo_root: Path, tier: str, comp_id: str) -> Scope:
    scope = Scope(tier=tier, comp_id=comp_id)  # type: ignore[arg-type]
    if _existing_state(repo_root, scope) is None:
        raise SystemExit(
            f"error: no existing {tier} draft at {scope.state_path()} — "
            f"seed one via /draft_{tier} first"
        )
    return scope


def _read_body_for(repo_root: Path, scope: Scope) -> tuple[Path, str]:
    """Return (body_abs_path, body_text) for an existing drafted scope."""
    state = _existing_state(repo_root, scope)
    if state is None or state.draft is None:
        raise SystemExit(f"error: scope {scope.key()} has no draft block")
    body_abs = repo_root / state.draft.body_path
    if not body_abs.exists():
        raise SystemExit(f"error: body file does not exist: {body_abs}")
    return body_abs, body_abs.read_text(encoding="utf-8")


def _find_blocks_with_name(body: str, child_tag: str, name: str) -> list[re.Match[str]]:
    """Return the ``<child_tag>...</child_tag>`` blocks whose inner
    ``<name>`` matches ``name`` (case-insensitive, trimmed).

    The match uses the same regex shape ``derive_manifest`` uses so the
    ledger's "found a node by name" agrees with the editor's "found a
    block by name" — important when ``derive_manifest`` collapsed two
    blocks with the same name into one ledger entry.
    """
    block_re = re.compile(rf"<{child_tag}\b[^>]*>(.*?)</{child_tag}>", re.S)
    target = name.strip().lower()
    out: list[re.Match[str]] = []
    name_re = re.compile(r"<name\b[^>]*>(.*?)</name>", re.S)
    for m in block_re.finditer(body):
        inner_name_m = name_re.search(m.group(1))
        if inner_name_m and inner_name_m.group(1).strip().lower() == target:
            out.append(m)
    return out


def _resolve_target_name(
    repo_root: Path,
    scope: Scope,
    *,
    target_id: str | None,
    target_name: str | None,
) -> str:
    """Resolve a removal target to the body-text ``<name>`` to match.

    With ``--name``, returns the input directly (preserving the user's
    case). With ``--feat-id`` / ``--resp-id``, looks up the existing
    ledger and returns the node's stored name. Errors out on
    unresolved id or missing ledger.
    """
    if target_name is not None and target_id is not None:
        raise SystemExit("error: pass --feat-id/--resp-id OR --name, not both")
    if target_name is not None:
        return target_name
    if target_id is None:
        raise SystemExit("error: must pass --feat-id/--resp-id or --name")
    ids_path = repo_root / scope.ids_path()
    if not ids_path.exists():
        raise SystemExit(f"error: no ledger at {ids_path}; cannot resolve {target_id!r} by id")
    manifest = load_manifest(ids_path)
    for n in manifest.nodes:
        if str(n.get("id", "")) == target_id:
            name = str(n.get("name", "")).strip()
            if not name:
                raise SystemExit(f"error: ledger node {target_id!r} has no name")
            return name
    raise SystemExit(f"error: id {target_id!r} not found in {ids_path}")


def _insert_child_before_close(body: str, wrapper: str, child_line: str) -> str:
    """Insert ``child_line`` (already terminated with ``\\n``) immediately
    before the ``</wrapper>`` closing tag, preserving the closing tag's
    own leading indentation."""
    close = f"</{wrapper}>"
    m = re.search(rf"(^|\n)([ \t]*){re.escape(close)}", body)
    if not m:
        raise SystemExit(f"error: body has no <{wrapper}> closing tag")
    insert_pos = m.start(2)
    return body[:insert_pos] + child_line + body[insert_pos:]


def _remove_block_with_padding(body: str, m: re.Match[str]) -> str:
    """Drop the matched block plus its leading line indentation and one
    trailing newline, so the surrounding body keeps its line shape."""
    start, end = m.start(), m.end()
    line_start = body.rfind("\n", 0, start) + 1
    if body[line_start:start].strip() == "":
        start = line_start
    if end < len(body) and body[end] == "\n":
        end += 1
    return body[:start] + body[end:]


def cmd_add_feature(args: argparse.Namespace) -> int:
    repo_root = Path(args.repo).resolve()
    scope = _substrate_root_scope(repo_root, "feature_expansion", args.comp_id)
    body_abs, body = _read_body_for(repo_root, scope)
    if _find_blocks_with_name(body, "feature", args.name):
        print(f"error: a <feature> with <name>{args.name}</name> already exists", file=sys.stderr)
        return 2
    implicit = "<implicit/>" if args.implicit else ""
    child = (
        f"  <feature><name>{args.name}</name><intent>{args.intent}</intent>{implicit}</feature>\n"
    )
    new_body = _insert_child_before_close(body, "features", child)
    body_bytes = new_body.encode("utf-8")
    body_abs.write_bytes(body_bytes)
    out = _resync_drafted_state(repo_root, scope, body_bytes)
    # Surface the minted feat_* id so the calling skill can echo it.
    ids = load_manifest(repo_root / scope.ids_path())
    target_lc = args.name.strip().lower()
    target = next(
        (n for n in ids.nodes if str(n.get("name", "")).strip().lower() == target_lc),
        None,
    )
    out["action"] = "add-feature"
    out["feat_id"] = str(target.get("id", "")) if target else ""
    out["name"] = args.name
    print(json.dumps(out))
    return 0


def cmd_remove_feature(args: argparse.Namespace) -> int:
    repo_root = Path(args.repo).resolve()
    scope = _substrate_root_scope(repo_root, "feature_expansion", args.comp_id)
    body_abs, body = _read_body_for(repo_root, scope)
    name = _resolve_target_name(repo_root, scope, target_id=args.feat_id, target_name=args.name)
    matches = _find_blocks_with_name(body, "feature", name)
    if not matches:
        print(f"error: no <feature> with <name>{name}</name> in body", file=sys.stderr)
        return 2
    if len(matches) > 1:
        print(
            f"error: {len(matches)} <feature> blocks match <name>{name}</name>; "
            f"ambiguous — refusing to remove",
            file=sys.stderr,
        )
        return 2
    new_body = _remove_block_with_padding(body, matches[0])
    body_bytes = new_body.encode("utf-8")
    body_abs.write_bytes(body_bytes)
    out = _resync_drafted_state(repo_root, scope, body_bytes)
    out["action"] = "remove-feature"
    out["removed_name"] = name
    print(json.dumps(out))
    return 0


def cmd_add_responsibility(args: argparse.Namespace) -> int:
    repo_root = Path(args.repo).resolve()
    scope = _substrate_root_scope(repo_root, "requirements", args.comp_id)
    body_abs, body = _read_body_for(repo_root, scope)
    if _find_blocks_with_name(body, "responsibility", args.name):
        print(
            f"error: a <responsibility> with <name>{args.name}</name> already exists",
            file=sys.stderr,
        )
        return 2

    # Validate feat-ids against the feature_expansion ledger. An empty
    # feat list is permitted — some resps trace to no specific feature
    # (owned platform work). A non-empty list with an unknown id is a
    # hard error so the body never carries dangling references.
    feat_ids = [f.strip() for f in (args.feat_ids or "").split(",") if f.strip()]
    if feat_ids:
        fe_scope = Scope(tier="feature_expansion", comp_id=args.comp_id)
        fe_ids = repo_root / fe_scope.ids_path()
        if not fe_ids.exists():
            print(
                f"error: feature_expansion ledger missing at {fe_ids}; cannot validate --feat-ids",
                file=sys.stderr,
            )
            return 2
        known = {str(n.get("id", "")) for n in load_manifest(fe_ids).nodes}
        unknown = [fid for fid in feat_ids if fid not in known]
        if unknown:
            print(f"error: unknown feat_ids: {unknown}", file=sys.stderr)
            return 2

    feats_xml = "".join(f'<feat id="{fid}"/>' for fid in feat_ids)
    child = (
        f"  <responsibility><name>{args.name}</name><feats>{feats_xml}</feats></responsibility>\n"
    )
    new_body = _insert_child_before_close(body, "requirements", child)
    body_bytes = new_body.encode("utf-8")
    body_abs.write_bytes(body_bytes)
    out = _resync_drafted_state(repo_root, scope, body_bytes)
    ids = load_manifest(repo_root / scope.ids_path())
    target_lc = args.name.strip().lower()
    target = next(
        (n for n in ids.nodes if str(n.get("name", "")).strip().lower() == target_lc),
        None,
    )
    out["action"] = "add-responsibility"
    out["resp_id"] = str(target.get("id", "")) if target else ""
    out["name"] = args.name
    out["feat_ids"] = feat_ids
    print(json.dumps(out))
    return 0


def cmd_remove_responsibility(args: argparse.Namespace) -> int:
    repo_root = Path(args.repo).resolve()
    scope = _substrate_root_scope(repo_root, "requirements", args.comp_id)
    body_abs, body = _read_body_for(repo_root, scope)
    name = _resolve_target_name(repo_root, scope, target_id=args.resp_id, target_name=args.name)
    matches = _find_blocks_with_name(body, "responsibility", name)
    if not matches:
        print(f"error: no <responsibility> with <name>{name}</name> in body", file=sys.stderr)
        return 2
    if len(matches) > 1:
        print(
            f"error: {len(matches)} <responsibility> blocks match <name>{name}</name>; "
            f"ambiguous — refusing to remove",
            file=sys.stderr,
        )
        return 2
    new_body = _remove_block_with_padding(body, matches[0])
    body_bytes = new_body.encode("utf-8")
    body_abs.write_bytes(body_bytes)
    out = _resync_drafted_state(repo_root, scope, body_bytes)
    out["action"] = "remove-responsibility"
    out["removed_name"] = name
    print(json.dumps(out))
    return 0


# ---------------- phase registry subcommands ----------------
#
# The phase registry lives at ``state/phases/<phase_id>.json`` and feeds
# ``compute_plan`` (siege/projection/plan.py). Each file is
# ``{schema_version, phase_id, order, name, feature_ids}``. The four
# editor subcommands keep the registry round-trippable without forcing
# the user to hand-edit JSON files.

_PHASE_SCHEMA_VERSION = 2


def _phase_path(repo_root: Path, phase_id: str) -> Path:
    return repo_root / "state" / "phases" / f"{phase_id}.json"


def _load_phase(repo_root: Path, phase_id: str) -> dict[str, Any]:
    path = _phase_path(repo_root, phase_id)
    if not path.exists():
        raise SystemExit(f"error: no phase at {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _write_phase(repo_root: Path, phase: dict[str, Any]) -> Path:
    path = _phase_path(repo_root, phase["phase_id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(phase, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def cmd_add_phase(args: argparse.Namespace) -> int:
    repo_root = Path(args.repo).resolve()
    phase_id = args.phase_id or f"phase_{mint_nonce()}"
    if _phase_path(repo_root, phase_id).exists():
        print(f"error: phase {phase_id} already exists", file=sys.stderr)
        return 2
    # Refuse to mint two phases at the same order — the plan projection
    # sorts by order and ties are silently undefined.
    phases_dir = repo_root / "state" / "phases"
    existing_phases = sorted(phases_dir.glob("*.json")) if phases_dir.exists() else []
    for path in existing_phases:
        existing = json.loads(path.read_text(encoding="utf-8"))
        if existing.get("order") == args.order:
            print(
                f"error: phase order {args.order} already taken by {existing.get('phase_id')}",
                file=sys.stderr,
            )
            return 2
    phase = {
        "schema_version": _PHASE_SCHEMA_VERSION,
        "phase_id": phase_id,
        "order": args.order,
        "name": args.name,
        "feature_ids": [],
    }
    path = _write_phase(repo_root, phase)
    print(json.dumps({"action": "add-phase", "phase_id": phase_id, "state_path": str(path)}))
    return 0


def cmd_remove_phase(args: argparse.Namespace) -> int:
    repo_root = Path(args.repo).resolve()
    phase = _load_phase(repo_root, args.phase_id)
    feat_ids = phase.get("feature_ids", [])
    if feat_ids:
        print(
            f"error: phase {args.phase_id} still owns features {feat_ids}; "
            f"unassign first or pass --force",
            file=sys.stderr,
        )
        return 2
    _phase_path(repo_root, args.phase_id).unlink()
    print(json.dumps({"action": "remove-phase", "phase_id": args.phase_id}))
    return 0


def cmd_assign_feature_to_phase(args: argparse.Namespace) -> int:
    repo_root = Path(args.repo).resolve()
    target = _load_phase(repo_root, args.phase_id)
    if args.feat_id in target.get("feature_ids", []):
        print(json.dumps({"action": "noop", "reason": "feature already assigned to this phase"}))
        return 0
    # A feature lives in at most one phase — strip it from any other
    # phase before adding it here. Keeps ``compute_plan``'s
    # feature→phase map a clean function.
    phases_dir = repo_root / "state" / "phases"
    moved_from: str | None = None
    if phases_dir.exists():
        for path in sorted(phases_dir.glob("*.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            if data["phase_id"] == args.phase_id:
                continue
            if args.feat_id in data.get("feature_ids", []):
                moved_from = data["phase_id"]
                data["feature_ids"] = [f for f in data["feature_ids"] if f != args.feat_id]
                _write_phase(repo_root, data)
    target.setdefault("feature_ids", []).append(args.feat_id)
    _write_phase(repo_root, target)
    print(
        json.dumps(
            {
                "action": "assign-feature-to-phase",
                "feat_id": args.feat_id,
                "phase_id": args.phase_id,
                "moved_from": moved_from,
            }
        )
    )
    return 0


def cmd_unassign_feature_from_phase(args: argparse.Namespace) -> int:
    repo_root = Path(args.repo).resolve()
    phase = _load_phase(repo_root, args.phase_id)
    if args.feat_id not in phase.get("feature_ids", []):
        print(
            f"error: feature {args.feat_id} not assigned to {args.phase_id}",
            file=sys.stderr,
        )
        return 2
    phase["feature_ids"] = [f for f in phase["feature_ids"] if f != args.feat_id]
    _write_phase(repo_root, phase)
    print(
        json.dumps(
            {
                "action": "unassign-feature-from-phase",
                "feat_id": args.feat_id,
                "phase_id": args.phase_id,
            }
        )
    )
    return 0


def cmd_mint_plan(args: argparse.Namespace) -> int:
    repo_root = Path(args.repo).resolve()
    plan_path = repo_root / "state" / "plan.json"
    if not plan_path.exists():
        print(f"error: no plan at {plan_path}", file=sys.stderr)
        return 2
    plan = json.loads(plan_path.read_text(encoding="utf-8"))

    minted: list[str] = []
    reseeded: list[str] = []
    skipped: list[str] = []
    planned: set[str] = set()
    for phase in plan.get("phases", []):
        for node in phase.get("impl_nodes", []):
            scope = Scope(
                tier="impl",
                parent_id=node["parent_id"],
                sub_id=node["sub_id"],
                phase=node["phase"],
            )
            rel = scope.state_path()
            planned.add(rel)
            prior = _existing_state(repo_root, scope)
            # Idempotent + additive: never disturb an already-built node.
            if prior is not None and prior.status in ("drafted", "reviewed", "approved"):
                skipped.append(rel)
                continue
            if args.dry_run:
                (reseeded if prior else minted).append(rel)
                continue
            meta = dict(prior.meta) if prior else {}
            meta["parent_resps"] = node["closure_resp_ids"]
            stub = State(
                schema_version=2,
                scope=scope,
                status="absent",
                nonce=mint_nonce(),
                is_foundation=prior.is_foundation if prior else False,
                edges=dict(prior.edges) if prior else {},
                meta=meta,
            )
            write_state(stub, repo_root / rel)
            (reseeded if prior else minted).append(rel)

    # Surface — never delete — phased impl nodes the new plan dropped.
    dropped: list[str] = []
    impl_root = repo_root / "state" / "impl"
    if impl_root.exists():
        for p in sorted(impl_root.rglob("*.json")):
            seg = p.parent.name
            if seg.startswith("p") and seg[1:].isdigit():
                rel = str(p.relative_to(repo_root))
                if rel not in planned:
                    dropped.append(rel)
    out: dict[str, Any] = {
        "minted": minted,
        "reseeded": reseeded,
        "skipped_built": skipped,
        "dropped_by_plan": dropped,
    }
    if args.dry_run:
        out["dry_run"] = True
    print(json.dumps(out, indent=2))
    return 0


def _rehydrate_ledger(repo_root: Path, ids_path: Path) -> Manifest:
    """Load a slim identity ledger and re-derive its full node records
    from the substrate body — the working-tree analogue of the
    projection's rehydration. Falls back to the slim ledger when the
    body can't be read.
    """
    slim = load_manifest(ids_path)
    body_abs = repo_root / slim.substrate.body_path()
    if not body_abs.exists():
        return slim
    body_bytes = body_abs.read_bytes()
    body_sha = hashlib.sha256(body_bytes).hexdigest()
    return derive_manifest(slim.substrate, body_bytes.decode("utf-8"), body_sha, slim)


def cmd_list_scopes(args: argparse.Namespace) -> int:
    repo_root = Path(args.repo).resolve()
    tier = args.tier
    # comparch scopes come from the sysarch ledger; subcomparch scopes
    # from every comparch ledger.
    source_dir = repo_root / "ids" / ("sysarch" if tier == "comparch" else "comparch")

    scopes: list[dict[str, Any]] = []
    if source_dir.exists():
        for ids_path in sorted(source_dir.glob("*.json")):
            manifest = _rehydrate_ledger(repo_root, ids_path)
            for n in manifest.nodes:
                if tier == "comparch":
                    scope = Scope(tier="comparch", comp_id=n["id"])
                    entry: dict[str, Any] = {"comp_id": n["id"]}
                else:
                    scope = Scope(
                        tier="subcomparch",
                        parent_id=manifest.substrate.comp_id,
                        sub_id=n["id"],
                    )
                    entry = {"parent_id": manifest.substrate.comp_id, "sub_id": n["id"]}
                prior = _existing_state(repo_root, scope)
                entry.update(
                    {
                        "alias": n.get("alias", ""),
                        "is_foundation": bool(n.get("is_foundation", False)),
                        "order": n.get("order", 0),
                        "status": prior.status if prior else "absent",
                    }
                )
                scopes.append(entry)

    # Foundation first, then declaration order — the topological order a
    # `/run_tier` fan-out drafts in.
    scopes.sort(key=lambda s: (not s["is_foundation"], s["order"]))
    print(json.dumps({"tier": tier, "scopes": scopes}, indent=2))
    return 0


# ---------------- read subcommands (projection) ----------------
#
# These wrap the read-side projection (``siege.projection``) and so
# pull its dependency closure (pydantic, bs4, …). The imports are
# deferred into each function body so ``import siege.cli`` itself stays
# pure-stdlib — a core-only install keeps running the write subcommands;
# the read subcommands need the ``[read]`` extra.


def _open_local_view(args: argparse.Namespace) -> GitView:
    """Build a GitView over the local repo at ``--ref`` (default HEAD)."""
    from siege.git_view import local_view

    return local_view(Path(args.repo).resolve(), args.ref)


def cmd_get_state(args: argparse.Namespace) -> int:
    view = _open_local_view(args)
    scope = _scope_from_args(args)
    base = {"ref": view.ref, "ref_head_sha": view.head_sha}
    state = view.get_state(scope)
    if state is None:
        print(
            json.dumps(
                {
                    **base,
                    "found": False,
                    "scope": {
                        "tier": scope.tier,
                        "comp_id": scope.comp_id,
                        "parent_id": scope.parent_id,
                        "sub_id": scope.sub_id,
                        "phase": scope.phase,
                    },
                },
                indent=2,
            )
        )
        return 0
    payload: dict[str, Any] = {**base, "found": True, **dump_state(state)}
    drift = view.drift_for(state)
    if drift:
        payload["drift"] = drift
    print(json.dumps(payload, indent=2))
    return 0


def cmd_get_context(args: argparse.Namespace) -> int:
    from siege.projection import GENERATION_BUILDERS
    from siege.prompts import load_generation_prompt

    view = _open_local_view(args)
    builder = GENERATION_BUILDERS.get(args.tier)
    if builder is None:
        print(f"error: no generation context builder for tier {args.tier!r}", file=sys.stderr)
        return 2
    bundle = builder(view, _scope_from_args(args))
    # ``--prompt-variant modify`` swaps the bundle's ``instructions`` field
    # for the surgical-edit prompt (``siege/prompts/modify_<tier>.md``).
    # The per-tier context bundle is identical to the regen path — only
    # the framing changes. Fall back silently to the default prompt for
    # tiers without a modify variant.
    if args.prompt_variant == "modify":
        modify_text = load_generation_prompt(f"modify_{args.tier}")
        if modify_text:
            bundle["instructions"] = modify_text
            bundle["prompt_variant"] = "modify"
    print(json.dumps(bundle, indent=2))
    return 0


def cmd_get_review_context(args: argparse.Namespace) -> int:
    from siege.projection import REVIEW_BUILDERS

    view = _open_local_view(args)
    builder = REVIEW_BUILDERS.get(args.tier)
    if builder is None:
        print(f"error: no review context builder for tier {args.tier!r}", file=sys.stderr)
        return 2
    print(json.dumps(builder(view, _scope_from_args(args), args.draft_sha), indent=2))
    return 0


def cmd_compute_plan(args: argparse.Namespace) -> int:
    from siege.projection.plan import compute_plan

    view = _open_local_view(args)
    print(json.dumps(compute_plan(view), indent=2))
    return 0


def cmd_get_structure_summary(args: argparse.Namespace) -> int:
    from siege.projection.structure import build_structure_summary

    view = _open_local_view(args)
    print(json.dumps(build_structure_summary(view, args.tier), indent=2))
    return 0


def cmd_get_project_graph(args: argparse.Namespace) -> int:
    from siege.projection.graph import build_project_graph

    view = _open_local_view(args)
    print(json.dumps(build_project_graph(view), indent=2))
    return 0


def cmd_get_review_summary(args: argparse.Namespace) -> int:
    from siege.projection.review_summary import build_review_summary

    view = _open_local_view(args)
    print(json.dumps(build_review_summary(view, args.tier), indent=2))
    return 0


def cmd_list_batches(args: argparse.Namespace) -> int:
    view = _open_local_view(args)
    batches: list[dict[str, Any]] = []
    for path in view.clone.ls_tree(view.head_sha, "state/batches/"):
        if not path.endswith(".json"):
            continue
        try:
            data = json.loads(view.clone.show_blob(view.head_sha, path).decode("utf-8"))
        except Exception:  # noqa: BLE001 — skip malformed
            continue
        if args.status and data.get("status") != args.status:
            continue
        batches.append(data)
    print(
        json.dumps({"ref": view.ref, "ref_head_sha": view.head_sha, "batches": batches}, indent=2)
    )
    return 0


def _add_scope_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--repo", default=".", help="repo root (default: cwd)")
    parser.add_argument("--tier", required=True, choices=ALL_TIERS)
    parser.add_argument("--comp-id", dest="comp_id", default=None)
    parser.add_argument("--parent-id", dest="parent_id", default=None)
    parser.add_argument("--sub-id", dest="sub_id", default=None)
    parser.add_argument(
        "--phase",
        type=int,
        default=None,
        help="phase index for a phased impl/fanin scope (omit for arch tiers)",
    )


def _add_ref_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--ref", default="HEAD", help="git ref to read (default: HEAD)")


def cmd_add_input_doc(args: argparse.Namespace) -> int:
    """Write an input document into the project repo and register it.

    Reads the content from ``--content-file``, writes it to the
    bundle-declared path for the given role (default
    ``inputs/<role>.md``), commits with a deterministic message,
    optionally pushes, then POSTs the new (body_sha, body_path) to
    the backend so the input_documents projection updates.

    Prints a single JSON line with the registered doc's id +
    body_sha so the caller can pipe.
    """
    from siege import backend_client
    from siege.git_view import run_git

    repo_root = Path(args.repo).resolve()
    content_file = Path(args.content_file).resolve()
    if not content_file.is_file():
        print(f"error: content file does not exist: {content_file}", file=sys.stderr)
        return 2

    content = content_file.read_bytes()
    role = args.role.strip()
    if not role:
        print("error: --role cannot be empty", file=sys.stderr)
        return 2

    body_path = args.body_path or f"inputs/{role}.md"
    target = repo_root / body_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)

    # Stage + commit. Push only if --no-push wasn't set.
    run_git(["add", body_path], cwd=repo_root)
    run_git(
        ["commit", "-m", f"inputs: add {role} ({args.name})"],
        cwd=repo_root,
    )
    body_sha = run_git(["rev-parse", "HEAD"], cwd=repo_root).strip()
    if not args.no_push:
        try:
            run_git(["push"], cwd=repo_root)
        except Exception as exc:  # noqa: BLE001
            print(
                f"warning: git push failed ({exc}); backend will not see "
                "the body until the branch is pushed",
                file=sys.stderr,
            )

    try:
        doc = backend_client.create_input_document(
            project_id=args.project_id,
            role=role,
            name=args.name,
            body_sha=body_sha,
            body_path=body_path,
        )
    except backend_client.BackendError as exc:
        print(f"error: backend registration failed: {exc}", file=sys.stderr)
        return 3

    print(
        json.dumps(
            {
                "action": "add-input-doc",
                "id": doc.get("id"),
                "role": doc.get("doc_type"),
                "name": doc.get("name"),
                "body_sha": doc.get("body_sha"),
                "body_path": doc.get("body_path"),
            }
        )
    )
    return 0


def cmd_list_input_docs(args: argparse.Namespace) -> int:
    """List a project's input documents via the backend."""
    from siege import backend_client

    try:
        docs = backend_client.list_input_documents(args.project_id)
    except backend_client.BackendError as exc:
        print(f"error: backend list failed: {exc}", file=sys.stderr)
        return 3
    print(json.dumps({"input_documents": docs}))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="siege.cli")
    subs = p.add_subparsers(dest="cmd", required=True)

    p_draft = subs.add_parser("write-draft", help="materialize state JSON for a drafted scope")
    _add_scope_args(p_draft)
    p_draft.add_argument("--body-path", dest="body_path", required=True)
    p_draft.add_argument("--thinking-effort", dest="thinking_effort", default=None)
    p_draft.add_argument("--batch-id", dest="batch_id", default=None)
    p_draft.add_argument("--prior-review-text", dest="prior_review_text", default=None)
    p_draft.add_argument("--is-foundation", dest="is_foundation", action="store_true")
    p_draft.set_defaults(func=cmd_write_draft)

    p_rev = subs.add_parser("write-review", help="materialize state JSON for a reviewed scope")
    _add_scope_args(p_rev)
    p_rev.add_argument("--review-path", dest="review_path", required=True)
    p_rev.set_defaults(func=cmd_write_review)

    p_app = subs.add_parser("write-approval", help="flip reviewed → approved")
    _add_scope_args(p_app)
    p_app.add_argument("--approver", required=True)
    p_app.set_defaults(func=cmd_write_approval)

    p_repair = subs.add_parser("repair-drift", help="recompute body_sha256 fields")
    _add_scope_args(p_repair)
    p_repair.set_defaults(func=cmd_repair_drift)

    p_batch = subs.add_parser("mint-batch", help="create a batch state file")
    p_batch.add_argument("--repo", default=".")
    p_batch.add_argument("--op-type", dest="op_type", required=True)
    p_batch.add_argument("--tier", required=True, choices=ALL_TIERS)
    p_batch.add_argument("--scopes-json", dest="scopes_json", default="[]")
    p_batch.add_argument("--threshold", type=int, default=None)
    p_batch.add_argument("--batch-id", dest="batch_id", default=None)
    p_batch.set_defaults(func=cmd_mint_batch)

    p_nonce = subs.add_parser("mint-nonce", help="emit a fresh nonce")
    p_nonce.set_defaults(func=cmd_mint_nonce)

    p_md = subs.add_parser("mark-drafted", help="re-sync state to a hand-edited body")
    _add_scope_args(p_md)
    p_md.set_defaults(func=cmd_mark_drafted)

    # ---- substrate-edit subcommands (mechanical add/remove) ----

    def _add_substrate_root_args(parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--repo", default=".")
        parser.add_argument(
            "--comp-id",
            dest="comp_id",
            default="proj",
            help="substrate-root comp_id (the single substrate-root scope; "
            "the sample-project convention is 'proj')",
        )

    p_af = subs.add_parser(
        "add-feature",
        help="append a <feature> block to feature_expansion/<comp_id>/body.md",
    )
    _add_substrate_root_args(p_af)
    p_af.add_argument("--name", required=True, help="user-facing feature name")
    p_af.add_argument("--intent", required=True, help="one-sentence intent")
    p_af.add_argument(
        "--implicit",
        action="store_true",
        help="mark the feature as implicit (downstream tiers treat it as background)",
    )
    p_af.set_defaults(func=cmd_add_feature)

    p_rf = subs.add_parser(
        "remove-feature",
        help="delete a <feature> block from feature_expansion/<comp_id>/body.md",
    )
    _add_substrate_root_args(p_rf)
    p_rf.add_argument("--feat-id", dest="feat_id", default=None, help="resolve via ledger")
    p_rf.add_argument("--name", default=None, help="match the <name> in the body directly")
    p_rf.set_defaults(func=cmd_remove_feature)

    p_ar = subs.add_parser(
        "add-responsibility",
        help="append a <responsibility> block to requirements/<comp_id>/body.md",
    )
    _add_substrate_root_args(p_ar)
    p_ar.add_argument("--name", required=True)
    p_ar.add_argument(
        "--feat-ids",
        dest="feat_ids",
        default="",
        help="comma-separated feat_* ids this resp serves (validated against the ledger)",
    )
    p_ar.set_defaults(func=cmd_add_responsibility)

    p_rr = subs.add_parser(
        "remove-responsibility",
        help="delete a <responsibility> block from requirements/<comp_id>/body.md",
    )
    _add_substrate_root_args(p_rr)
    p_rr.add_argument("--resp-id", dest="resp_id", default=None, help="resolve via ledger")
    p_rr.add_argument("--name", default=None, help="match the <name> in the body directly")
    p_rr.set_defaults(func=cmd_remove_responsibility)

    # ---- phase registry subcommands ----

    p_apz = subs.add_parser("add-phase", help="create a state/phases/<id>.json file")
    p_apz.add_argument("--repo", default=".")
    p_apz.add_argument("--name", required=True, help="display name")
    p_apz.add_argument("--order", type=int, required=True, help="phase ordinal (1, 2, 3, …)")
    p_apz.add_argument(
        "--phase-id",
        dest="phase_id",
        default=None,
        help="override the minted phase id (testing / idempotency)",
    )
    p_apz.set_defaults(func=cmd_add_phase)

    p_rpz = subs.add_parser("remove-phase", help="delete a state/phases/<id>.json file")
    p_rpz.add_argument("--repo", default=".")
    p_rpz.add_argument("--phase-id", dest="phase_id", required=True)
    p_rpz.set_defaults(func=cmd_remove_phase)

    p_assign = subs.add_parser(
        "assign-feature-to-phase",
        help="add a feat_* id to a phase's feature_ids (strips it from any other phase first)",
    )
    p_assign.add_argument("--repo", default=".")
    p_assign.add_argument("--feat-id", dest="feat_id", required=True)
    p_assign.add_argument("--phase-id", dest="phase_id", required=True)
    p_assign.set_defaults(func=cmd_assign_feature_to_phase)

    p_unassign = subs.add_parser(
        "unassign-feature-from-phase",
        help="remove a feat_* id from a phase's feature_ids",
    )
    p_unassign.add_argument("--repo", default=".")
    p_unassign.add_argument("--feat-id", dest="feat_id", required=True)
    p_unassign.add_argument("--phase-id", dest="phase_id", required=True)
    p_unassign.set_defaults(func=cmd_unassign_feature_from_phase)

    p_plan = subs.add_parser("mint-plan", help="materialize phased impl stubs from state/plan.json")
    p_plan.add_argument("--repo", default=".")
    p_plan.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        help="print the would-mint / would-reseed lists without writing state files",
    )
    p_plan.set_defaults(func=cmd_mint_plan)

    p_ls = subs.add_parser(
        "list-scopes", help="enumerate a tier's scopes from the identity ledgers"
    )
    p_ls.add_argument("--repo", default=".")
    p_ls.add_argument("--tier", required=True, choices=["comparch", "subcomparch"])
    p_ls.set_defaults(func=cmd_list_scopes)

    # ---- read subcommands (projection) ----

    p_gst = subs.add_parser("get-state", help="print the state JSON for a scope")
    _add_scope_args(p_gst)
    _add_ref_arg(p_gst)
    p_gst.set_defaults(func=cmd_get_state)

    p_gc = subs.add_parser("get-context", help="print the generation context bundle")
    _add_scope_args(p_gc)
    _add_ref_arg(p_gc)
    p_gc.add_argument(
        "--prompt-variant",
        dest="prompt_variant",
        default="default",
        choices=["default", "modify"],
        help=(
            "swap the bundle's ``instructions`` field for the per-tier modify prompt "
            "(siege/prompts/modify_<tier>.md). 'modify' is for surgical edits via "
            "the /modify_* skills; falls back to the default prompt if the tier has "
            "no modify variant. (default: default)"
        ),
    )
    p_gc.set_defaults(func=cmd_get_context)

    p_grc = subs.add_parser("get-review-context", help="print the review context bundle")
    _add_scope_args(p_grc)
    _add_ref_arg(p_grc)
    p_grc.add_argument("--draft-sha", dest="draft_sha", required=True)
    p_grc.set_defaults(func=cmd_get_review_context)

    p_cp = subs.add_parser("compute-plan", help="print the phasing plan projection")
    p_cp.add_argument("--repo", default=".")
    _add_ref_arg(p_cp)
    p_cp.set_defaults(func=cmd_compute_plan)

    p_gss = subs.add_parser("get-structure-summary", help="print a tier's structure summary")
    p_gss.add_argument("--repo", default=".")
    p_gss.add_argument("--tier", required=True, choices=ALL_TIERS)
    _add_ref_arg(p_gss)
    p_gss.set_defaults(func=cmd_get_structure_summary)

    p_gpg = subs.add_parser("get-project-graph", help="print the whole-project node + edge graph")
    p_gpg.add_argument("--repo", default=".")
    _add_ref_arg(p_gpg)
    p_gpg.set_defaults(func=cmd_get_project_graph)

    p_grs = subs.add_parser("get-review-summary", help="print a tier's review summary")
    p_grs.add_argument("--repo", default=".")
    p_grs.add_argument("--tier", required=True, choices=ALL_TIERS)
    _add_ref_arg(p_grs)
    p_grs.set_defaults(func=cmd_get_review_summary)

    p_lb = subs.add_parser("list-batches", help="list state/batches/<id>.json files")
    p_lb.add_argument("--repo", default=".")
    _add_ref_arg(p_lb)
    p_lb.add_argument("--status", default=None)
    p_lb.set_defaults(func=cmd_list_batches)

    # ---- propagation lifecycle (step 7) ----

    p_op = subs.add_parser(
        "open-propagation",
        help="materialize a fresh state/propagations/<id>.json from a worklist",
    )
    p_op.add_argument("--repo", default=".")
    p_op.add_argument("--op-type", dest="op_type", required=True)
    p_op.add_argument(
        "--worklist-json",
        dest="worklist_json",
        default="[]",
        help="JSON array of {scope: {tier, comp_id?, ...}, status?, note?}",
    )
    p_op.add_argument(
        "--from-source-scope-json",
        dest="from_source_scope_json",
        default=None,
        help=(
            "compute the worklist top-down from this source scope "
            "(mutually exclusive with --worklist-json and --from-plan-change). Walks the "
            "chain feature_expansion → requirements → sysarch → comparch → "
            "subcomparch → impl and emits one entry per existing downstream "
            "scope. Fanin is skipped (bottom-up)."
        ),
    )
    p_op.add_argument(
        "--from-plan-change",
        dest="from_plan_change",
        action="store_true",
        help=(
            "diff the live plan projection against existing impl state files; "
            "emit pending entries for impls whose closure_resp_ids changed and "
            "skipped entries for impls the current plan no longer covers. "
            "Mutually exclusive with --worklist-json and --from-source-scope-json."
        ),
    )
    p_op.add_argument("--tier", default=None, choices=list(ALL_TIERS))
    p_op.add_argument("--threshold", type=int, default=None)
    p_op.add_argument(
        "--source-scope-json",
        dest="source_scope_json",
        default=None,
        help="JSON {tier, comp_id?, ...} — origin of the propagation",
    )
    p_op.add_argument(
        "--meta-json",
        dest="meta_json",
        default=None,
        help="optional JSON dict of free-form context (batch_id, comment, …)",
    )
    p_op.add_argument(
        "--propagation-id",
        dest="propagation_id",
        default=None,
        help="override the minted id (testing / idempotency)",
    )
    p_op.set_defaults(func=cmd_open_propagation)

    p_upd = subs.add_parser(
        "update-propagation-entry",
        help="flip one worklist entry's status in an existing propagation",
    )
    p_upd.add_argument("--repo", default=".")
    p_upd.add_argument("--propagation-id", dest="propagation_id", required=True)
    p_upd.add_argument(
        "--scope-json",
        dest="scope_json",
        required=True,
        help="JSON {tier, comp_id?, ...} identifying the entry",
    )
    p_upd.add_argument(
        "--status",
        required=True,
        choices=["pending", "in_progress", "done", "skipped"],
    )
    p_upd.add_argument("--note", default=None)
    p_upd.set_defaults(func=cmd_update_propagation_entry)

    p_cd = subs.add_parser(
        "compute-downstream",
        help="preview the top-down worklist a propagation from this source would carry",
    )
    p_cd.add_argument("--repo", default=".")
    _add_ref_arg(p_cd)
    p_cd.add_argument(
        "--source-scope-json",
        dest="source_scope_json",
        required=True,
        help="JSON {tier, comp_id?, parent_id?, sub_id?, phase?}",
    )
    p_cd.set_defaults(func=cmd_compute_downstream)

    p_lp = subs.add_parser("list-propagations", help="list state/propagations/<id>.json files")
    p_lp.add_argument("--repo", default=".")
    _add_ref_arg(p_lp)
    p_lp.add_argument(
        "--status",
        default=None,
        choices=["open", "complete"],
        help="filter by rolled-up status",
    )
    p_lp.set_defaults(func=cmd_list_propagations)

    p_aid = subs.add_parser(
        "add-input-doc",
        help="register a git-resident input document on the backend",
    )
    p_aid.add_argument("--repo", default=".", help="path to the project repo (default: cwd)")
    p_aid.add_argument("--project-id", dest="project_id", required=True)
    p_aid.add_argument(
        "--role", required=True, help="bundle-declared input role (e.g. project_doc)"
    )
    p_aid.add_argument("--name", required=True, help="human-readable name for the doc")
    p_aid.add_argument(
        "--content-file", dest="content_file", required=True, help="path to the body content"
    )
    p_aid.add_argument(
        "--body-path",
        dest="body_path",
        default=None,
        help="path inside the project repo to write to (default: inputs/<role>.md)",
    )
    p_aid.add_argument(
        "--no-push",
        dest="no_push",
        action="store_true",
        help="skip the git push (for local-only testing)",
    )
    p_aid.set_defaults(func=cmd_add_input_doc)

    p_lid = subs.add_parser("list-input-docs", help="list a project's input documents")
    p_lid.add_argument("--project-id", dest="project_id", required=True)
    p_lid.set_defaults(func=cmd_list_input_docs)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
