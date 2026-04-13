"""Structural validators for parsed tag trees.

The lenient parser in :mod:`backend.graph.parsers.xml_sections`
extracts whatever tree it can find. These validators layer on top
and enforce the per-caller structural invariants — "this kind of
tree must have exactly these children, with exactly these tags,
with non-empty text in these leaf positions."

Validator errors are the signal that feeds back into the parse-
validate retry loop. The error messages are deliberately worded
to make sense as LLM feedback: they name the tag path that was
wrong and say what was expected.

Each caller adds its own ``validate_*`` function here:

* :func:`validate_features` — for the expansion → feat_* mint path
  (Phase 2).
* ``validate_arch_doc`` (future) — for the component arch doc
  parseable-sections path (Phase 4).
* And so on.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from backend.graph.parsers.xml_sections import TagNode, extract_tag_tree


class ValidationError(ValueError):
    """Raised when a parsed tag tree fails structural validation.

    Message is suitable for feeding back into a retry prompt —
    names the tag path and explains what's wrong.
    """


# ── Features (Phase 2: expansion → feat_*) ───────────────────────────


@dataclass(frozen=True)
class Feature:
    """A single validated feature from an expansion's <features> block.

    ``name`` is the short identifier (2–5 words, title case
    expected). ``intent`` is the paragraph-length description of
    what the feature does. Both are non-empty and already
    whitespace-stripped at their outer edges.

    ``group_label`` is the enclosing ``<group>``'s ``<name>`` if
    the feature was inside one, or ``None`` for ungrouped
    features. ``is_implicit`` is ``True`` when the ``<feature>``
    carried an ``<implicit/>`` marker, signalling that the LLM
    inferred it as obviously-necessary rather than finding it in
    the user's input doc.
    """

    name: str
    intent: str
    group_label: str | None = None
    is_implicit: bool = False


_FEATURE_ALLOWED_CHILDREN = {"name", "intent", "implicit"}
_FEATURES_ALLOWED_CHILDREN = {"feature", "group"}
_GROUP_ALLOWED_CHILDREN = {"name", "feature"}


def validate_features(tree: TagNode) -> list[Feature]:
    """Validate a parsed ``<features>`` tree and return its features.

    Shape:

    * ``tree.tag`` must be exactly ``"features"``.
    * ``<features>`` may contain a mix of ``<feature>`` entries
      (ungrouped) and ``<group>`` blocks (each holding one or more
      ``<feature>`` entries).
    * There must be at least one ``<feature>`` overall (grouped
      or ungrouped).
    * Unknown tags at any level are rejected.
    * Each ``<feature>`` contains exactly one ``<name>`` and
      exactly one ``<intent>``. Both must be non-empty after
      stripping. An optional ``<implicit/>`` marker flags the
      feature as LLM-inferred.
    * Each ``<group>`` contains exactly one ``<name>`` (the group
      label) and at least one ``<feature>``. Groups do not nest —
      a ``<group>`` inside a ``<group>`` is rejected.

    The returned list is **flat** in document order: grouped and
    ungrouped features appear in the order they were written,
    with each ``Feature.group_label`` reflecting its source
    ``<group>`` (or ``None`` if ungrouped).

    Raises :class:`ValidationError` on the first problem found,
    with a message naming the offending tag path.
    """
    if tree.tag != "features":
        raise ValidationError(
            f"Expected root tag <features>, got <{tree.tag}>. "
            "Wrap the feature list in a single <features>...</features> block."
        )

    # Reject unknown children at the features level. Only
    # <feature> and <group> are permitted.
    for child in tree.children:
        if child.tag not in _FEATURES_ALLOWED_CHILDREN:
            raise ValidationError(
                f"<features> contains an unexpected child <{child.tag}>. "
                "Only <feature> entries and <group> blocks are allowed at "
                "this level."
            )

    result: list[Feature] = []
    feature_index = 0  # flat position across groups + ungrouped
    for child in tree.children:
        if child.tag == "feature":
            result.append(_validate_feature(child, feature_index, group_label=None))
            feature_index += 1
        elif child.tag == "group":
            group_label, group_features = _validate_group(child, feature_index)
            result.extend(group_features)
            feature_index += len(group_features)

    if not result:
        raise ValidationError(
            "<features> block contains no <feature> entries. "
            "Every project must have at least one feature."
        )

    return result


def _validate_group(node: TagNode, base_index: int) -> tuple[str, list[Feature]]:
    """Validate a ``<group>`` block and return ``(label, [Feature, ...])``.

    ``base_index`` is the flat feature index the first child
    feature will take — used only for error messages to help the
    LLM locate the problem in a retry prompt.
    """
    # Reject unknown children inside a group.
    for child in node.children:
        if child.tag not in _GROUP_ALLOWED_CHILDREN:
            raise ValidationError(
                f"<group> contains an unexpected child <{child.tag}>. "
                "Only <name> and <feature> entries are allowed inside a <group>. "
                "Groups do not nest."
            )

    name_children = node.find_all("name")
    if len(name_children) == 0:
        raise ValidationError(
            "<group> is missing a <name> child. Every group must have "
            "exactly one <name> identifying the grouping theme."
        )
    if len(name_children) > 1:
        raise ValidationError(
            f"<group> has {len(name_children)} <name> children; exactly one is required."
        )

    label = name_children[0].text
    if not label:
        raise ValidationError(
            "<group> has an empty <name>. The group name must be a short "
            'label identifying the theme (e.g. "User Management").'
        )

    feature_children = node.find_all("feature")
    if not feature_children:
        raise ValidationError(
            f'<group> "{label}" contains no <feature> entries. A group '
            "with no features is meaningless — inline the features directly "
            "under <features> or add features to the group."
        )

    features: list[Feature] = []
    for offset, feature_node in enumerate(feature_children):
        features.append(
            _validate_feature(
                feature_node,
                base_index + offset,
                group_label=label,
            )
        )
    return label, features


def _validate_feature(node: TagNode, index: int, *, group_label: str | None) -> Feature:
    """Validate a single ``<feature>`` entry and return its ``Feature``.

    ``index`` is the flat position of this feature across the
    whole ``<features>`` block — used in error messages to help
    the LLM locate the problem. ``group_label`` is propagated from
    the enclosing ``<group>``, or ``None`` when the feature sits
    directly under ``<features>``.
    """
    pos = f"<feature> at position {index}"

    # Reject unknown children inside a feature. <implicit/> is a
    # self-closing marker with no text or children of its own.
    for child in node.children:
        if child.tag not in _FEATURE_ALLOWED_CHILDREN:
            raise ValidationError(
                f"{pos} contains an unexpected child <{child.tag}>. "
                "Only <name>, <intent>, and an optional <implicit/> marker "
                "are allowed inside a <feature>."
            )

    name_children = node.find_all("name")
    if len(name_children) == 0:
        raise ValidationError(
            f"{pos} is missing a <name> child. Every feature must have exactly one <name>."
        )
    if len(name_children) > 1:
        raise ValidationError(
            f"{pos} has {len(name_children)} <name> children; exactly one is required."
        )

    intent_children = node.find_all("intent")
    if len(intent_children) == 0:
        raise ValidationError(
            f"{pos} is missing an <intent> child. Every feature must have exactly one <intent>."
        )
    if len(intent_children) > 1:
        raise ValidationError(
            f"{pos} has {len(intent_children)} <intent> children; exactly one is required."
        )

    implicit_children = node.find_all("implicit")
    if len(implicit_children) > 1:
        raise ValidationError(
            f"{pos} has {len(implicit_children)} <implicit/> markers; at most one is allowed."
        )
    is_implicit = len(implicit_children) == 1

    name_text = name_children[0].text
    if not name_text:
        raise ValidationError(
            f"{pos} has an empty <name>. The feature name must be "
            "a short identifier, typically 2–5 words in title case."
        )

    intent_text = intent_children[0].text
    if not intent_text:
        raise ValidationError(
            f"{pos} has an empty <intent>. The feature intent must "
            "be a short paragraph describing what the feature does."
        )

    return Feature(
        name=name_text,
        intent=intent_text,
        group_label=group_label,
        is_implicit=is_implicit,
    )


# ── Requirements (Phase 3: reqs → resp_*) ────────────────────────────


@dataclass(frozen=True)
class Responsibility:
    """A single validated responsibility from a ``<requirements>`` block.

    ``name`` is the short identifier (2–5 words, title case
    expected). ``intent`` is the paragraph-length description of
    the responsibility's role and scope. ``covers`` is the set of
    feature IDs this responsibility serves — at least one, drawn
    from a closed set of known features (the validator checks
    membership against a caller-supplied allowlist). All strings
    are non-empty and already whitespace-stripped at their outer
    edges.
    """

    name: str
    intent: str
    covers: tuple[str, ...]


_REQUIREMENTS_ALLOWED_CHILDREN = {"responsibility"}
_RESPONSIBILITY_ALLOWED_CHILDREN = {"name", "intent", "covers"}
_COVERS_ALLOWED_CHILDREN = {"feat"}


def validate_requirements(tree: TagNode, *, known_feature_ids: set[str]) -> list[Responsibility]:
    """Validate a parsed ``<requirements>`` tree and return its entries.

    Shape:

    * ``tree.tag`` must be exactly ``"requirements"``.
    * ``<requirements>`` contains one or more ``<responsibility>``
      entries. No other tags at this level.
    * Each ``<responsibility>`` contains exactly one ``<name>``,
      exactly one ``<intent>``, and exactly one ``<covers>``. No
      other tags inside.
    * Each ``<covers>`` contains one or more ``<feat id="..."/>``
      children. The ``id`` must match a known feature from
      ``known_feature_ids``. Unknown / missing IDs are parse
      errors that feed the retry loop.
    * **Coverage requirement:** every feature in
      ``known_feature_ids`` must appear in at least one
      ``<covers>`` block across the full validated set. Missing
      coverage is a parse error.

    Parallel shape to :func:`validate_features`: same general
    layout (one root, a flat list of structured children, each
    child has a name + intent), different tag vocabulary. The
    ``<covers>`` requirement is what distinguishes it from its
    feature-expansion cousin: the many-to-many edges emitted on
    approval come from parsing these IDs, so ID validity is
    enforced here rather than at mint time.
    """
    if tree.tag != "requirements":
        raise ValidationError(
            f"Expected root tag <requirements>, got <{tree.tag}>. "
            "Wrap the responsibility list in a single <requirements>...</requirements> block."
        )

    for child in tree.children:
        if child.tag not in _REQUIREMENTS_ALLOWED_CHILDREN:
            raise ValidationError(
                f"<requirements> contains an unexpected child <{child.tag}>. "
                "Only <responsibility> entries are allowed at this level."
            )

    result: list[Responsibility] = []
    for index, child in enumerate(tree.children):
        result.append(_validate_responsibility(child, index, known_feature_ids=known_feature_ids))

    if not result:
        raise ValidationError(
            "<requirements> block contains no <responsibility> entries. "
            "Every project must have at least one top-level responsibility."
        )

    # Coverage check: every known feature must be covered by at
    # least one responsibility. Collect all the covered IDs across
    # the full output and diff against the known set.
    covered: set[str] = set()
    for resp in result:
        covered.update(resp.covers)
    missing = sorted(known_feature_ids - covered)
    if missing:
        raise ValidationError(
            "<requirements> block does not cover every feature. "
            f"The following feature IDs are not listed in any <covers> block: "
            f"{', '.join(missing)}. Every feature must be implicated by "
            "at least one responsibility."
        )

    return result


def _validate_responsibility(
    node: TagNode, index: int, *, known_feature_ids: set[str]
) -> Responsibility:
    """Validate a single ``<responsibility>`` entry."""
    pos = f"<responsibility> at position {index}"

    for child in node.children:
        if child.tag not in _RESPONSIBILITY_ALLOWED_CHILDREN:
            raise ValidationError(
                f"{pos} contains an unexpected child <{child.tag}>. "
                "Only <name>, <intent>, and <covers> are allowed inside a <responsibility>."
            )

    name_children = node.find_all("name")
    if len(name_children) == 0:
        raise ValidationError(
            f"{pos} is missing a <name> child. Every responsibility must have exactly one <name>."
        )
    if len(name_children) > 1:
        raise ValidationError(
            f"{pos} has {len(name_children)} <name> children; exactly one is required."
        )

    intent_children = node.find_all("intent")
    if len(intent_children) == 0:
        raise ValidationError(
            f"{pos} is missing an <intent> child. Every responsibility "
            "must have exactly one <intent>."
        )
    if len(intent_children) > 1:
        raise ValidationError(
            f"{pos} has {len(intent_children)} <intent> children; exactly one is required."
        )

    covers_children = node.find_all("covers")
    if len(covers_children) == 0:
        raise ValidationError(
            f"{pos} is missing a <covers> child. Every responsibility "
            "must have exactly one <covers> block listing at least one "
            '<feat id="feat_..."/> child identifying the feature IDs '
            "it serves."
        )
    if len(covers_children) > 1:
        raise ValidationError(
            f"{pos} has {len(covers_children)} <covers> children; exactly one is required."
        )

    name_text = name_children[0].text
    if not name_text:
        raise ValidationError(
            f"{pos} has an empty <name>. The responsibility name "
            "must be a short identifier, typically 2–5 words in title case."
        )

    intent_text = intent_children[0].text
    if not intent_text:
        raise ValidationError(
            f"{pos} has an empty <intent>. The responsibility intent "
            "must be a short paragraph describing the role and scope."
        )

    covers = _validate_covers(covers_children[0], pos, known_feature_ids=known_feature_ids)

    return Responsibility(name=name_text, intent=intent_text, covers=covers)


def _validate_covers(
    node: TagNode, parent_pos: str, *, known_feature_ids: set[str]
) -> tuple[str, ...]:
    """Validate a single ``<covers>`` block and return its feature IDs.

    ``parent_pos`` is the position marker of the enclosing
    responsibility — used in error messages so the retry prompt
    can direct the LLM to the right responsibility.
    """
    # Reject unknown children inside <covers>.
    for child in node.children:
        if child.tag not in _COVERS_ALLOWED_CHILDREN:
            raise ValidationError(
                f"{parent_pos} has a <covers> block containing an unexpected "
                f'child <{child.tag}>. Only <feat id="feat_..."/> entries '
                "are allowed inside <covers>."
            )

    feat_nodes = node.find_all("feat")
    if not feat_nodes:
        raise ValidationError(
            f"{parent_pos} has an empty <covers> block. Every responsibility "
            "must cover at least one feature — list the feature IDs via "
            '<feat id="feat_..."/> children.'
        )

    ids: list[str] = []
    seen: set[str] = set()
    for i, feat_node in enumerate(feat_nodes):
        fid = feat_node.attrs.get("id", "").strip()
        if not fid:
            raise ValidationError(
                f"{parent_pos} has a <feat> entry at <covers> position {i} "
                "with no id attribute. Every <feat> must carry an "
                'id="feat_..." attribute referencing a known feature.'
            )
        if fid in seen:
            raise ValidationError(
                f"{parent_pos} has a <feat> entry at <covers> position {i} "
                f"listing duplicate feature id {fid!r}. Each feature id may "
                "appear at most once per <covers> block."
            )
        seen.add(fid)
        if fid not in known_feature_ids:
            raise ValidationError(
                f"{parent_pos} has a <feat> entry at <covers> position {i} "
                f"referencing unknown feature id {fid!r}. Valid feature "
                f"IDs for this project: {', '.join(sorted(known_feature_ids))}. "
                "Only reference IDs from the feature list provided in the prompt."
            )
        ids.append(fid)

    return tuple(ids)


# ── System architecture (Phase 3 stage 2: sysarch → comp_*/policy_*/edges) ──


@dataclass(frozen=True)
class Component:
    """A single validated component entry from a ``<sysarch>`` block.

    ``alias`` is the local reference used inside this sysarch
    document's ``<dependencies>`` and ``<domain-parent>`` edges.
    It is *not* a node ID — the mint handler resolves aliases to
    real ``comp_*`` IDs at approval time. ``resp_refs`` carries
    the top-level ``resp_*`` IDs assigned to this component; the
    1:1 resp→comp invariant is enforced at the ``<sysarch>`` root
    level so every known top-level resp lands in exactly one
    component's list.
    """

    alias: str
    name: str
    kind: str  # "domain" or "presentational"
    role: str
    api_intent: str
    resp_refs: tuple[str, ...]
    is_foundation: bool


@dataclass(frozen=True)
class Policy:
    """A single validated policy entry from a ``<policies>`` block.

    ``required_resp_id`` is the top-level ``resp_*`` ID that must
    be fulfilled at every site the ``trigger`` phrase matches.
    The mint handler stores the whole dataclass as an XML blob
    on the minted ``policy_*`` node's ``content`` column; comparch
    (Phase 4) re-parses it when deciding which components the
    policy applies to.
    """

    name: str
    trigger: str
    required_resp_id: str
    rationale: str


@dataclass(frozen=True)
class DepEdge:
    """A ``<dep from=... to=.../>`` entry inside ``<dependencies>``.

    Both endpoints are component aliases within this sysarch doc.
    The mint handler translates them to real ``comp_*`` IDs when
    emitting ``EdgeCreated`` events.
    """

    from_alias: str
    to_alias: str


@dataclass(frozen=True)
class DomainParentEdge:
    """A ``<parent from=... to=.../>`` entry inside ``<domain-parent>``.

    ``from_alias`` is a presentational component; ``to_alias`` is
    a domain component. Both are local aliases that the mint
    handler resolves.
    """

    from_alias: str
    to_alias: str


@dataclass(frozen=True)
class SysarchDoc:
    """The full validated sysarch output as structured data.

    Mint handler consumes this rather than re-walking the parsed
    ``TagNode`` tree, which keeps alias-based concerns in the
    validator and ID-based concerns in the mint handler.
    """

    techspec: str
    components: tuple[Component, ...]
    policies: tuple[Policy, ...]
    deps: tuple[DepEdge, ...]
    domain_parents: tuple[DomainParentEdge, ...]


# Alias syntax: lowercase letter, then up to 31 lowercase
# alphanumerics or underscores. Deterministic, fits in a path
# segment, easy for the LLM to honour.
_ALIAS_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")

_SYSARCH_ALLOWED_CHILDREN = {
    "techspec",
    "components",
    "policies",
    "dependencies",
    "domain-parent",
}
_SYSARCH_REQUIRED_ORDER = (
    "techspec",
    "components",
    "policies",
    "dependencies",
    "domain-parent",
)
_COMPONENT_ALLOWED_CHILDREN = {
    "name",
    "kind",
    "role",
    "api-intent",
    "responsibilities",
    "foundation",
}
_RESPONSIBILITIES_ALLOWED_CHILDREN = {"resp"}
_POLICIES_ALLOWED_CHILDREN = {"policy"}
_POLICY_ALLOWED_CHILDREN = {"name", "trigger", "required", "rationale"}
_DEPENDENCIES_ALLOWED_CHILDREN = {"dep"}
_DOMAIN_PARENT_ALLOWED_CHILDREN = {"parent"}
_COMPONENT_KIND_VALUES = {"domain", "presentational"}


def validate_sysarch(
    tree: TagNode,
    *,
    known_top_level_resp_ids: set[str],
) -> SysarchDoc:
    """Validate a parsed ``<sysarch>`` tree and return a SysarchDoc.

    Enforces the full shape described in
    :mod:`backend.graph.prompts.sysarch`: single root, five
    sections in order, alias syntax + uniqueness, component field
    completeness, exactly-one-foundation, exactly-one-assignment
    per top-level resp, known resp IDs in ``<responsibilities>``
    and policy ``<required>``, policy sub-grammar, dep acyclicity,
    domain-parent direction.

    ``known_top_level_resp_ids`` is the set of all top-level
    ``resp_*`` IDs minted by ``reqs_*`` approval — collected from
    the DB before the retry loop starts. The validator cross-
    checks every resp reference against this set and enforces
    complete coverage.
    """
    if tree.tag != "sysarch":
        raise ValidationError(
            f"Expected root tag <sysarch>, got <{tree.tag}>. "
            "Wrap the system architecture output in a single "
            "<sysarch>...</sysarch> block."
        )

    # Section order enforcement — each expected section must
    # appear in the right position. Missing or reordered sections
    # get a specific error so the LLM can fix on retry.
    section_map: dict[str, TagNode] = {}
    for child in tree.children:
        if child.tag not in _SYSARCH_ALLOWED_CHILDREN:
            raise ValidationError(
                f"<sysarch> contains an unexpected child <{child.tag}>. "
                f"Allowed children are: {sorted(_SYSARCH_ALLOWED_CHILDREN)}."
            )
        if child.tag in section_map:
            raise ValidationError(
                f"<sysarch> contains more than one <{child.tag}> section; "
                "exactly one of each section is required."
            )
        section_map[child.tag] = child

    actual_order = [c.tag for c in tree.children if c.tag in _SYSARCH_REQUIRED_ORDER]
    if actual_order != list(_SYSARCH_REQUIRED_ORDER):
        raise ValidationError(
            f"<sysarch> sections are not in the required order. "
            f"Expected: {list(_SYSARCH_REQUIRED_ORDER)}. "
            f"Got: {actual_order}. "
            "Reorder the children of <sysarch> to match the required sequence."
        )

    # All five sections present — validate each in turn.
    techspec = _validate_sysarch_techspec(section_map["techspec"])
    components = _validate_sysarch_components(
        section_map["components"], known_top_level_resp_ids=known_top_level_resp_ids
    )
    policies = _validate_sysarch_policies(
        section_map["policies"], known_top_level_resp_ids=known_top_level_resp_ids
    )

    alias_set = {c.alias for c in components}
    alias_kind_map = {c.alias: c.kind for c in components}

    deps = _validate_sysarch_dependencies(section_map["dependencies"], alias_set)
    domain_parents = _validate_sysarch_domain_parent(section_map["domain-parent"], alias_kind_map)

    # Dep cycle detection on the alias graph before returning.
    _detect_dep_cycles(deps, alias_set)

    return SysarchDoc(
        techspec=techspec,
        components=components,
        policies=policies,
        deps=deps,
        domain_parents=domain_parents,
    )


def _validate_sysarch_techspec(node: TagNode) -> str:
    """Extract the non-empty text of ``<techspec>``."""
    if node.children:
        # Any nested tags inside techspec are unexpected for MVP.
        # We still accept them with a warning for now — the LLM's
        # intent is clear — but reject if there's no direct text.
        raise ValidationError(
            "<techspec> must contain plain text only, no nested tags. "
            f"Found children: {[c.tag for c in node.children]}."
        )
    text = node.text.strip() if node.text else ""
    if not text:
        raise ValidationError(
            "<techspec> is empty. The system techspec must be a paragraph "
            "describing project-level technology and architecture choices."
        )
    return text


def _validate_sysarch_components(
    node: TagNode, *, known_top_level_resp_ids: set[str]
) -> tuple[Component, ...]:
    """Validate ``<components>`` and return a tuple of ``Component``."""
    # Allow only <component> children at this level.
    for child in node.children:
        if child.tag != "component":
            raise ValidationError(
                f"<components> contains an unexpected child <{child.tag}>. "
                "Only <component> entries are allowed at this level."
            )
    component_nodes = [c for c in node.children if c.tag == "component"]
    if not component_nodes:
        raise ValidationError(
            "<components> contains no <component> entries. "
            "Every project needs at least one top-level component."
        )

    components: list[Component] = []
    seen_aliases: set[str] = set()
    assigned_resp_ids: dict[str, str] = {}  # resp_id → alias that assigned it
    foundation_aliases: list[str] = []

    for index, cnode in enumerate(component_nodes):
        comp = _validate_component(
            cnode,
            index=index,
            known_top_level_resp_ids=known_top_level_resp_ids,
        )
        if comp.alias in seen_aliases:
            raise ValidationError(
                f"<components> contains two <component> entries with the same "
                f"alias {comp.alias!r}. Aliases must be unique within a sysarch "
                "doc. Rename one of them."
            )
        seen_aliases.add(comp.alias)
        if comp.is_foundation:
            foundation_aliases.append(comp.alias)
        for rid in comp.resp_refs:
            if rid in assigned_resp_ids:
                raise ValidationError(
                    f"Responsibility {rid!r} is assigned to both "
                    f"{assigned_resp_ids[rid]!r} and {comp.alias!r}. Each "
                    "top-level responsibility must be assigned to exactly one "
                    "component."
                )
            assigned_resp_ids[rid] = comp.alias
        components.append(comp)

    # Foundation requirement: exactly one component must carry the marker.
    if len(foundation_aliases) == 0:
        raise ValidationError(
            "<components> has no foundation component. Exactly one "
            "component must carry a self-closing <foundation/> marker "
            "child — it owns the project's root folder files (build "
            "config, package init, shared utilities). See the "
            "architecture doc §Foundation components."
        )
    if len(foundation_aliases) > 1:
        raise ValidationError(
            f"<components> has {len(foundation_aliases)} foundation components "
            f"({', '.join(sorted(foundation_aliases))}). Exactly one foundation "
            "component is required; promote the others to regular domain "
            "components or merge them into the single foundation."
        )

    # Coverage check: every known top-level resp must be assigned.
    missing = sorted(known_top_level_resp_ids - set(assigned_resp_ids.keys()))
    if missing:
        raise ValidationError(
            "<sysarch> does not assign every top-level responsibility to a "
            f"component. Missing: {', '.join(missing)}. Every responsibility "
            "in the input list must appear in exactly one component's "
            "<responsibilities> block."
        )

    return tuple(components)


def _validate_component(
    node: TagNode, *, index: int, known_top_level_resp_ids: set[str]
) -> Component:
    """Validate a single ``<component>`` entry."""
    pos = f"<component> at position {index}"

    alias = node.attrs.get("alias", "").strip()
    if not alias:
        raise ValidationError(
            f"{pos} is missing the alias attribute. Every component must "
            'carry alias="..." (lowercase snake_case, 1-32 chars, starts '
            "with a letter)."
        )
    if not _ALIAS_RE.match(alias):
        raise ValidationError(
            f"{pos} has invalid alias {alias!r}. Aliases must match "
            "^[a-z][a-z0-9_]{0,31}$ — lowercase letter first, then "
            "lowercase alphanumerics or underscores, 1-32 characters."
        )

    # Check children allowlist.
    for child in node.children:
        if child.tag not in _COMPONENT_ALLOWED_CHILDREN:
            raise ValidationError(
                f"{pos} (alias={alias!r}) contains an unexpected child "
                f"<{child.tag}>. Allowed children are: "
                f"{sorted(_COMPONENT_ALLOWED_CHILDREN)}."
            )

    def _require_one(tag: str) -> TagNode:
        matching = node.find_all(tag)
        if len(matching) == 0:
            raise ValidationError(
                f"{pos} (alias={alias!r}) is missing a <{tag}> child. "
                "Every component must have exactly one."
            )
        if len(matching) > 1:
            raise ValidationError(
                f"{pos} (alias={alias!r}) has {len(matching)} <{tag}> "
                "children; exactly one is required."
            )
        return matching[0]

    name_node = _require_one("name")
    kind_node = _require_one("kind")
    role_node = _require_one("role")
    api_intent_node = _require_one("api-intent")
    responsibilities_node = _require_one("responsibilities")

    name = (name_node.text or "").strip()
    if not name:
        raise ValidationError(
            f"{pos} (alias={alias!r}) has an empty <name>. The display "
            "name must be a short title-case identifier."
        )

    kind = (kind_node.text or "").strip()
    if kind not in _COMPONENT_KIND_VALUES:
        raise ValidationError(
            f"{pos} (alias={alias!r}) has invalid <kind> {kind!r}. "
            "Must be 'domain' or 'presentational'."
        )

    role = (role_node.text or "").strip()
    if not role:
        raise ValidationError(
            f"{pos} (alias={alias!r}) has an empty <role>. Every component "
            "must have a role paragraph describing what it does."
        )

    api_intent = (api_intent_node.text or "").strip()
    if not api_intent:
        raise ValidationError(
            f"{pos} (alias={alias!r}) has an empty <api-intent>. Every "
            "component must describe the shape of its intended API."
        )

    # Validate the <responsibilities> block.
    for rchild in responsibilities_node.children:
        if rchild.tag not in _RESPONSIBILITIES_ALLOWED_CHILDREN:
            raise ValidationError(
                f"{pos} (alias={alias!r}) has a <responsibilities> block "
                f"containing an unexpected child <{rchild.tag}>. Only "
                '<resp id="resp_..."/> entries are allowed.'
            )
    resp_nodes = responsibilities_node.find_all("resp")
    if not resp_nodes:
        raise ValidationError(
            f"{pos} (alias={alias!r}) has an empty <responsibilities> block. "
            "Every component must be assigned at least one top-level "
            'responsibility via a <resp id="resp_..."/> child.'
        )
    resp_refs: list[str] = []
    seen_refs: set[str] = set()
    for ri, rnode in enumerate(resp_nodes):
        rid = rnode.attrs.get("id", "").strip()
        if not rid:
            raise ValidationError(
                f"{pos} (alias={alias!r}) has a <resp> entry at position {ri} "
                "with no id attribute. Every <resp> must carry an "
                'id="resp_..." attribute referencing a known responsibility.'
            )
        if rid in seen_refs:
            raise ValidationError(
                f"{pos} (alias={alias!r}) has duplicate <resp> reference "
                f"{rid!r} in its <responsibilities> block. Each responsibility "
                "may be listed at most once per component."
            )
        seen_refs.add(rid)
        if rid not in known_top_level_resp_ids:
            raise ValidationError(
                f"{pos} (alias={alias!r}) references unknown top-level "
                f"responsibility {rid!r}. Valid IDs: "
                f"{', '.join(sorted(known_top_level_resp_ids))}."
            )
        resp_refs.append(rid)

    is_foundation = len(node.find_all("foundation")) > 0

    return Component(
        alias=alias,
        name=name,
        kind=kind,
        role=role,
        api_intent=api_intent,
        resp_refs=tuple(resp_refs),
        is_foundation=is_foundation,
    )


def validate_policy_blob(text: str, *, known_resp_ids: set[str]) -> Policy:
    """Parse and validate a single ``<policy>`` XML blob.

    Standalone helper so comparch (Phase 4) and any other consumer
    can parse a stored ``policy_*.content`` back into a ``Policy``
    dataclass without reinventing the sub-grammar. The sysarch
    validator calls this inline for each policy in the
    ``<policies>`` block.

    ``known_resp_ids`` is the set of responsibility IDs the policy
    is allowed to reference via its ``<required>`` field.
    """
    tree = extract_tag_tree(text, "policy")
    return _validate_policy(tree, index=0, known_resp_ids=known_resp_ids)


def _validate_sysarch_policies(
    node: TagNode, *, known_top_level_resp_ids: set[str]
) -> tuple[Policy, ...]:
    """Validate ``<policies>`` and return a tuple of ``Policy``."""
    for child in node.children:
        if child.tag not in _POLICIES_ALLOWED_CHILDREN:
            raise ValidationError(
                f"<policies> contains an unexpected child <{child.tag}>. "
                "Only <policy> entries are allowed."
            )
    policy_nodes = node.find_all("policy")
    policies: list[Policy] = []
    for index, pnode in enumerate(policy_nodes):
        policies.append(
            _validate_policy(pnode, index=index, known_resp_ids=known_top_level_resp_ids)
        )
    return tuple(policies)


def _validate_policy(node: TagNode, *, index: int, known_resp_ids: set[str]) -> Policy:
    """Validate a single ``<policy>`` entry."""
    pos = f"<policy> at position {index}"
    for child in node.children:
        if child.tag not in _POLICY_ALLOWED_CHILDREN:
            raise ValidationError(
                f"{pos} contains an unexpected child <{child.tag}>. "
                "Only <name>, <trigger>, <required>, and <rationale> are allowed."
            )

    def _require_one(tag: str) -> TagNode:
        matching = node.find_all(tag)
        if len(matching) == 0:
            raise ValidationError(
                f"{pos} is missing a <{tag}> child. Every policy must have exactly one."
            )
        if len(matching) > 1:
            raise ValidationError(
                f"{pos} has {len(matching)} <{tag}> children; exactly one is required."
            )
        return matching[0]

    name = (_require_one("name").text or "").strip()
    trigger = (_require_one("trigger").text or "").strip()
    required = (_require_one("required").text or "").strip()
    rationale = (_require_one("rationale").text or "").strip()

    if not name:
        raise ValidationError(f"{pos} has an empty <name>.")
    if not trigger:
        raise ValidationError(
            f"{pos} has an empty <trigger>. The trigger is the semantic "
            "phrase identifying where the policy applies (e.g. "
            "'any LLM call', 'any domain write')."
        )
    if not rationale:
        raise ValidationError(
            f"{pos} has an empty <rationale>. The rationale paragraph "
            "explains why the policy exists and carries weight when the "
            "application pass decides which components it applies to."
        )
    if not required:
        raise ValidationError(
            f"{pos} has an empty <required>. It must contain a single "
            "resp_* ID referencing the responsibility that must be "
            "fulfilled at every trigger site."
        )
    if required not in known_resp_ids:
        raise ValidationError(
            f"{pos} has <required>{required}</required> referencing an "
            f"unknown responsibility. Valid IDs: "
            f"{', '.join(sorted(known_resp_ids))}."
        )

    return Policy(name=name, trigger=trigger, required_resp_id=required, rationale=rationale)


def _validate_sysarch_dependencies(node: TagNode, alias_set: set[str]) -> tuple[DepEdge, ...]:
    """Validate ``<dependencies>`` and return a tuple of ``DepEdge``."""
    for child in node.children:
        if child.tag not in _DEPENDENCIES_ALLOWED_CHILDREN:
            raise ValidationError(
                f"<dependencies> contains an unexpected child <{child.tag}>. "
                "Only <dep> entries are allowed."
            )
    dep_nodes = node.find_all("dep")
    deps: list[DepEdge] = []
    for index, dnode in enumerate(dep_nodes):
        from_alias = dnode.attrs.get("from", "").strip()
        to_alias = dnode.attrs.get("to", "").strip()
        if not from_alias or not to_alias:
            raise ValidationError(
                f"<dep> at position {index} is missing a from or to attribute. "
                'Every <dep> must carry from="..." to="..." with known aliases.'
            )
        if from_alias not in alias_set:
            raise ValidationError(
                f"<dep> at position {index} has unknown from alias {from_alias!r}. "
                f"Valid aliases: {sorted(alias_set)}."
            )
        if to_alias not in alias_set:
            raise ValidationError(
                f"<dep> at position {index} has unknown to alias {to_alias!r}. "
                f"Valid aliases: {sorted(alias_set)}."
            )
        if from_alias == to_alias:
            raise ValidationError(
                f"<dep> at position {index} has from == to (both {from_alias!r}). "
                "A component cannot depend on itself."
            )
        deps.append(DepEdge(from_alias=from_alias, to_alias=to_alias))
    return tuple(deps)


def _validate_sysarch_domain_parent(
    node: TagNode, alias_kind_map: dict[str, str]
) -> tuple[DomainParentEdge, ...]:
    """Validate ``<domain-parent>`` and return a tuple of ``DomainParentEdge``."""
    for child in node.children:
        if child.tag not in _DOMAIN_PARENT_ALLOWED_CHILDREN:
            raise ValidationError(
                f"<domain-parent> contains an unexpected child <{child.tag}>. "
                "Only <parent> entries are allowed."
            )
    parent_nodes = node.find_all("parent")
    edges: list[DomainParentEdge] = []
    for index, pnode in enumerate(parent_nodes):
        from_alias = pnode.attrs.get("from", "").strip()
        to_alias = pnode.attrs.get("to", "").strip()
        if not from_alias or not to_alias:
            raise ValidationError(
                f"<parent> at position {index} is missing a from or to "
                'attribute. Every <parent> must carry from="..." to="..." '
                "with known aliases."
            )
        if from_alias not in alias_kind_map:
            raise ValidationError(
                f"<parent> at position {index} has unknown from alias {from_alias!r}."
            )
        if to_alias not in alias_kind_map:
            raise ValidationError(
                f"<parent> at position {index} has unknown to alias {to_alias!r}."
            )
        if alias_kind_map[from_alias] != "presentational":
            raise ValidationError(
                f"<parent> at position {index}: from alias {from_alias!r} must "
                f"be a presentational component (kind={alias_kind_map[from_alias]!r})."
            )
        if alias_kind_map[to_alias] != "domain":
            raise ValidationError(
                f"<parent> at position {index}: to alias {to_alias!r} must "
                f"be a domain component (kind={alias_kind_map[to_alias]!r})."
            )
        edges.append(DomainParentEdge(from_alias=from_alias, to_alias=to_alias))
    return tuple(edges)


def _detect_dep_cycles(deps: tuple[DepEdge, ...], alias_set: set[str]) -> None:
    """DFS on the dependency alias graph; raise on the first cycle found.

    Cycle paths are reported in alias form (the LLM authored the
    aliases, so it can fix them). Deterministic order — aliases
    are sorted for reproducible retry prompts.
    """
    # Build adjacency list in deterministic order.
    adj: dict[str, list[str]] = {a: [] for a in sorted(alias_set)}
    for d in deps:
        adj[d.from_alias].append(d.to_alias)
    for a in adj:
        adj[a].sort()

    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = {a: WHITE for a in adj}
    stack: list[str] = []

    def _dfs(node: str) -> None:
        color[node] = GRAY
        stack.append(node)
        for nxt in adj[node]:
            if color[nxt] == GRAY:
                # Cycle: nxt is the closing point; find it in the stack.
                start = stack.index(nxt)
                cycle = stack[start:] + [nxt]
                raise ValidationError(
                    f"Dependency cycle detected: {' → '.join(cycle)}. "
                    "Remove one of these <dep> edges or restructure the "
                    "components so the graph is a DAG. Foundation should "
                    "typically be a sink (everything depends on it, it "
                    "depends on nothing)."
                )
            if color[nxt] == WHITE:
                _dfs(nxt)
        color[node] = BLACK
        stack.pop()

    for a in adj:
        if color[a] == WHITE:
            _dfs(a)
