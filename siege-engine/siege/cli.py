"""Writer-side CLI invoked by skills.

Skills compose the artifact body with the LLM, then shell out to this
CLI to materialize the state JSON file and (optionally) commit + push.
Keeps the JSON-shape discipline inside Python so prompts don't have
to hand-write valid JSON.

Subcommands:

    write-draft    — write state JSON + body for a `drafted` transition
    write-review   — write state JSON + review.md for a `reviewed` transition
    write-approval — flip `reviewed` to `approved`
    repair-drift   — recompute body_sha256 fields, bump nonce
    mint-batch     — write a state/batches/<id>.json
    mint-nonce     — emit a fresh ULID-shaped nonce on stdout (utility)

All subcommands work on the local working tree only — they DON'T do
git operations. The calling skill is responsible for `git add`,
`git commit`, `git push`.

Run with ``python -m siege.cli <subcommand> --help`` for per-command
flags.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import secrets
import sys
from pathlib import Path
from typing import Any

from siege.parsers.review_xml import parse_review
from siege.state import (
    ALL_TIERS,
    PHASED_TIERS,
    ApprovalBlock,
    DraftBlock,
    ReviewBlock,
    Scope,
    State,
    now_iso,
    parse_state,
    sha256_text,
    write_state,
)
from siege.validate import validate_artifact

# ULID is overkill for the v0 idempotency cache. A 26-char base32
# secret has the same effective collision resistance.
_NONCE_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUV"


def mint_nonce() -> str:
    n = secrets.randbits(128)
    chars: list[str] = []
    for _ in range(26):
        chars.append(_NONCE_ALPHABET[n & 0x1F])
        n >>= 5
    return "".join(reversed(chars))


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
                "model": args.model or "",
            },
            prior_review_text=prior_review_text,
        ),
        is_foundation=(prior.is_foundation if prior is not None else bool(args.is_foundation)),
        edges=edges,
        meta=meta,
    )
    state_path = repo_root / scope.state_path()
    write_state(state, state_path)
    print(json.dumps({"state_path": str(state_path), "body_sha256": body_sha}))
    return 0


def cmd_write_review(args: argparse.Namespace) -> int:
    repo_root = Path(args.repo).resolve()
    scope = _scope_from_args(args)
    review_path = Path(args.review_path)
    review_abs = repo_root / review_path
    if not review_abs.exists():
        print(f"error: review file does not exist: {review_abs}", file=sys.stderr)
        return 2
    review_text = review_abs.read_text(encoding="utf-8")
    parsed = parse_review(review_text)

    prior = _existing_state(repo_root, scope)
    if prior is None or prior.draft is None:
        print(
            "error: cannot write a review for a scope that isn't drafted",
            file=sys.stderr,
        )
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
            score=parsed.score,
            reviewer_metadata={"model": args.model or ""},
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
                "score": parsed.score,
                "intro_first_sentence": parsed.intro.split(".", 1)[0],
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

    if not changes:
        print(json.dumps({"changed": False}))
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
    print(json.dumps({"changed": True, "deltas": changes}))
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


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="siege.cli")
    subs = p.add_subparsers(dest="cmd", required=True)

    p_draft = subs.add_parser("write-draft", help="materialize state JSON for a drafted scope")
    _add_scope_args(p_draft)
    p_draft.add_argument("--body-path", dest="body_path", required=True)
    p_draft.add_argument("--thinking-effort", dest="thinking_effort", default=None)
    p_draft.add_argument("--batch-id", dest="batch_id", default=None)
    p_draft.add_argument("--model", default=None)
    p_draft.add_argument("--prior-review-text", dest="prior_review_text", default=None)
    p_draft.add_argument("--is-foundation", dest="is_foundation", action="store_true")
    p_draft.set_defaults(func=cmd_write_draft)

    p_rev = subs.add_parser("write-review", help="materialize state JSON for a reviewed scope")
    _add_scope_args(p_rev)
    p_rev.add_argument("--review-path", dest="review_path", required=True)
    p_rev.add_argument("--model", default=None)
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

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
