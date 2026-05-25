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
        new_propagation,
        write_propagation,
    )

    repo_root = Path(args.repo).resolve()
    raw_entries = json.loads(args.worklist_json) if args.worklist_json else []
    entries = [
        WorklistEntry(
            scope=Scope(**e["scope"]),
            status=str(e.get("status", "pending")),
            note=e.get("note"),
        )
        for e in raw_entries
    ]
    source_scope = Scope(**json.loads(args.source_scope_json)) if args.source_scope_json else None
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
    body_bytes = body_abs.read_bytes()
    body_sha = hashlib.sha256(body_bytes).hexdigest()

    # Re-sync to the hand-edited body: new sha + generated_at, fresh
    # nonce, status back to drafted, review/approval cleared.
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
    print(json.dumps(out))
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
    print(
        json.dumps(
            {
                "minted": minted,
                "reseeded": reseeded,
                "skipped_built": skipped,
                "dropped_by_plan": dropped,
            },
            indent=2,
        )
    )
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

    view = _open_local_view(args)
    builder = GENERATION_BUILDERS.get(args.tier)
    if builder is None:
        print(f"error: no generation context builder for tier {args.tier!r}", file=sys.stderr)
        return 2
    print(json.dumps(builder(view, _scope_from_args(args)), indent=2))
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

    p_plan = subs.add_parser("mint-plan", help="materialize phased impl stubs from state/plan.json")
    p_plan.add_argument("--repo", default=".")
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

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
