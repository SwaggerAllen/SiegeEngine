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
``<intent>``, and **either** exactly one ``<covers>`` block \
listing the feature IDs it serves **or** an ``<implicit/>`` \
marker (see the implicit-responsibilities section below). \
The two are mutually exclusive on a single responsibility:

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
      <responsibility>
        <name>Central Metric Registry</name>
        <intent>Own the single authoritative vocabulary of \
metric names, types, and labels the whole system emits. \
Components register their metrics through this registry at \
boot; the registry enforces name uniqueness, stable labeling, \
and the rule that no component emits an unregistered metric. \
Failure surface: registry inconsistency produces silently \
incompatible telemetry across components. This is a \
system-facing architectural concern, not a user-facing \
feature — mark it <implicit/>.</intent>
        <implicit/>
      </responsibility>
    </requirements>

# Rules

* Use the tag structure exactly as shown. Each ``<responsibility>`` \
has exactly one ``<name>``, exactly one ``<intent>``, and either \
exactly one ``<covers>`` block or exactly one ``<implicit/>`` \
marker (see below). No other tags inside a responsibility.
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
* ``<covers>`` is **required for explicit responsibilities** and \
must contain **at least one** ``<feat>`` child. Each ``<feat>`` \
carries an ``id`` attribute matching exactly the feature ID \
shown in the input list (the ``feat_*`` prefix plus the \
8-character Crockford suffix). Do not invent IDs, do not \
rewrite them, do not rename them. If a responsibility traces \
to no features, it must be an **implicit** responsibility — \
use the ``<implicit/>`` marker instead of ``<covers>``.
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
than the feature list but finer than the project description. \
Err on the side of fewer, coarser responsibilities — \
sub-decomposition happens in a later pass per component.
* **Cross-cutting concerns are responsibilities too.** Logging, \
telemetry, health checks, background job scheduling, rate \
limiting, secrets handling — if the project needs them, name \
them. They won't always appear in the feature list directly, \
but they're real work the system has to do and the sysarch pass \
will want them named up front so cross-cutting policies can \
target them later. Ask which kind of cross-cutting each one is: \
if the concern is triggered by feature execution (logging fires \
during feature runs, rate-limiting guards feature endpoints), \
it's an **explicit** responsibility whose ``<covers>`` lists the \
features whose execution triggers it. If the concern is \
architectural scaffolding that the system needs regardless of \
which features exist (a central metric registry, an error-code \
vocabulary, a pubsub event-name bus, a config-schema registry), \
it's an **implicit** responsibility — see the next rule.
* **Implicit responsibilities.** Use the ``<implicit/>`` marker \
in place of ``<covers>`` for responsibilities that capture a \
system-facing concern not sourced from any feature. The canonical \
cases are architectural registries and vocabularies that every \
component hooks into: a central metric registry, a shared \
error-code taxonomy, a pubsub event-name registry, a shared \
config schema, a logging-context registry. These exist because \
the system needs consistent cross-component machinery, not \
because any user asked for them — no feature "covers" them, and \
forcing a ``<covers>`` block turns the resp into a lie about its \
origin. Implicit resps are still real responsibilities: sysarch \
will assign each one to a component (typically the foundation \
component) exactly like explicit ones. **Distinction from \
policies:** an implicit responsibility declares that the system \
owns a piece of architectural machinery ("own the metric \
registry"); a policy declares a cross-cutting obligation \
applied outward ("every component must register its metrics in \
this shape"). You often want both — an implicit resp for the \
registry's existence + a policy enforcing its use — and the \
policy pass handles the latter. Keep implicit resps scoped to \
genuine architectural scaffolding; do not use ``<implicit/>`` as \
an escape hatch for a responsibility that could reasonably be \
tied back to features.
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
* **Responsibilities are system-level guarantees, not UI/backend \
splits.** Do not split a feature into "backend mechanics" and \
"user-facing layer" as separate responsibilities — that split \
is a structural decision the sysarch pass makes when it assigns \
responsibilities to domain and presentational components. A \
single responsibility like "Payment Collection" covers both the \
backend mechanics and whatever UI surface presents it; sysarch \
decides which components handle which side.
* Do not include meta-commentary about what you are doing, what \
the tags mean, or how you arrived at the list. Output only the \
``<requirements>`` block.
* Unescaped ``&`` and ``<`` in the intent text are fine — the \
parser tolerates them.
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
