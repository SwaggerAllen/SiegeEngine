"""Prompt template for the requirements (``reqs_*``) draft.

The requirements pass consumes the approved feature set (the
``feat_*`` nodes minted from the feature expansion) and produces a
structured, tag-based list of **top-level responsibilities** that
downstream passes will map onto concrete components. The
feature → responsibility relationship is many-to-many and is
captured as ``<covers>`` children on each responsibility — on
approval the mint handler emits a ``decomposition`` edge
(``feat_X → resp_Y``) for every listed feature.

Output format (parsed by :mod:`backend.graph.parsers.xml_sections`
and validated by :func:`backend.graph.parsers.validators.validate_requirements`):

    <requirements>
      <responsibility>
        <name>User Authentication</name>
        <intent>…paragraph-length description of what this
        responsibility covers, framed at the role level…</intent>
        <covers>
          <feat id="feat_abc12345"/>
          <feat id="feat_def67890"/>
        </covers>
      </responsibility>
      …
    </requirements>

Parallel shape to the feature expansion prompt on purpose:
``<requirements>`` is to ``reqs_*`` what ``<features>`` is to
``expansion_*``. A shared parse-validate retry loop lives in the
generation handler.

See ``docs/architecture/v2-rearchitecture.md`` §Subrequirements
decomposition and §Feature → Responsibility → Component.
"""

from __future__ import annotations

from backend.projects.settings import NodeCountRange

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
failure modes. Write responsibility handles that sysarch can \
cluster without guessing which component should own them. A \
responsibility whose intent could describe two different \
components' work is cut too broadly; a responsibility whose \
intent duplicates another's data concern under a different \
feature label hasn't left the feature axis behind.

You will be given a list of features (approved in an upstream \
pass, each with a stable ``feat_*`` ID) and must produce a \
structured responsibility list. The feature → responsibility \
relationship is many-to-many; you record it via ``<covers>`` \
children listing the feature IDs each responsibility serves.

# Output format

Output a single ``<requirements>`` block. Nothing else. Inside \
it, each responsibility has exactly one ``<name>``, exactly one \
``<intent>``, and exactly one ``<covers>`` block containing one \
or more ``<feat>`` children with an ``id`` attribute:

    <requirements>
      <responsibility>
        <name>Credential Verification and Session Establishment</name>
        <intent>Verify the identity of a human or service \
interacting with the system, establish a session, and make the \
identity available to downstream logic. Owns the session state \
lifecycle: creation on successful verification, refresh on \
activity, invalidation on sign-out or timeout. Covers sign-in, \
sign-out, token refresh, and session invalidation, but not the \
specific credential mechanism (password, SSO, passkey) — that's \
an implementation choice settled later. Failure surface: a \
broken verifier blocks all sign-ins; a broken session store \
silently degrades authenticated state.</intent>
        <covers>
          <feat id="feat_login01"/>
          <feat id="feat_pwdrst2"/>
          <feat id="feat_session"/>
        </covers>
      </responsibility>
      <responsibility>
        <name>Per-Request Permission Checks</name>
        <intent>Decide whether an authenticated principal may \
perform a given action on a given resource. Separate from \
credential verification because the checks apply at every \
request, not just at sign-in, and because the policy surface \
grows independently of the identity surface. Owns the \
permission-to-role mapping data; does not own user records or \
session state.</intent>
        <covers>
          <feat id="feat_login01"/>
          <feat id="feat_admin99"/>
        </covers>
      </responsibility>
      <responsibility>
        <name>Subscription State and Payment Collection</name>
        <intent>Maintain the billing state of each account: \
active plan, payment method on file, grace-period countdown. \
Collect payment via provider API, emit invoices, schedule \
retries on failure, and suspend accounts when retries exhaust. \
Owns subscription records and invoice history. Does not own \
pricing-model decisions — those are configuration, not \
runtime state.</intent>
        <covers>
          <feat id="feat_plans00"/>
          <feat id="feat_invoice"/>
        </covers>
      </responsibility>
    </requirements>

# Rules

* Use the tag structure exactly as shown. Each ``<responsibility>`` \
has exactly one ``<name>``, exactly one ``<intent>``, and exactly \
one ``<covers>`` block. No other tags inside a responsibility.
* ``<name>`` is a short identifier — typically 2 to 5 words, title \
case. Name the system-level guarantee, not the engineering \
category. "Credential Verification and Session Establishment" \
is sharper than "User Authentication"; "Subscription State and \
Payment Collection" is sharper than "Billing"; "Background \
Retry Scheduling" is sharper than "Job Execution". If the name \
could label a responsibility in any software project without \
modification, push toward what makes this project's version \
distinctive. The name is sysarch's shortest handle for \
assigning this responsibility to a component — it has to earn \
its brevity by being specific.
* ``<intent>`` is a paragraph — typically 2 to 5 sentences. The \
sysarch pass will read this intent to decide which component \
owns this responsibility. Name the specific data this \
responsibility governs, the specific operations it performs, \
and the failure surfaces it has. Also name what it explicitly \
does **not** cover, so sysarch knows where boundaries lie. \
Avoid prescribing implementation (no "we will use JWT", no \
"this service will expose a REST API"). A good intent reads \
like a system-level contract: "Verify the identity of a caller, \
establish a session, and make the identity available to \
downstream logic — covers sign-in, sign-out, token refresh, \
and session invalidation, but not the specific credential \
mechanism."
* ``<covers>`` is **required** and must contain **at least one** \
``<feat>`` child per responsibility. Each ``<feat>`` carries an \
``id`` attribute matching exactly the feature ID shown in the \
input list (the ``feat_*`` prefix plus the 8-character Crockford \
suffix). Do not invent IDs, do not rewrite them, do not rename \
them. A responsibility that covers no features is not a valid \
top-level responsibility — either merge it into one that does \
or drop it.
* A feature may appear under multiple ``<covers>`` blocks — the \
relationship is many-to-many. A cross-cutting responsibility \
like "Telemetry" will typically cover most features; a scoped \
responsibility like "Billing" will cover only a handful. This \
is expected.
* **Every feature in the input must be covered by at least one \
responsibility.** Before emitting the list, mentally check that \
each input feature ID appears in at least one ``<covers>`` block. \
Missing coverage is a parse error that gets fed back to you.
* **Granularity.** Aim for a responsibility list that's coarser \
than the feature list but finer than the project description. A \
typical project produces {{TYPICAL_MIN}}–{{TYPICAL_MAX}} top-level \
responsibilities. If you're at {{CEILING}} or more, you're \
reaching into implementation territory; if you're at {{FLOOR}} \
or fewer, you're probably glossing over real decomposition \
work. Err on the side of fewer, coarser responsibilities — \
sub-decomposition happens in a later pass per component.
* **Cross-cutting concerns are responsibilities too.** Logging, \
telemetry, health checks, background job scheduling, rate \
limiting, secrets handling — if the project needs them, name \
them. They won't always appear in the feature list directly, but \
they're real work the system has to do and the sysarch pass will \
want them named up front so cross-cutting policies can target \
them later. Cross-cutting responsibilities still need a \
``<covers>`` block — list the features whose generation or \
execution you'd expect to trigger the cross-cutting concern.
* **Break feature boundaries — that is the point of this tier.** \
A feature like "Accept card payments" touches payment \
processing, account state management, audit logging, and \
notification delivery. Those are four different system concerns \
with different data ownership and different failure modes. Don't \
mirror the feature structure — redistribute it. If your \
responsibility list looks like the feature list with different \
names, you haven't rotated.
* **Group into one responsibility concerns that share data \
ownership and fail together.** Separate into different \
responsibilities concerns that touch different data or have \
different failure surfaces, even if they serve the same \
user-facing feature. Sysarch will cluster resps into components \
along these same lines, so the closer your responsibility \
boundaries match data-ownership boundaries, the cleaner \
sysarch's component assignments will be.
* **Split server-side and user-facing work into sibling \
responsibilities.** When a feature has both back-end mechanics \
and a user-facing interaction layer, produce **two separate \
responsibilities** — one describing the mechanics (what the \
server does) and one describing the user-facing layer (what \
the user interacts with). Both ``<covers>`` the same feature. \
The sysarch pass downstream assigns each responsibility to \
exactly one component, and presentational components are \
first-class citizens that need their own responsibilities to \
own. A single fat "Handle X" responsibility that smears across \
both concerns forces sysarch into a corner. Example: feature \
"Accept card payments" should produce siblings \
"Payment Processing" (tokenize card, call provider, update \
account state) **and** "Payment Form UX" (render card input, \
inline validation, error messaging). They both cover the same \
feat_*. Not every feature needs the split — a purely-backend \
feature like "Nightly audit sweep" or a purely-UI feature like \
"Theme switcher" stays as a single responsibility.
* Do not include meta-commentary about what you are doing, what \
the tags mean, or how you arrived at the list. Output only the \
``<requirements>`` block.
* Unescaped ``&`` and ``<`` in the intent text are fine — the \
parser tolerates them.
"""


def render_system_prompt(counts: NodeCountRange) -> str:
    """Return the requirements system prompt with count tokens filled.

    The template cites four numbers for the top-level
    responsibility count — typical min/max plus a floor and a
    ceiling for the "you're under-decomposing / over-decomposing"
    warnings. The handler pulls the configured
    ``top_level_responsibilities`` range off ``ProjectSettings``
    and passes it here.
    """
    return (
        _SYSTEM_PROMPT_TEMPLATE.replace("{{FLOOR}}", str(counts.floor))
        .replace("{{TYPICAL_MIN}}", str(counts.typical_min))
        .replace("{{TYPICAL_MAX}}", str(counts.typical_max))
        .replace("{{CEILING}}", str(counts.ceiling))
    )


def render_user_prompt(
    *,
    features_summary: str,
    prior_approved: str | None,
    prior_pending: str | None,
    feedback: str | None,
    parse_error: str | None = None,
    vocab_summary: str = "",
    input_doc: str = "",
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
    parts.append("# Project features (approved upstream)")
    parts.append("")
    parts.append(features_summary.strip() or "(no features minted yet)")
    parts.append("")

    if prior_approved:
        parts.append("# Previously-approved requirements")
        parts.append("")
        parts.append(prior_approved.strip())
        parts.append("")

    if prior_pending:
        parts.append("# Current draft (not yet approved)")
        parts.append("")
        parts.append(prior_pending.strip())
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
    elif feedback and (prior_pending or prior_approved):
        parts.append(
            "Revise the requirements to address the user feedback above. "
            "Preserve structure where the feedback does not request "
            "changes. Output only the revised <requirements> block."
        )
    elif prior_pending or prior_approved:
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
    these IDs verbatim in each ``<covers>`` block, so they must
    appear in the rendered list. The name and intent are context.
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
