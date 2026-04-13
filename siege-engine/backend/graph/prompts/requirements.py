"""Prompt template for the requirements (``reqs_*``) draft.

The requirements pass consumes the approved feature set (the
``feat_*`` nodes minted from the feature expansion) and produces a
structured, tag-based list of **top-level responsibilities** that
downstream passes will map onto concrete components. One
responsibility may be implicated by many features and vice versa —
the many-to-many relationship is authored at the sysarch layer,
not here. This pass only names the responsibilities and explains
what they're for.

Output format (parsed by :mod:`backend.graph.parsers.xml_sections`
and validated by :func:`backend.graph.parsers.validators.validate_requirements`):

    <requirements>
      <responsibility>
        <name>User Authentication</name>
        <intent>…paragraph-length description of what this
        responsibility covers, framed at the role level…</intent>
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

SYSTEM_PROMPT = """\
You are a senior software architect helping to decompose a \
project's feature set into top-level **responsibilities** — the \
coarsest building blocks that concrete software components will \
later fulfill. You will be given a list of features (approved in \
an upstream pass) and must produce a structured responsibility \
list.

A responsibility is a **role**, not a thing: "User \
Authentication", "Billing", "Content Storage", "Scheduled Job \
Execution". Each responsibility is something the software must \
*do* regardless of how it ends up being built. Many features may \
share one responsibility (auth is implicated by almost every \
user-facing feature), and one feature may span several \
responsibilities.

# Output format

Output a single ``<requirements>`` block. Nothing else. Inside \
it, each responsibility has exactly one ``<name>`` and exactly \
one ``<intent>``:

    <requirements>
      <responsibility>
        <name>User Authentication</name>
        <intent>Verify the identity of a human or service \
interacting with the system, establish a session, and make the \
identity available to downstream logic. Covers sign-in, sign-out, \
token refresh, and session invalidation, but not the specific \
credential mechanism (password, SSO, passkey) — that's an \
implementation choice settled later.</intent>
      </responsibility>
      <responsibility>
        <name>Authorization</name>
        <intent>Decide whether an authenticated principal may \
perform a given action on a given resource. Separate from \
authentication because the checks apply at every request, not \
just at sign-in, and because the policy surface grows \
independently of the identity surface.</intent>
      </responsibility>
      <responsibility>
        <name>Billing</name>
        <intent>Bill the account owner for usage, collect \
payment, and gate product access based on the current billing \
state. Covers tiered plans, invoices, payment retries, and \
account suspension. Does not cover pricing-model \
decisions.</intent>
      </responsibility>
    </requirements>

# Rules

* Use the tag structure exactly as shown. Each ``<responsibility>`` \
has exactly one ``<name>`` and exactly one ``<intent>``. No other \
tags inside a responsibility.
* ``<name>`` is a short identifier — typically 2 to 5 words, title \
case. Think "User Authentication", "Rate Limiting", "Audit \
Logging", not "The ability to check who a user is."
* ``<intent>`` is a paragraph — typically 2 to 5 sentences. \
Describe the *role* the responsibility plays, the scope it \
covers, and when useful the things it explicitly does **not** \
cover. Avoid prescribing implementation (no "we will use JWT", no \
"this service will expose a REST API").
* **Granularity.** Aim for a responsibility list that's coarser \
than the feature list but finer than the project description. A \
typical project produces 8–20 top-level responsibilities. If \
you're at 40, you're reaching into implementation territory; if \
you're at 3, you're probably glossing over real decomposition \
work. Err on the side of fewer, coarser responsibilities — \
sub-decomposition happens in a later pass per component.
* **Coverage.** Every feature in the input should be implicated \
by at least one responsibility in the output. You do not need to \
write the mapping down in this pass (it's produced by the sysarch \
pass later), but mentally check that "could I route each feature \
to at least one of these responsibilities?" is true before \
emitting the list.
* **Cross-cutting concerns are responsibilities too.** Logging, \
telemetry, health checks, background job scheduling, rate \
limiting, secrets handling — if the project needs them, name \
them. They won't always appear in the feature list directly, but \
they're real work the system has to do and the sysarch pass will \
want them named up front so cross-cutting policies can target \
them later.
* Do not include meta-commentary about what you are doing, what \
the tags mean, or how you arrived at the list. Output only the \
``<requirements>`` block.
* Unescaped ``&`` and ``<`` in the intent text are fine — the \
parser tolerates them.
"""


def render_user_prompt(
    *,
    features_summary: str,
    prior_approved: str | None,
    prior_pending: str | None,
    feedback: str | None,
    parse_error: str | None = None,
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
    """
    parts: list[str] = []
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
            "Regenerate the requirements from scratch based on the "
            "features above. Output only the <requirements> block."
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
    ``name``, ``content`` (the intent paragraph), and optionally
    ``group_label`` (for group grouping in the output). Features
    are rendered in the provided order, grouped by label. Ungrouped
    features land under an implicit "(ungrouped)" heading only if
    there are also grouped features in the same batch — otherwise
    the list is flat.
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
            name = feat.get("name", "").strip() or "(unnamed)"
            intent = (feat.get("content") or "").strip()
            implicit_marker = " (inferred)" if feat.get("is_implicit") else ""
            lines.append(f"- **{name}**{implicit_marker}: {intent}")
        lines.append("")

    return "\n".join(lines).rstrip()
