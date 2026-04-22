"""Prompt template for the requirements (``reqs_*``) draft.

The requirements pass consumes the approved feature set (the
``feat_*`` nodes minted from the feature expansion) and produces a
structured, tag-based list of **top-level responsibilities** that
downstream passes will map onto concrete components. The
feature → responsibility relationship splits into two roles:
``<owns>`` (primary system-side owner — exactly one per feature
across the whole doc) and ``<supports>`` (responsibilities that
contribute infrastructure or a composed slice without taking
primary ownership — zero or more per feature). Both feed the
many-to-many ``decomposition`` edges the mint handler emits on
approval; the split is a correctness gate against scope
collisions, not a downstream topology change.

Output format (parsed by :mod:`backend.graph.parsers.xml_sections`
and validated by :func:`backend.graph.parsers.validators.validate_requirements`):

    <requirements>
      <responsibility>
        <name>User Authentication</name>
        <intent>…paragraph-length description of what this
        responsibility covers, framed at the role level…</intent>
        <owns>
          <feat id="feat_abc12345"/>
        </owns>
        <supports>
          <feat id="feat_def67890"/>
        </supports>
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
structured responsibility list. Each feature appears in \
**exactly one** responsibility's ``<owns>`` block (its primary \
system-side owner) and in zero or more responsibilities' \
``<supports>`` blocks (responsibilities that contribute \
infrastructure or composition without taking primary ownership).

# Output format

Output two top-level blocks in this order: ``<introduction>`` \
and ``<requirements>``. The ``<introduction>`` is required — a \
2–5 paragraph prose preamble capturing your initial thinking \
about the decomposition: which axes of system work you \
identified, which responsibilities you considered and rejected, \
which ambiguities in the feature set you had to resolve (or \
flagged as open). Downstream tiers don't read this intro, but \
when requirements regenerates with feedback you (or a later \
model) can refer back to it to stay anchored in your initial \
framing instead of restarting from scratch.

After ``<introduction>``, output a single ``<requirements>`` \
block. Inside it, each responsibility has exactly one \
``<name>``, exactly one ``<intent>``, exactly one ``<owns>`` \
block, and at most one ``<supports>`` block. Each of those \
blocks contains one or more ``<feat>`` children with an ``id`` \
attribute (``<supports>`` may be omitted or empty):

    <introduction>
      The central axis here is control-plane vs data-plane: \
    identity + authz on one side, invoice lifecycle + payment \
    settlement on the other. Kept them as two top-level resps \
    because sysarch will almost certainly assign them to \
    separate components with different durability profiles.

      Open question I flagged in passing: the input doc says \
    "admin override" without specifying whether it produces \
    audit entries. I assumed yes (operational necessity) and \
    captured it in the Authorization resp's intent.
    </introduction>
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
        <owns>
          <feat id="feat_login01"/>
          <feat id="feat_pwdrst2"/>
          <feat id="feat_session"/>
        </owns>
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
        <owns>
          <feat id="feat_admin99"/>
        </owns>
        <supports>
          <feat id="feat_login01"/>
        </supports>
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
        <owns>
          <feat id="feat_plans00"/>
          <feat id="feat_invoice"/>
        </owns>
      </responsibility>
    </requirements>

# Rules

* Use the tag structure exactly as shown. Each ``<responsibility>`` \
has exactly one ``<name>``, exactly one ``<intent>``, exactly one \
``<owns>`` block, and at most one ``<supports>`` block. No other \
tags inside a responsibility.
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
* ``<owns>`` is **required** and must contain **at least one** \
``<feat>`` child per responsibility. ``<owns>`` declares the \
features this responsibility is the primary system-side owner \
of — the single responsibility that carries the feature's \
system-level guarantee. A responsibility that owns no features \
is not a valid top-level responsibility — either merge it into \
one that does or drop it.
* ``<supports>`` is optional and may contain zero or more \
``<feat>`` children. ``<supports>`` declares features where this \
responsibility contributes infrastructure, composition, or a \
read-dependency slice, but another responsibility is the \
primary owner. Example: a "Background Job Queue" responsibility \
supports every feature that needs async work (it provides the \
execution substrate) but owns none of them (the scheduler, \
generation pipeline, etc. are the owners). Example: a \
"Multi-Project Workspace" view supports a cross-project \
feature by composing data from the review-routing and \
project-provisioning owners — it supports, they own. Use \
``<supports>`` generously when the distinction is real; the \
sysarch pass reads it as a signal of cross-cutting dependency.
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
* **A feature may appear in many ``<supports>`` blocks.** A \
cross-cutting feature ("authentication protects every request") \
may be supported by many responsibilities even though one \
responsibility owns it. This is expected — use ``<supports>`` \
to make the dependency visible rather than hiding it.
* **A feature must not appear in both ``<owns>`` and \
``<supports>`` of the same responsibility.** ``<owns>`` already \
implies supporting presence; duplicating is redundant.
* **Responsibilities do not overlap in scope.** Two \
responsibilities must not claim ownership of the same \
system-side scope even through different feature coverage. The \
single-owner rule catches per-feature collisions; this rule is \
about prose scope. If two resps' intent paragraphs both say \
they own "produce end-of-month statements", that's overlap even \
if they own different features — collapse them into one, or \
redraw the boundary by trigger or data set. Example: "Billing" \
and "Receipts" would overlap if both claimed "produce \
end-of-month statements"; split by trigger instead — Billing \
owns invoice lifecycle, Receipts owns post-payment \
acknowledgments. Each intent paragraph's "does not cover" \
clause should make the boundary between this resp and its \
nearest sibling explicit.
* **Every feature in the input must be owned by some \
responsibility.** Before emitting the list, mentally check that \
each input feature ID appears in exactly one ``<owns>`` block. \
A feature that appears only in ``<supports>`` (or nowhere) is a \
coverage gap — the validator rejects it.
* **Granularity.** Aim for a responsibility list that's coarser \
than the feature list but finer than the project description. \
Err on the side of fewer, coarser responsibilities — \
sub-decomposition happens in a later pass per component.
* **Cross-cutting concerns are responsibilities too.** Logging, \
telemetry, health checks, background job scheduling, rate \
limiting, secrets handling — if the project needs them, name \
them. They won't always appear in the feature list directly, \
but they're real work the system has to do and the sysarch \
pass will want them named up front so cross-cutting policies \
can target them later. Cross-cutting responsibilities still \
need an ``<owns>`` block listing at least one feature they are \
the primary owner of (for purely infrastructural \
responsibilities this may be narrow — a telemetry responsibility \
might own the one "system observability" feature). They \
typically have a large ``<supports>`` block listing every \
feature whose execution they touch.
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
