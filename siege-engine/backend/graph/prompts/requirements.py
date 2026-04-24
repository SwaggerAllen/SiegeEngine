# ruff: noqa: E501
"""Prompt template for the requirements (``reqs_*``) draft.

The requirements pass consumes the approved feature set (the
``feat_*`` nodes minted from the feature expansion) and produces
a flat list of **atomic system-side responsibilities** — one
concern per atom, named by a short noun phrase. Clustering into
components is sysarch's job, not this tier's; the grammar is
deliberately first-class-atom so structural edits (rename /
merge / split / reparent) can mobilize individual atoms without
prose surgery.

Atomic responsibility grammar (parsed by
:mod:`backend.graph.parsers.xml_sections` and validated by
:func:`backend.graph.parsers.validators.validate_requirements`):

    <requirements>
      <responsibility>
        <name>session-state lifecycle</name>
        <feats>
          <feat id="feat_login01"/>
        </feats>
      </responsibility>
      …
    </requirements>

Document-level invariants (enforced by the validator):

* **Name-dedup** — no two atoms share a normalized name.
* **Feat-coverage** — every known feature appears in at least one
  atom's ``<feats>``; a feature with no atom tag is a rotation
  gap and fails parse.

Many-to-many is expected: a cross-cutting feature may implicate
multiple atoms. Empty ``<feats/>`` is legal for system-emergent
atoms (event log, reducer, etc.) with no direct feature cause.

See ``docs/architecture/v2-rearchitecture.md`` §Subrequirements
decomposition and §Feature → Responsibility → Component.
"""

from __future__ import annotations

_SYSTEM_PROMPT_TEMPLATE = """\
You are **rotating** the problem from user-facing capabilities \
to system-side obligations. The features you are given describe \
what users can do; the responsibilities you produce describe \
what the system must handle. These are different axes — one \
feature usually implicates several system-side concerns, and \
one concern is usually implicated by several features, because \
user concerns and system concerns don't align 1:1. Your job is \
not to decompose features; it is to re-index them along the \
axis of system-side concern.

Each responsibility you produce is an **atom** — one concrete \
concern, not a grouping. "session-state lifecycle" is an atom. \
"rate-limit buckets" is an atom. "Authentication" is not an atom \
— it is a grouping of several concerns (session, password hash, \
rate limit, token refresh) that you will emit as separate atoms. \
Clustering these atoms into components is the downstream \
**sysarch pass**'s job, not yours. Your job is to enumerate the \
atoms and tag each one with the feature IDs that implicate it.

# Output format

Output two top-level blocks in this order: ``<introduction>`` \
and ``<requirements>``. The ``<introduction>`` is optional — a \
short prose preamble (2–5 sentences) naming the rotation axis \
you used and any ambiguities you had to resolve. Keep it \
compact; the atoms themselves carry the load.

After ``<introduction>``, output a single ``<requirements>`` \
block. Inside it, each ``<responsibility>`` has this exact \
shape — one ``<name>`` and one ``<feats>`` block, nothing else:

    <introduction>
    Rotating login, password-reset, permission, and invoicing \
    features onto system-side axes: auth produces several \
    independent concerns (session state, password hashing, rate \
    limiting, token refresh, permission mapping) that sysarch \
    will likely cluster across two or three components. The \
    event log has no direct feature cause; it's a platform-level \
    emergent atom.
    </introduction>
    <requirements>
      <responsibility>
        <name>append-only event log</name>
        <feats/>
      </responsibility>
      <responsibility>
        <name>password hash storage</name>
        <feats>
          <feat id="feat_login01"/>
          <feat id="feat_pwdrst2"/>
        </feats>
      </responsibility>
      <responsibility>
        <name>session-state lifecycle</name>
        <feats>
          <feat id="feat_login01"/>
        </feats>
      </responsibility>
      <responsibility>
        <name>sign-in rate limit</name>
        <feats>
          <feat id="feat_login01"/>
        </feats>
      </responsibility>
      <responsibility>
        <name>session token refresh</name>
        <feats>
          <feat id="feat_login01"/>
        </feats>
      </responsibility>
      <responsibility>
        <name>password-reset token issuance</name>
        <feats>
          <feat id="feat_pwdrst2"/>
        </feats>
      </responsibility>
      <responsibility>
        <name>permission-to-role mapping</name>
        <feats>
          <feat id="feat_admin99"/>
        </feats>
      </responsibility>
      <responsibility>
        <name>per-request access decision</name>
        <feats>
          <feat id="feat_admin99"/>
          <feat id="feat_login01"/>
        </feats>
      </responsibility>
      <responsibility>
        <name>invoice emission</name>
        <feats>
          <feat id="feat_invoice"/>
        </feats>
      </responsibility>
      <responsibility>
        <name>grace-period countdown</name>
        <feats>
          <feat id="feat_invoice"/>
        </feats>
      </responsibility>
    </requirements>

Notice what happens across the 10 atoms above: four features \
expand into ten system-side concerns; ``feat_login01`` appears \
in five atoms (cross-cutting login concern); the event-log atom \
has no direct feature cause (emergent platform concern); no two \
atoms share a name. That is the rotation.

# Rules

* Each ``<responsibility>`` has exactly one ``<name>`` and \
exactly one ``<feats>`` block. No other tags — no ``<scope>``, \
no ``<intent>``, no ``<failure-surface>``, no ``<owns>``, no \
``<supports>``, no ``<does-not-own>``. The structure is the spec.
* ``<name>`` is a short noun phrase (2–8 words, typically \
lowercase) naming **one** system-side concern. Good examples: \
"append-only event log", "per-request access decision", \
"staleness cascade edge walk", "review SLA timer", \
"per-generation sandbox filesystem scope". Bad examples: \
"User Authentication" (grouping — break into session lifecycle, \
password hash, rate limit, etc.), "users can log in" (feature \
axis, not system-side), "secure session handling" (vague), \
"authentication" (one word, vague).
* **One atom = one concern.** If the name has "and" in it, it's \
probably two atoms. "session lifecycle and token refresh" → \
split into "session-state lifecycle" + "session token refresh". \
"billing state and invoice emission" → split.
* ``<feats>`` is a flat list of zero-or-more \
``<feat id="feat_..."/>`` children naming every feature that \
implicates this atom. Each ``id`` must match exactly a feature \
ID from the input list (``feat_*`` prefix plus 8-character \
Crockford suffix). Do not invent IDs, do not rewrite them.
* **Many-to-many is expected.** A feature like \
``feat_login01`` typically implicates session lifecycle, \
password hash, rate limit, token refresh, and access decision — \
tag it on all five. The grammar does not track "primary" \
ownership; sysarch figures out clustering.
* **Empty ``<feats/>`` is legal** for system-emergent atoms with \
no direct feature cause — an append-only event log, a reducer \
entrypoint, a per-project sandbox root. Use this when the atom \
is real but no user-facing feature names it.
* **Name-dedup (enforced).** No two atoms share a name \
(case- and whitespace-insensitive). If two candidates would \
collide, they are either the same atom (merge them) or need \
sharper names that distinguish the actual boundary.
* **Feat-coverage (enforced).** Every feature in the input must \
appear in at least one atom's ``<feats>``. A feature with no \
atom tag is a rotation gap — the validator rejects the draft and \
names the missing IDs. If a feature looks like it has no system \
side, look again: every feature imposes *some* system-side \
obligation, even if only "persist this preference".
* **Break feature boundaries — that is the point.** A feature \
like "Accept card payments" decomposes into payment-method \
storage, charge authorization, invoice emission, retry \
scheduling, and audit trail — five atoms, one feature. If your \
atom list looks like the feature list with different names, you \
haven't rotated.
* **No atom-count ceiling — prefer splitting when uncertain.** \
There is no target count. If a candidate name packs multiple \
concerns ("review routing, notification, and SLA"), split it \
into separate atoms even if that pushes the total well past \
what "feels right". Clustering is sysarch's job, not yours; a \
longer atom list that preserves one-concern-per-atom is always \
better than a shorter list that smuggles groupings back in. \
Aim for atoms at the "one coherent piece of system behavior \
sysarch could assign to a module" scale.
* **Clustering is sysarch's job, not yours.** Don't group atoms \
into components. Don't worry if one feature tags five atoms \
that might live in three different components — sysarch will \
cluster them. Your job is the flat atom list.
* **Atoms are system-side concerns, not UI/backend splits.** Do \
not emit sibling atoms like "payment mechanics" + "payment UI"; \
emit one atom naming the system-side concern ("invoice emission") \
and let sysarch decides which components render which side. The \
rotation axis is user-facing → system-side, not user-facing → \
frontend vs. backend.
* Do not include meta-commentary. Output only ``<introduction>`` \
followed by ``<requirements>``.
* Unescaped ``&`` and ``<`` in names are fine — the parser \
tolerates them.
"""


def render_system_prompt() -> str:
    """Return the requirements system prompt."""
    from backend.graph.prompts._change_summary import change_summary_instruction

    return _SYSTEM_PROMPT_TEMPLATE + change_summary_instruction()


def render_user_prompt(
    *,
    features_summary: str,
    prior_approved: str | None,
    prior_pending: str | None,
    feedback: str | None,
    parse_error: str | None = None,
    vocab_summary: str = "",
    input_doc: str = "",
    referenced_content_summary: str = "",
) -> str:
    """Build the user prompt for the requirements generator.

    ``features_summary`` is a plain-text rendering of the project's
    minted ``feat_*`` nodes (name + intent per feature, grouped by
    ``group_label`` where applicable) — built by the handler from
    a fresh query of the database so it reflects whatever the
    feature-mint pass landed. The rest of the parameters mirror
    the feature-expansion prompt: prior approved / pending content
    for regen iteration, user feedback for revision, and an
    optional ``parse_error`` for the parse-validate retry path.

    ``input_doc`` is the raw project input document. The handler
    passes it on every generation so the LLM sees the original
    framing for both initial drafts and feedback iterations.
    This function just renders the section when non-empty and
    omits it otherwise.
    """
    parts: list[str] = []
    if input_doc and input_doc.strip():
        parts.append("# Project input document")
        parts.append("")
        parts.append(input_doc.strip())
        parts.append("")
    if vocab_summary and vocab_summary.strip():
        parts.append(vocab_summary.strip())
        parts.append("")
    if (
        referenced_content_summary
        and referenced_content_summary.strip()
        and referenced_content_summary.strip() != "(no external references)"
    ):
        parts.append(referenced_content_summary.strip())
        parts.append("")
    parts.append("# Project features (approved upstream)")
    parts.append("")
    parts.append(features_summary.strip() or "(no features minted yet)")
    parts.append("")

    prior = prior_pending or prior_approved
    if prior:
        parts.append("# Current version")
        parts.append("")
        parts.append(prior.strip())
        parts.append("")

    if feedback:
        parts.append("# User feedback")
        parts.append("")
        parts.append(feedback.strip())
        parts.append("")

    if parse_error:
        parts.append("# Previous output failed structural validation")
        parts.append("")
        parts.append(
            "Your previous response did not parse into a valid "
            "<requirements> block. The specific error was:"
        )
        parts.append("")
        parts.append(f"> {parse_error.strip()}")
        parts.append("")
        parts.append(
            "Fix the structure and re-emit the full <requirements> block. "
            "Keep the responsibility set itself the same where possible — "
            "this retry is about format, not content."
        )
        parts.append("")

    parts.append("# Task")
    parts.append("")
    if parse_error:
        parts.append(
            "Re-emit the requirements as a valid <requirements> block "
            "addressing the structural error above. Output only the "
            "corrected <requirements> block."
        )
    elif feedback and prior:
        parts.append(
            "Revise the requirements to address the user feedback above. "
            "Preserve structure where the feedback does not request "
            "changes. Output only the revised <requirements> block."
        )
    elif prior:
        parts.append(
            "Improve the requirements above. Fix any issues you notice "
            "with responsibility boundaries, coverage, specificity, or "
            "the axis rotation from features to system-level guarantees. "
            "Output only the revised <requirements> block."
        )
    else:
        parts.append(
            "Write an initial top-level requirements list for this "
            "project based on the features above. Output only the "
            "<requirements> block."
        )

    return "\n".join(parts).rstrip() + "\n"


def format_features_summary(features: list[dict]) -> str:
    """Render minted ``feat_*`` nodes as a plain-text feature list
    suitable for embedding in the prompt.

    Each ``features`` element must have at least these keys:
    ``id``, ``name``, ``content`` (the intent paragraph), and
    optionally ``group_label`` (for group grouping in the output)
    and ``is_implicit``. Features are rendered in the provided
    order, grouped by label. Ungrouped features land under an
    implicit "(ungrouped)" heading only if there are also grouped
    features in the same batch — otherwise the list is flat.

    **The ID is the load-bearing part** — the LLM needs to echo
    these IDs verbatim in each ``<owns>`` / ``<supports>`` block,
    so they must appear in the rendered list. The name and intent
    are context.
    """
    if not features:
        return "(no features minted yet)"

    # Bucket features by group_label preserving first-appearance
    # order, same as the frontend FeatureList rendering. A small
    # duplication because the frontend does it in TypeScript and
    # this is Python; both read from the same raw list though.
    buckets: dict[str | None, list[dict]] = {}
    order: list[str | None] = []
    for feat in features:
        key = feat.get("group_label")
        if key not in buckets:
            buckets[key] = []
            order.append(key)
        buckets[key].append(feat)

    any_grouped = any(label is not None for label in order)

    lines: list[str] = []
    for label in order:
        bucket = buckets[label]
        if any_grouped:
            lines.append(f"## {label or '(ungrouped)'}")
            lines.append("")
        for feat in bucket:
            fid = feat.get("id", "").strip() or "(unknown-id)"
            name = feat.get("name", "").strip() or "(unnamed)"
            intent = (feat.get("content") or "").strip()
            implicit_marker = " (inferred)" if feat.get("is_implicit") else ""
            lines.append(f"- `{fid}` **{name}**{implicit_marker}: {intent}")
        lines.append("")

    return "\n".join(lines).rstrip()
