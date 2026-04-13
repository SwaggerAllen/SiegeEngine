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
    """

    TECHSPEC = "techspec"
    PUBAPI = "pubapi"
    PRIVAPI = "privapi"
    POLICIES = "policies"
    DEPS = "deps"


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
