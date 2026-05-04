"""Review prompt for the subcomparch tier."""

from __future__ import annotations

from backend.graph.prompts.review._shared import (
    render_review_system_prompt,
    review_task_footer,
)
from backend.graph.review_context.subcomparch import SubcomparchContext

_HANDLES_INTRO = """\
Subcomparch is the leaf articulation — no more tiers will \
correct it. Impl reads the public / private surface split \
directly and writes code against those signatures. Vagueness \
here doesn't get smoothed out by another compression pass: \
every method-name-without-a-signature becomes a contract impl \
has to invent, and every silent failure-mode-without-an-error-\
variant becomes either a caller surprise or a fabricated \
exception type.

Two cross-cutting consistency checks are load-bearing here. \
First: the four sections (techspec / pubapi / privapi / deps) \
must agree internally — every techspec claim must surface in \
pubapi or privapi, every surface entry must be grounded in \
techspec or the parent's ``<owns>`` slice. Second: this sub's \
techspec and pubapi must agree with the parent comparch's \
techspec (tech-stack, sync/async, error style) and with the \
parent's failure-surface entries that touch resps this sub \
owns.
"""

_HANDLES = """\
- ``<technical-specification>`` **narrows** the parent comparch \
techspec to this sub's slice — names the specific tables, \
async patterns, validation surfaces, or persistence \
mechanisms this sub owns *within* the parent's stack. Flag \
wholesale copying of the parent techspec; flag category-speak \
("handles X", "manages Y", "contains the helpers for Z") \
that doesn't name distinctive specifics.
- ``<public-surface>`` shows full **signatures**, not method \
names. For every callable: parameter types (or schema-shape \
for events), return type including the error variant when the \
call can fail, sync/async marker, and named side effects. \
Flag method-names-without-signatures, opaque error atoms \
where the techspec describes a discriminating failure mode, \
and entries that re-export internals.
- ``<private-surface>`` names internal types and data \
structures impl will define, not just helper functions. If \
the techspec mentions a buffer, queue, cache entry, or other \
named structure, the privapi should declare its shape. Flag \
helpers-only privapi when the techspec implies named types, \
and flag privapi entries that are actually re-exported public \
API.
- ``<dependencies>`` targets are real ``comp_*`` IDs only — \
either same-parent sibling subs or parent-sibling top-level \
components. The validator allowlists by ID against the \
context bundle and rejects any ``to`` attribute without a \
``comp_`` prefix; trust those guarantees and don't spend \
review budget there.
- **Surface closure — both directions.** *Pass A:* for every \
behavior, side effect, persisted value, emitted event, or \
return shape the techspec describes, identify the pubapi \
entry (callable from outside) or privapi entry (callable from \
this sub's impl) that mounts it. A techspec sentence with no \
matching surface entry is half-done. *Pass B:* for every \
pubapi/privapi entry, the techspec or this sub's owns-slice \
should describe why it exists. Filler entries without an \
anchor inflate the contract impl has to honor.
- **Failure-mode observability through pubapi.** Subcomparch \
has no separate failure-surface section, so failure modes \
thread through pubapi. For every failure or partial-success \
scenario the techspec describes — and for every parent-\
comparch failure-surface entry that touches a resp this sub \
owns — confirm a pubapi entry exposes it: an error variant in \
a tagged-tuple return, a typed exception, an event a caller \
can subscribe to, a status field they can inspect. The most \
common shape of this defect: techspec names partial-failure \
or rate-limit rejection, but the corresponding pubapi \
function returns a bare success type or an opaque error atom \
that strips the discriminating detail. Either expand the \
return shape or strike the failure-mode from the techspec; \
silent failures with no public observability are worse than \
admitting the limitation.
- **Dependency grounding.** For each ``<dep to="comp_..."/>``, \
confirm the techspec or a pubapi/privapi entry describes how \
this sub actually uses the target — what data flows, which \
sibling pubapi gets called, what event gets subscribed to. \
Symmetrically, scan techspec/pubapi prose for any cross-comp \
call site implied by the text and confirm a corresponding \
``<dep>`` is declared. Ungrounded ``<dep>`` is spurious or \
evidence of missing prose; implicit cross-comp references \
without a declared dep mislead impl about allowed imports.
- **Co-owner seam visibility.** When the parent comparch's \
``<owns>`` shows this sub co-owning a resp with a sibling \
(UI flow split or read/write path split), the pubapi must \
make this sub's slice unambiguous on its own. Method names + \
return shapes that could plausibly belong to either co-owner \
are the defect; flag any pubapi where the seam isn't visible \
without cross-referencing the sibling's pubapi.
- **Cross-section consistency is the highest-yield check.** \
Read the four sections as one document and flag direct \
contradictions: a techspec claim ("never returns partial \
results") versus a pubapi return type that includes a \
``Partial`` variant; an async-only techspec versus sync \
signatures (or vice versa); a privapi helper that operates on \
a type the privapi never declares; a pubapi event the \
techspec never describes emitting. Be specific about which \
two sections disagree and what the artifact would need to do \
to reconcile.

Things you do **not** need to flag (the parser already \
rejects them, so the artifact you're seeing has already \
passed these checks): missing or out-of-order sections; \
``<policies>``, ``<subcomponents>``, or ``<sub-dependencies>`` \
sections (subcomparch can't have any of them); ``<dep>`` \
targets that are not real ``comp_*`` IDs from the allowed \
list; duplicate ``<dep>`` entries; self-deps. Spending review \
budget on these is wasted effort.
"""

_ARCHITECTURE_INTRO = """\
Tech-stack drift between this sub and its parent comparch is \
the highest-impact architectural defect at the leaf tier — \
it propagates straight into impl. Watch for sync/async \
mismatch, error-style mismatch (Result vs. exceptions), \
mutable/immutable data-shape mismatch, and persistence-\
pattern drift. Also watch for over-bundled scope (one sub \
trying to own concerns that should be split across siblings) \
and pubapi bloat (entries that don't actually need to cross \
the sibling boundary).
"""

_ARCHITECTURE = """\
- Is this sub's tech choice consistent with the parent \
comparch's techspec? Flag drift (e.g. parent says async, \
sub's pubapi is sync-only; parent says ``Result[T, ErrKind]``, \
sub raises typed exceptions instead).
- Is the cut of pubapi vs. privapi principled, or is the \
public surface bloated with internals that no sibling \
actually needs? Flag pubapi entries that could be private \
without breaking sibling consumers.
- Is the sub's scope (its role + what it actually builds via \
pubapi + privapi) coherent? Flag bundles of unrelated \
concerns inside one sub, and flag pubapi entries that don't \
map to any responsibility this sub claims.
- Are the declared ``<dependencies>`` minimal — only the \
siblings or parent-siblings this sub actually calls — or is \
this sub depending on more comps than its prose justifies?
"""


def render_system_prompt() -> str:
    return render_review_system_prompt(
        artifact_label="``<subcomparch>`` block",
        scope_label="this subcomponent",
        handles_criteria=_HANDLES,
        architecture_criteria=_ARCHITECTURE,
        handles_intro=_HANDLES_INTRO,
        architecture_intro=_ARCHITECTURE_INTRO,
    )


def render_user_prompt(context: SubcomparchContext, generated_output: str) -> str:
    parts: list[str] = []
    parts.append(f"# Subcomponent under review: {context.sub_name}")
    parts.append("")
    for key, value in context.context_kwargs.items():
        if not isinstance(value, str) or not value.strip():
            continue
        parts.append(f"# {key}")
        parts.append("")
        parts.append(value.strip())
        parts.append("")
    parts.append("# Generated subcomparch (the artifact to review)")
    parts.append("")
    parts.append(generated_output.strip())
    parts.append("")
    parts.append("# Task")
    parts.append("")
    parts.append(review_task_footer())
    return "\n".join(parts).rstrip() + "\n"
