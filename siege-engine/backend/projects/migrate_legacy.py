"""Clone a legacy SQL-backed project into a fresh v3 substrate project.

The legacy backend keeps a project's graph in SQL (Nodes / Edges /
Fragments / Drafts). v3 keeps the same information as artifact files in
a git repo (bodies + identity ledgers + state JSON), parsed and
projected on read. This module reads a legacy project's data and
writes a v3 substrate into a *new* ``source="upload"`` Project so the
v3 read endpoints can render it. The legacy project is never mutated.

Scope today: the four substrate tiers v3 currently projects —
``feature_expansion`` / ``requirements`` / ``sysarch`` / ``comparch``
(structural only; per-comp fragments concatenate into the comparch
body for forward-compat but the graph projection doesn't read them
yet). ``subcomparch`` / ``impl`` / ``fanin`` are not migrated.

The migrator is *defensive*: missing tiers are skipped with a note in
the report, the comparch alias scheme synthesizes from the legacy
comp_id (since the original sub aliases aren't persisted), and the
result is validated by running ``build_project_graph`` before the
Project row is committed. On any failure the on-disk repo + the new
Project row are rolled back together — the original legacy project is
always safe.
"""

from __future__ import annotations

import logging
import re
import secrets
import shutil
import subprocess
from collections import defaultdict
from pathlib import Path
from typing import NamedTuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.config import settings as backend_settings
from backend.models import Project
from backend.models.node import Fragment, Node
from siege.git_view import local_view
from siege.manifest import Manifest, write_manifest
from siege.projection.graph import build_project_graph
from siege.state import DraftBlock, Scope, State, now_iso, sha256_text, write_state

logger = logging.getLogger(__name__)

# Per-comp fragments the legacy comparch tier writes. Order matters
# only for human readability of the migrated body — the v3 projection
# ignores everything outside the <subcomponents> block.
_COMPARCH_FRAGMENT_KINDS = (
    "comparchtechspec",
    "comparchpubapi",
    "comparchprivapi",
    "comparchpolicies",
    "comparchdeps",
    "comparchfailuresurface",
)

_COMPONENT_BLOCK = re.compile(r"<component\b([^>]*)>", re.S)
_ALIAS_ATTR = re.compile(r'\balias\s*=\s*"([^"]*)"')


class MigrationReport(NamedTuple):
    new_project_id: str
    feat_count: int
    resp_count: int
    comp_count: int
    decomposed_comp_count: int
    subcomp_count: int
    dependency_edges: int
    domain_parent_edges: int
    skipped_tiers: list[str]
    warnings: list[str]


def migrate_to_v3(
    db: Session,
    legacy_project_id: str,
    new_name: str | None = None,
) -> tuple[Project, MigrationReport]:
    """Migrate ``legacy_project_id`` to a new upload-sourced v3 Project."""
    legacy = db.get(Project, legacy_project_id)
    if legacy is None:
        raise ValueError(f"legacy project {legacy_project_id!r} not found")

    project = Project(
        name=new_name or f"{legacy.name} (v3)",
        description=legacy.description,
        remote_url=None,
        github_repo_slug=None,
        auto_push_enabled=False,
        source="upload",
        git_repo_path="",
    )
    db.add(project)
    db.flush()
    repo_path = Path(backend_settings.git_repos_base_path) / project.id

    try:
        repo_path.parent.mkdir(parents=True, exist_ok=True)
        repo_path.mkdir(exist_ok=False)
        _init_repo(repo_path)

        report = _build_v3_substrate(db, legacy_project_id, project.id, repo_path)

        _git_commit(repo_path, f"migrated from legacy project {legacy_project_id}")

        # Validate via the v3 projection before committing the Project row.
        view = local_view(repo_path, ref="main")
        graph = build_project_graph(view)
        if not graph.get("nodes"):
            raise ValueError(
                "v3 projection of migrated project yielded zero nodes; "
                "legacy project likely has no expansion / reqs / sysarch content "
                "to migrate"
            )

        project.git_repo_path = str(repo_path)
        db.commit()
        db.refresh(project)
        return project, report
    except Exception:
        shutil.rmtree(repo_path, ignore_errors=True)
        db.rollback()
        if project in db:
            db.delete(project)
            db.commit()
        raise


# ---------------- substrate construction ----------------


def _build_v3_substrate(
    db: Session, legacy_project_id: str, new_project_id: str, repo_path: Path
) -> MigrationReport:
    nodes_by_tier = _load_legacy_nodes(db, legacy_project_id)
    fragments_by_owner = _load_fragments(db, legacy_project_id)

    skipped: list[str] = []
    warnings: list[str] = []
    feat_count = resp_count = comp_count = subcomp_count = 0
    decomposed_count = dep_count = dp_count = 0
    proj_scope_id = "proj"  # v3 substrate top-level id, opaque

    # ---- feature_expansion ----
    expansion = next(iter(nodes_by_tier.get("expansion", [])), None)
    if expansion is not None:
        body = expansion.content or ""
        feats = sorted(nodes_by_tier.get("feat", []), key=lambda n: n.display_order)
        _write_substrate(
            repo_path,
            Scope(tier="feature_expansion", comp_id=proj_scope_id),
            body=body,
            manifest_nodes=[{"id": f.id, "name": f.name} for f in feats],
        )
        feat_count = len(feats)
    else:
        skipped.append("feature_expansion")

    # ---- requirements ----
    reqs = next(iter(nodes_by_tier.get("reqs", [])), None)
    if reqs is not None:
        body = reqs.content or ""
        resps = sorted(
            [r for r in nodes_by_tier.get("resp", []) if r.parent_id is None],
            key=lambda n: n.display_order,
        )
        _write_substrate(
            repo_path,
            Scope(tier="requirements", comp_id=proj_scope_id),
            body=body,
            manifest_nodes=[{"id": r.id, "name": r.name} for r in resps],
        )
        resp_count = len(resps)
    else:
        skipped.append("requirements")

    # ---- sysarch + per-comp comparch ----
    sysarch = next(iter(nodes_by_tier.get("sysarch", [])), None)
    top_comps = sorted(
        [c for c in nodes_by_tier.get("comp", []) if c.parent_id is None],
        key=lambda n: n.display_order,
    )
    comp_alias_by_id: dict[str, str] = {}
    if sysarch is not None:
        body = sysarch.content or ""
        body_aliases = _parse_component_aliases(body)
        if len(body_aliases) != len(top_comps):
            warnings.append(
                f"sysarch body declares {len(body_aliases)} components but the DB has "
                f"{len(top_comps)} top-level comps; aligning by min length"
            )
        manifest_nodes: list[dict] = []
        for i, comp in enumerate(top_comps):
            alias = body_aliases[i] if i < len(body_aliases) else f"comp_{i}"
            comp_alias_by_id[comp.id] = alias
            manifest_nodes.append({"id": comp.id, "alias": alias})
        _write_substrate(
            repo_path,
            Scope(tier="sysarch", comp_id=proj_scope_id),
            body=body,
            manifest_nodes=manifest_nodes,
        )
        comp_count = len(top_comps)
        # Edge counts are derived from the body's <dep>/<parent> tags
        # (the v3 projection reads them the same way).
        dep_count = len(re.findall(r"<dep\b", body))
        dp_count = len(re.findall(r"<parent\b", body))
    else:
        skipped.append("sysarch")

    # ---- comparch per top-level comp ----
    for comp in top_comps:
        subs = sorted(
            [n for n in nodes_by_tier.get("comp", []) if n.parent_id == comp.id],
            key=lambda n: n.display_order,
        )
        frags = [
            f
            for f in fragments_by_owner.get(comp.id, [])
            if f.fragment_kind in _COMPARCH_FRAGMENT_KINDS
        ]
        if not subs and not frags:
            # Comp was never decomposed at the comparch tier; skip.
            continue
        body = _build_comparch_body(subs, frags)
        sub_manifest_nodes = [
            {"id": sub.id, "alias": _synth_subcomp_alias(sub.id, i)} for i, sub in enumerate(subs)
        ]
        _write_substrate(
            repo_path,
            Scope(tier="comparch", comp_id=comp.id),
            body=body,
            manifest_nodes=sub_manifest_nodes,
        )
        decomposed_count += 1
        subcomp_count += len(subs)

    return MigrationReport(
        new_project_id=new_project_id,
        feat_count=feat_count,
        resp_count=resp_count,
        comp_count=comp_count,
        decomposed_comp_count=decomposed_count,
        subcomp_count=subcomp_count,
        dependency_edges=dep_count,
        domain_parent_edges=dp_count,
        skipped_tiers=skipped,
        warnings=warnings,
    )


# ---------------- helpers ----------------


def _load_legacy_nodes(db: Session, project_id: str) -> dict[str, list[Node]]:
    rows = list(db.execute(select(Node).where(Node.project_id == project_id)).scalars())
    by_tier: dict[str, list[Node]] = defaultdict(list)
    for n in rows:
        by_tier[n.tier].append(n)
    return by_tier


def _load_fragments(db: Session, project_id: str) -> dict[str, list[Fragment]]:
    rows = list(db.execute(select(Fragment).where(Fragment.project_id == project_id)).scalars())
    by_owner: dict[str, list[Fragment]] = defaultdict(list)
    for f in rows:
        by_owner[f.owner_id].append(f)
    return by_owner


def _parse_component_aliases(body: str) -> list[str]:
    """Aliases for each ``<component alias="…">`` block, in body order."""
    out: list[str] = []
    for attrs in _COMPONENT_BLOCK.findall(body):
        m = _ALIAS_ATTR.search(attrs)
        out.append(m.group(1) if m else "")
    return out


def _synth_subcomp_alias(comp_id: str, index: int) -> str:
    """Subcomp aliases aren't persisted in legacy. Derive one from the
    comp_id so it's stable + unique per project. Falls back to a
    sequenced placeholder if the id has an unexpected shape."""
    if comp_id.startswith("comp_") and len(comp_id) > 5:
        return comp_id[5:]
    return f"sub_{index}"


def _build_comparch_body(subs: list[Node], fragments: list[Fragment]) -> str:
    """Assemble a v3-grammar comparch body.

    The fragment content rides along as plain markdown sections (the
    v3 projection ignores it today; preserved verbatim so a future
    reader can see what the legacy backend had). The load-bearing part
    is the ``<subcomponents>`` block — that's what the v3 ledger
    derivation reads to mint sub IDs.
    """
    parts: list[str] = []
    frags_by_kind = {f.fragment_kind: f for f in fragments}
    for kind in _COMPARCH_FRAGMENT_KINDS:
        f = frags_by_kind.get(kind)
        if f and f.content:
            parts.append(f"## {kind}\n\n{f.content.strip()}\n")
    parts.append("<subcomponents>")
    for i, sub in enumerate(subs):
        alias = _synth_subcomp_alias(sub.id, i)
        foundation = "<foundation/>" if sub.is_foundation else ""
        # Escape ``<`` / ``&`` in names defensively — legacy names are
        # free-form text. Aliases come from comp_ids, safe by shape.
        safe_name = sub.name.replace("&", "&amp;").replace("<", "&lt;")
        parts.append(
            f'  <subcomponent alias="{alias}"><name>{safe_name}</name>{foundation}</subcomponent>'
        )
    parts.append("</subcomponents>")
    return "\n".join(parts) + "\n"


def _write_substrate(
    repo_path: Path,
    scope: Scope,
    body: str,
    manifest_nodes: list[dict],
) -> None:
    body_path = repo_path / scope.body_path()
    body_path.parent.mkdir(parents=True, exist_ok=True)
    body_path.write_text(body, encoding="utf-8")
    body_sha = sha256_text(body)

    manifest = Manifest(
        schema_version=2,
        substrate=scope,
        derived_from_sha256=body_sha,
        nodes=manifest_nodes,
    )
    write_manifest(repo_path / scope.ids_path(), manifest)

    state = State(
        schema_version=1,
        scope=scope,
        status="approved",
        nonce=secrets.token_hex(8),
        draft=DraftBlock(
            body_path=scope.body_path(),
            body_sha256=body_sha,
            generated_at=now_iso(),
            generator_metadata={"migrated": True},
            prior_review_text="",
        ),
    )
    write_state(state, repo_path / scope.state_path())


def _init_repo(repo_path: Path) -> None:
    """Init a fresh local repo with ``main`` as the default branch,
    matching the sample / upload conventions."""
    subprocess.run(
        ["git", "init", "-q", "-b", "main", str(repo_path)], check=True, capture_output=True
    )
    for key, value in (
        ("user.email", "migration@siege.local"),
        ("user.name", "Siege Migration"),
        ("commit.gpgsign", "false"),
    ):
        subprocess.run(
            ["git", "-C", str(repo_path), "config", key, value], check=True, capture_output=True
        )


def _git_commit(repo_path: Path, message: str) -> None:
    subprocess.run(["git", "-C", str(repo_path), "add", "-A"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo_path), "commit", "-q", "-m", message],
        check=True,
        capture_output=True,
    )
