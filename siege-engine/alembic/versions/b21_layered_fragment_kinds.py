"""v2 layered fragment kinds — split sysarch / comparch / subcomparch layers

Revision ID: b21_layered_fragment_kinds
Revises: b20_job_is_deferred
Create Date: 2026-04-27

Adds prefixed ``comparch*`` / ``subcomparch*`` fragment kinds so
the rich content the comparch / subcomparch tiers produce no
longer overwrites the skeletal seeds the parent-tier mint emits.
Pairs with the layered fragment model in
``backend/graph/fragments.py`` — see the module docstring for the
runtime semantics. The legacy unprefixed slots survive as the
"lowest layer" + reader-side fallback target until projects are
fully migrated (i.e. until the user regenerates the parent tier
to write fresh skeletal content into the legacy slot).

Forward-only; downgrade raises NotImplementedError.

Two-step upgrade:

1. Widen ``ck_fragments_fragment_kind`` to allow the 10 new
   prefixed kinds.
2. Copy legacy fragment content into the new layer slots for
   each comp whose tier-specific content is already approved
   (top-level comp with non-empty ``Node.content`` → approved
   comparch; subcomp with non-empty ``Node.content`` → approved
   subcomparch). The legacy rows stay in place — for top-level
   comps they'll be re-seeded with the sysarch skeletal content
   the next time the user regenerates sysarch, and for subcomps
   they'll be re-seeded with the comparch-mint skeletal content
   the next time their parent's comparch regenerates. Until
   that happens, the reader fallback in
   ``backend/graph/fragments.py`` keeps the legacy rich content
   visible to readers.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b21_layered_fragment_kinds"
down_revision: Union[str, Sequence[str], None] = "b20_job_is_deferred"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Must match ``backend.models.node.FRAGMENT_KINDS`` exactly.
# Inlined here so the migration stays self-contained — alembic
# migrations are forward-only and shouldn't import app code whose
# definitions could drift after the migration was authored.
NEW_FRAGMENT_KINDS = (
    "techspec",
    "pubapi",
    "privapi",
    "policies",
    "deps",
    "failuresurface",
    "comparchtechspec",
    "comparchpubapi",
    "comparchprivapi",
    "comparchpolicies",
    "comparchdeps",
    "comparchfailuresurface",
    "subcomparchtechspec",
    "subcomparchpubapi",
    "subcomparchprivapi",
    "subcomparchdeps",
)

# (legacy_kind, comparch-layer-kind) pairs — one INSERT per pair
# fans the legacy comp-level content out into the new comparch slot.
_COMPARCH_LAYER_COPIES = (
    ("techspec", "comparchtechspec"),
    ("pubapi", "comparchpubapi"),
    ("privapi", "comparchprivapi"),
    ("policies", "comparchpolicies"),
    ("deps", "comparchdeps"),
    ("failuresurface", "comparchfailuresurface"),
)

# (legacy_kind, subcomparch-layer-kind) pairs — same idea, for the
# subcomp-level subcomparch content.
_SUBCOMPARCH_LAYER_COPIES = (
    ("techspec", "subcomparchtechspec"),
    ("pubapi", "subcomparchpubapi"),
    ("privapi", "subcomparchprivapi"),
    ("deps", "subcomparchdeps"),
)


def upgrade() -> None:
    # Step 1: widen the CHECK constraint to allow the new kinds.
    with op.batch_alter_table("fragments") as batch:
        batch.drop_constraint("ck_fragments_fragment_kind", type_="check")
        batch.create_check_constraint(
            "ck_fragments_fragment_kind",
            f"fragment_kind IN {NEW_FRAGMENT_KINDS}",
        )

    # Step 2: copy legacy fragment content into the new layer slots
    # for owners whose tier content is already approved.
    bind = op.get_bind()
    _copy_layer(
        bind,
        owner_filter="n.parent_id IS NULL",
        copies=_COMPARCH_LAYER_COPIES,
    )
    _copy_layer(
        bind,
        owner_filter="n.parent_id IS NOT NULL",
        copies=_SUBCOMPARCH_LAYER_COPIES,
    )


def _copy_layer(bind, owner_filter: str, copies) -> None:
    """Copy each legacy fragment row to its new-layer slot.

    Each ``(legacy_kind, new_kind)`` pair triggers one
    ``INSERT OR IGNORE … SELECT`` that mirrors the legacy
    fragment into the new slot for every comp matching
    ``owner_filter`` whose ``Node.content`` is non-empty (= its
    tier's content is approved). ``INSERT OR IGNORE`` makes the
    upgrade idempotent — if the destination row already exists,
    the existing row wins so a partial-failure re-run is safe.
    """
    for legacy_kind, new_kind in copies:
        bind.execute(
            sa.text(
                f"""
                INSERT OR IGNORE INTO fragments
                  (id, project_id, owner_id, fragment_kind, content, updated_at)
                SELECT
                  fr.owner_id || '_' || :new_kind AS id,
                  fr.project_id,
                  fr.owner_id,
                  :new_kind AS fragment_kind,
                  fr.content,
                  fr.updated_at
                FROM fragments AS fr
                JOIN nodes AS n ON n.id = fr.owner_id
                WHERE fr.fragment_kind = :legacy_kind
                  AND n.tier = 'comp'
                  AND {owner_filter}
                  AND COALESCE(n.content, '') != ''
                """
            ),
            {"new_kind": new_kind, "legacy_kind": legacy_kind},
        )


def downgrade() -> None:
    raise NotImplementedError("v2 migrations are forward-only.")
