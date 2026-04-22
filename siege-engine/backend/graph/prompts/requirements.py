# ruff: noqa: E501
"""Prompt template for the requirements (``reqs_*``) draft.

The requirements pass consumes the approved feature set (the
``feat_*`` nodes minted from the feature expansion) and produces a
compact, structured list of **top-level responsibilities** that
downstream passes map onto concrete components. The schema is
machine-first: scope phrases and deferral cross-references that
make overlap mechanically detectable, not prose that has to be
re-read every regen.

Responsibility grammar (parsed by
:mod:`backend.graph.parsers.xml_sections` and validated by
:func:`backend.graph.parsers.validators.validate_requirements`):

    <requirements>
      <responsibility>
        <name>User Authentication</name>
        <scope>
          <item>password + session state</item>
          <item>sign-in rate limit</item>
        </scope>
        <does-not-own>
          <defers to="Per-Request Authorization">permission checks</defers>
        </does-not-own>
        <failure-surface>Broken verifier blocks all sign-ins; session-store bug silently degrades authenticated state.</failure-surface>
        <owns>
          <feat id="feat_abc12345"/>
        </owns>
        <supports>
          <feat id="feat_def67890"/>
        </supports>
      </responsibility>
      …
    </requirements>

Each responsibility is: name + scope (short noun phrases) +
explicit deferrals (boundary work as structured entries) + one-
sentence failure surface + owns/supports feature lists. No prose
intent paragraph — the structured fields carry the same signal
with roughly 70% fewer tokens and make cross-responsibility
overlap mechanically detectable at validation time rather than
after sysarch reads the doc.

See ``docs/architecture/v2-rearchitecture.md`` §Subrequirements
decomposition and §Feature → Responsibility → Component.
"""

from __future__ import annotations

_SYSTEM_PROMPT_TEMPLATE = """\
You are **rotating** the problem from user-facing capabilities \
to system-level guarantees. The features you are given describe \
what users can do; the responsibilities you produce describe \
what the system must ensure. These are different axes — multiple \
features contribute to one responsibility, and one feature spans \
several responsibilities, because user concerns and system \
concerns don't align 1:1. Your job is not to decompose features \
into smaller pieces; it is to re-index them along the axis of \
system-level obligation.

Your downstream reader is the **sysarch pass**, which will \
assign each responsibility to exactly one component by \
clustering responsibilities that share data ownership and \
failure modes. Your output is structured, not prose: short \
noun phrases naming the concerns each responsibility owns, \
explicit deferrals to peers for boundary work, and a one-\
sentence failure-surface statement. The structure is the \
primary signal — sysarch reads scope and failure mode, not \
a narrative.

Each feature appears in **exactly one** responsibility's \
``<owns>`` block (its primary system-side owner) and in zero or \
more responsibilities' ``<supports>`` blocks (responsibilities \
that contribute infrastructure or composition without taking \
primary ownership).

# Output format

Output two top-level blocks in this order: ``<introduction>`` \
and ``<requirements>``. The ``<introduction>`` is required — a \
short prose preamble (5–15 sentences, a couple of paragraphs) \
capturing your initial thinking about the decomposition: which \
axes of system work you identified, which responsibilities you \
considered and rejected, which ambiguities in the feature set \
you had to resolve. This is the only prose in the doc; the \
responsibilities themselves are fully structured. Keep the \
introduction compact — it exists so a later regen can re-anchor, \
not as a place to extend each responsibility's rationale.

After ``<introduction>``, output a single ``<requirements>`` \
block. Inside it, each responsibility has this exact shape (no \
``<intent>`` paragraph, no other tags):

    <introduction>
      The central axis here is control-plane vs data-plane: \
    identity + authz on one side, invoice lifecycle + payment \
    settlement on the other. I kept them as two top-level \
    resps because sysarch will almost certainly assign them to \
    separate components with different durability profiles.
    </introduction>
    <requirements>
      <responsibility>
        <name>Credential Verification and Session Establishment</name>
        <scope>
          <item>password hash storage</item>
          <item>session state lifecycle</item>
          <item>sign-in rate limit</item>
          <item>token refresh</item>
        </scope>
        <does-not-own>
          <defers to="Per-Request Permission Checks">permission-to-role mapping</defers>
          <defers to="Subscription State and Payment Collection">account activation state</defers>
        </does-not-own>
        <failure-surface>Broken verifier blocks all sign-ins; session-store bug silently degrades authenticated state.</failure-surface>
        <owns>
          <feat id="feat_login01"/>
          <feat id="feat_pwdrst2"/>
          <feat id="feat_session"/>
        </owns>
      </responsibility>
      <responsibility>
        <name>Per-Request Permission Checks</name>
        <scope>
          <item>permission-to-role mapping</item>
          <item>per-request access decision</item>
        </scope>
        <does-not-own>
          <defers to="Credential Verification and Session Establishment">user identity records</defers>
        </does-not-own>
        <failure-surface>A permission check bug is either a denial-of-service (false negatives) or a privilege escalation (false positives).</failure-surface>
        <owns>
          <feat id="feat_admin99"/>
        </owns>
        <supports>
          <feat id="feat_login01"/>
        </supports>
      </responsibility>
      <responsibility>
        <name>Subscription State and Payment Collection</name>
        <scope>
          <item>account plan state</item>
          <item>payment-method record</item>
          <item>grace-period countdown</item>
          <item>invoice emission</item>
        </scope>
        <does-not-own>
          <defers to="Bundle Configuration">pricing model</defers>
        </does-not-own>
        <failure-surface>Payment-collector outage stalls account activation; invoice emission bug charges the wrong customer.</failure-surface>
        <owns>
          <feat id="feat_plans00"/>
          <feat id="feat_invoice"/>
        </owns>
      </responsibility>
    </requirements>

# Rules

* Each ``<responsibility>`` has exactly one ``<name>``, exactly \
one ``<scope>`` block, at most one ``<does-not-own>`` block, \
exactly one ``<failure-surface>``, exactly one ``<owns>`` block, \
and at most one ``<supports>`` block. No ``<intent>`` tag, no \
other tags. The structure is the spec.
* ``<name>`` is a short identifier — typically 2 to 5 words, title \
case. Name the system-level guarantee, not the engineering \
category. "Credential Verification and Session Establishment" \
is sharper than "User Authentication"; "Subscription State and \
Payment Collection" is sharper than "Billing"; "Background \
Retry Scheduling" is sharper than "Job Execution". If the name \
could label a responsibility in any software project without \
modification, push toward what makes this project's version \
distinctive.
* ``<scope>`` is **required** and must contain **at least one** \
``<item>`` child. Each ``<item>`` is a short noun phrase (2–8 \
words, system-side) naming a concrete concern this \
responsibility owns. Think "persistent-state handles" and \
"durable-invariant labels", not "user activities" — scope \
phrases should read as system concerns sysarch can assign to \
a module. Good examples: "append-only event log", "pure reducer \
entrypoint", "staleness cascade edge walk", "per-generation \
sandbox filesystem scope", "review SLA timer". Bad examples: \
"users can log in" (feature axis), "secure session handling" \
(vague), "authentication".
* ``<does-not-own>`` is optional and contains ``<defers>`` \
entries with a ``to="Other Responsibility Name"`` attribute and \
a scope-phrase body. Each entry records a concern this \
responsibility explicitly defers to another responsibility in \
this doc, making the boundary between the two explicit. The \
``to`` attribute must match another responsibility's ``<name>`` \
exactly — the validator rejects unresolved references. Use this \
generously where boundaries are easy to get wrong; an empty \
``<does-not-own>`` is fine when the boundary is obvious from the \
scope alone.
* ``<failure-surface>`` is **required** and is a single sentence \
naming the concrete failure mode (data loss, invariant violation, \
silent degradation, security breach). Example: "Reducer drift is \
a platform-integrity incident; a non-reducer write path is an \
invariant violation; log corruption is project data loss." \
Name the specific failure, not the impact category.
* ``<owns>`` is **required** and must contain **at least one** \
``<feat>`` child. ``<owns>`` declares the features this \
responsibility is the primary system-side owner of — the single \
responsibility that carries each feature's system-level guarantee.
* ``<supports>`` is optional and may contain zero or more \
``<feat>`` children. ``<supports>`` declares features where this \
responsibility contributes infrastructure, composition, or a \
read-dependency slice, but another responsibility is the primary \
owner. Use it generously when the dependency is real.
* Each ``<feat>`` inside ``<owns>`` or ``<supports>`` carries an \
``id`` attribute matching exactly the feature ID shown in the \
input list (the ``feat_*`` prefix plus the 8-character Crockford \
suffix). Do not invent IDs, do not rewrite them, do not rename \
them.
* **Single-owner rule (load-bearing).** Every feature ID appears \
in exactly one responsibility's ``<owns>`` block across the \
whole document. Two responsibilities both claiming ownership of \
the same feature is a scope collision — the validator rejects \
it and feeds you a list of offending features. If two \
responsibilities really do both want a feature, one of them \
owns it and the other declares ``<supports>`` — or the \
boundary between the two responsibilities is drawn wrong and \
needs redrawing.
* **Scope-dedup rule (load-bearing).** No two responsibilities \
may share a scope phrase (case- and whitespace-insensitive). If \
two responsibilities both list "event-log retention" in their \
scope, the validator rejects the draft — rename one, collapse \
them into a single responsibility, or split the phrase by the \
real boundary ("event-log retention window" vs "audit-log \
retention policy"). The scope list is the primary dedup target; \
drafting short distinct phrases for each responsibility is the \
entire point of the grammar.
* **Every feature in the input must be owned by some \
responsibility.** A feature that appears only in ``<supports>`` \
(or nowhere) is a coverage gap — the validator rejects it.
* **Break feature boundaries — that is the point of this tier.** \
A feature like "Accept card payments" touches payment \
processing, account state management, audit logging, and \
notification delivery. Those are four different system concerns \
with different data ownership and different failure modes. Don't \
mirror the feature structure — redistribute it. If your \
responsibility list looks like the feature list with different \
names, you haven't rotated.
* **Group into one responsibility concerns that share data \
ownership and fail together.** Separate concerns that touch \
different data or have different failure surfaces. Sysarch \
clusters resps into components along these same lines, so the \
closer your responsibility boundaries match data-ownership \
boundaries, the cleaner sysarch's component assignments will be.
* **Cross-cutting concerns are responsibilities too.** Logging, \
telemetry, health checks, background job scheduling, rate \
limiting, secrets handling — if the project needs them, name \
them. Cross-cutting responsibilities still need an ``<owns>`` \
block listing at least one feature they are the primary owner of.
* **Responsibilities are system-level guarantees, not UI/backend \
splits.** A single responsibility like "Payment Collection" \
covers both backend mechanics and UI; sysarch decides which \
components handle which side.
* Do not include meta-commentary. Output only ``<introduction>`` \
followed by ``<requirements>``.
* Unescaped ``&`` and ``<`` in scope / defers / failure-surface \
text are fine — the parser tolerates them.
"""


def render_system_prompt() -> str:
    """Return the requirements system prompt."""
    return _SYSTEM_PROMPT_TEMPLATE


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
