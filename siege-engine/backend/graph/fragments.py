"""Fragment ID format for transcluded architecture-doc sections.

A fragment is a parseable section of an architecture doc — currently
``<technical-specification>``, ``<public-surface>``,
``<private-surface>``, or ``<dependencies>``. Fragments are
transcluded by multiple docs (a component's public surface appears
in both the component arch and the system architecture), and diff
propagation operates on fragment granularity.

Fragment IDs have the form ``<owner_id>_<fragment_kind>`` where the
owner is a node ID from :mod:`backend.graph.ids`. They are never
minted independently — fragments don't move, so their identity is
tied to their owner.

Parsing splits on the **last** underscore: owner IDs contain an
underscore themselves (``comp_a3f7k2m9``), so splitting on the first
underscore would be wrong. This means fragment kinds **must be
single-token** (no underscore in the kind name); enforced at import
time below.
"""

from __future__ import annotations

from enum import Enum

from backend.graph.ids import InvalidIdError
from backend.graph.ids import validate as validate_owner_id


class FragmentKind(str, Enum):
    """Vocabulary of parseable architecture-doc fragments.

    Every member value must be a single token (no underscore). See
    the module docstring for why.

    Layered model (per node, lowest writer wins as fallback for
    readers; each tier's reset only clears its own layer):

    - Sysarch layer — ``TECHSPEC`` / ``PUBAPI`` on a top-level comp.
      Written by ``sysarch_mint`` as the comp's role + api-intent
      seed. Survives comparch reset.
    - Comparch layer — ``COMPARCH_*`` on the comp itself (rich
      output), plus ``TECHSPEC`` / ``PUBAPI`` on each subcomp
      (skeletal seed for subcomparch). Written by ``comparch_mint``.
      Comparch reset clears just the comp's ``COMPARCH_*``;
      subcomp seeds cascade with the subcomp via ``NodeDeleted``.
    - Subcomparch layer — ``SUBCOMPARCH_*`` on a subcomp (rich
      output). Written by ``subcomparch_mint``. Subcomparch reset
      clears these; the comparch-mint skeletal seeds on the sub
      survive.
    """

    # Sysarch-layer kinds (also serve as the comparch-mint skeletal
    # seeds for subcomps — same shape one tier down).
    TECHSPEC = "techspec"
    PUBAPI = "pubapi"
    # Pre-layered kinds retained for backward compat on legacy
    # projects until those rows are migrated to the comparch layer.
    # Going forward, fresh comparch / subcomparch output never
    # writes here — it goes to the prefixed kinds below. Readers
    # check the prefixed kind first and fall back to the unprefixed
    # value if the legacy slot still holds the rich content.
    PRIVAPI = "privapi"
    POLICIES = "policies"
    DEPS = "deps"
    # ``failuresurface`` is stored as one token (no underscore) to
    # satisfy the single-token invariant enforced below — owner IDs
    # contain underscores so the fragment-ID parser must split on the
    # last underscore.
    FAILURE_SURFACE = "failuresurface"

    # Comparch-layer kinds — rich content for a top-level comp,
    # written by ``comparch_mint``. Comparch reset clears these.
    COMPARCH_TECHSPEC = "comparchtechspec"
    COMPARCH_PUBAPI = "comparchpubapi"
    COMPARCH_PRIVAPI = "comparchprivapi"
    COMPARCH_POLICIES = "comparchpolicies"
    COMPARCH_DEPS = "comparchdeps"
    COMPARCH_FAILURE_SURFACE = "comparchfailuresurface"

    # Subcomparch-layer kinds — rich content for a subcomp,
    # written by ``subcomparch_mint``. Subcomparch reset clears these.
    SUBCOMPARCH_TECHSPEC = "subcomparchtechspec"
    SUBCOMPARCH_PUBAPI = "subcomparchpubapi"
    SUBCOMPARCH_PRIVAPI = "subcomparchprivapi"
    SUBCOMPARCH_DEPS = "subcomparchdeps"


# Tier-layer membership lookups — used by reset wiring + reader
# fallback helpers so call sites don't list the kinds inline.
COMPARCH_LAYER_KINDS: tuple[FragmentKind, ...] = (
    FragmentKind.COMPARCH_TECHSPEC,
    FragmentKind.COMPARCH_PUBAPI,
    FragmentKind.COMPARCH_PRIVAPI,
    FragmentKind.COMPARCH_POLICIES,
    FragmentKind.COMPARCH_DEPS,
    FragmentKind.COMPARCH_FAILURE_SURFACE,
)
SUBCOMPARCH_LAYER_KINDS: tuple[FragmentKind, ...] = (
    FragmentKind.SUBCOMPARCH_TECHSPEC,
    FragmentKind.SUBCOMPARCH_PUBAPI,
    FragmentKind.SUBCOMPARCH_PRIVAPI,
    FragmentKind.SUBCOMPARCH_DEPS,
)


# Mapping from a comparch-layer kind to its non-layered counterpart,
# used by the reader fallback (when a fresh project's comparch-layer
# slot is empty, fall back to the legacy slot that used to hold the
# rich content). The migration copies legacy values into the new
# layer once at upgrade time, so post-migration reads see the right
# content from the comparch layer; this fallback exists for the
# transition window and as defence-in-depth.
COMPARCH_LAYER_FALLBACK: dict[FragmentKind, FragmentKind] = {
    FragmentKind.COMPARCH_TECHSPEC: FragmentKind.TECHSPEC,
    FragmentKind.COMPARCH_PUBAPI: FragmentKind.PUBAPI,
    FragmentKind.COMPARCH_PRIVAPI: FragmentKind.PRIVAPI,
    FragmentKind.COMPARCH_POLICIES: FragmentKind.POLICIES,
    FragmentKind.COMPARCH_DEPS: FragmentKind.DEPS,
    FragmentKind.COMPARCH_FAILURE_SURFACE: FragmentKind.FAILURE_SURFACE,
}
SUBCOMPARCH_LAYER_FALLBACK: dict[FragmentKind, FragmentKind] = {
    FragmentKind.SUBCOMPARCH_TECHSPEC: FragmentKind.TECHSPEC,
    FragmentKind.SUBCOMPARCH_PUBAPI: FragmentKind.PUBAPI,
    FragmentKind.SUBCOMPARCH_PRIVAPI: FragmentKind.PRIVAPI,
    FragmentKind.SUBCOMPARCH_DEPS: FragmentKind.DEPS,
}

# Inverse lookups — given a sysarch/legacy kind, what's the
# layered counterpart for a top-level comp / a subcomp? Used by
# :func:`best_layered_fragment_content` to dispatch by owner tier.
LAYERED_KIND_FOR_TOP_LEVEL: dict[FragmentKind, FragmentKind] = {
    legacy: layer for layer, legacy in COMPARCH_LAYER_FALLBACK.items()
}
LAYERED_KIND_FOR_SUBCOMP: dict[FragmentKind, FragmentKind] = {
    legacy: layer for layer, legacy in SUBCOMPARCH_LAYER_FALLBACK.items()
}


# Enforce the single-token invariant at import time so a future
# addition with an underscore fails loudly rather than corrupting
# fragment-ID parsing.
for _kind in FragmentKind:
    assert "_" not in _kind.value, (
        f"FragmentKind.{_kind.name} value {_kind.value!r} contains an "
        "underscore; fragment kinds must be single-token because "
        "parse_fragment_id splits on the last underscore."
    )
del _kind


class InvalidFragmentIdError(ValueError):
    """Raised when a fragment ID does not match the scheme."""


def fragment_id(owner_id: str, kind: FragmentKind) -> str:
    """Build a fragment ID from its owner and kind.

    The owner ID is validated to catch malformed input early.
    """
    validate_owner_id(owner_id)
    return f"{owner_id}_{kind.value}"


def fragment_changed(old_content: str, new_content: str) -> bool:
    """Return True when a fragment's content changed materially.

    Phase 9 MVP: whitespace-normalized string inequality. A
    ``FragmentUpdated`` event whose payload matches the projection's
    current content (modulo surrounding whitespace) is a no-op write
    — the fanout dispatcher treats it as such and emits no
    staleness markers for dependents.

    Richer structured diffs (per-field or per-section) are a
    post-MVP refinement. For the crude "regen all downstream" fanout
    rule in Phase 9, any material content difference is enough to
    invalidate every reader; the dispatcher doesn't need to know
    exactly what changed.
    """
    return (old_content or "").strip() != (new_content or "").strip()


def best_layered_fragment_content(
    session,  # type: ignore[no-untyped-def]
    owner_node,  # type: ignore[no-untyped-def]
    sysarch_kind: FragmentKind,
) -> str:
    """Read the highest-layer non-empty fragment content for a comp owner.

    Layer preference by owner tier:

    - Top-level comp (``parent_id is None``): comparch layer
      (:data:`LAYERED_KIND_FOR_TOP_LEVEL`) → sysarch / legacy slot
    - Subcomp (``parent_id`` points at another comp): subcomparch
      layer (:data:`LAYERED_KIND_FOR_SUBCOMP`) → sysarch / legacy
      slot

    Returns empty string when neither layer has populated content.
    Pre-migration projects whose rich content lives in the legacy
    slot are read transparently because the layered slot is empty
    and the lookup falls through.

    ``sysarch_kind`` must be a sysarch-layer / legacy kind. Passing
    a layer-prefixed kind raises ``ValueError`` — call sites should
    name the section semantically (TECHSPEC / PUBAPI / …) and let
    the helper dispatch to the right layer.
    """
    from backend.models.node import Fragment, Node  # local: avoid cycle

    if not isinstance(owner_node, Node):
        raise TypeError(
            f"best_layered_fragment_content expects a Node, got {type(owner_node).__name__}"
        )
    # Caller should pass the legacy / sysarch-layer kind so this
    # helper can dispatch to the right per-tier layer. Passing a
    # layer-prefixed kind defeats the dispatch.
    if sysarch_kind in COMPARCH_LAYER_KINDS or sysarch_kind in SUBCOMPARCH_LAYER_KINDS:
        raise ValueError(
            f"best_layered_fragment_content: pass the sysarch-layer kind, not {sysarch_kind!r}"
        )

    if owner_node.parent_id is None:
        layered = LAYERED_KIND_FOR_TOP_LEVEL.get(sysarch_kind)
    else:
        layered = LAYERED_KIND_FOR_SUBCOMP.get(sysarch_kind)

    if layered is not None:
        layer_frag = session.get(Fragment, fragment_id(owner_node.id, layered))
        if layer_frag is not None and (layer_frag.content or "").strip():
            return layer_frag.content

    legacy_frag = session.get(Fragment, fragment_id(owner_node.id, sysarch_kind))
    return legacy_frag.content if legacy_frag is not None else ""


def parse_fragment_id(fid: str) -> tuple[str, FragmentKind]:
    """Parse a fragment ID into its (owner_id, fragment_kind) parts.

    Splits on the **last** underscore so that owner IDs containing
    underscores (which they always do) round-trip correctly.
    """
    if not isinstance(fid, str):
        raise InvalidFragmentIdError(f"Fragment ID must be a string, got {type(fid).__name__}")
    try:
        owner_id, kind_str = fid.rsplit("_", 1)
    except ValueError as exc:
        raise InvalidFragmentIdError(f"Fragment ID missing underscore separator: {fid!r}") from exc
    try:
        kind = FragmentKind(kind_str)
    except ValueError as exc:
        raise InvalidFragmentIdError(f"Unknown fragment kind in {fid!r}: {kind_str!r}") from exc
    try:
        validate_owner_id(owner_id)
    except InvalidIdError as exc:
        raise InvalidFragmentIdError(f"Invalid owner ID in fragment {fid!r}: {exc}") from exc
    return owner_id, kind
