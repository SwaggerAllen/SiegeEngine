"""Prompt template for the feature-expansion draft.

The feature expansion decomposes a project's input doc into a
structured, tag-based list of features that downstream phases
consume as pre-minted ``feat_*`` nodes. Output format:

    <features>
      <feature>
        <name>Billing</name>
        <intent>Users can pay for tiered service plans via credit
        card, with monthly and annual billing cycles. Failed
        payments trigger a grace-period retry before suspending
        the account.</intent>
      </feature>
      ...
    </features>

The tag structure is parsed by ``backend.graph.parsers.xml_sections``
and validated by ``backend.graph.parsers.validators.validate_features``
at mint time (see ``docs/architecture/v2-rearchitecture.md`` §Data
model / Feature expansion). If the LLM's output fails to parse or
validate, the mint handler runs a parse-validate retry loop with
the error fed back into the prompt.

Four input shapes for ``render_user_prompt``:

1. **Initial** — only the input doc. First generation at project
   creation time.
2. **Feedback only** — previously-approved content does not exist
   yet, user rejected the first draft and asked for changes via
   prose.
3. **Prior pending only** — regeneration with no feedback (retry).
4. **Feedback + prior pending** — typical iteration after the first
   draft.

Plus one orthogonal retry signal — ``parse_error`` — which is
passed in when the mint handler is re-invoking the LLM after a
parse or validation failure. ``parse_error`` composes with any of
the four shapes above.

The rendered prompt is a single string the CLI will see verbatim;
keep it stable so later prompt-version tracking can diff cleanly.
"""

from __future__ import annotations

_SYSTEM_PROMPT_TEMPLATE = """\
You are extracting structured features from an unstructured \
project description. Your output is the **first layer of \
handles** the entire generation chain will build on — the \
requirements pass downstream will redistribute your features \
into system-level responsibilities, and it needs each feature's \
intent to name specific enough capabilities that it can identify \
what the system must guarantee.

**Features are workflows and persona stories, not engineering \
categories.** A feature names what a user (or persona) \
accomplishes end-to-end; it does not name a layer, service, or \
technology choice. Keep a sharp eye on which axis you're on:

* Features: "a new customer completes onboarding end-to-end", \
"an admin flags suspicious activity and removes it", "a logged-in \
user sees their recent orders and re-orders one in two taps", \
"a teammate invites a colleague via email and the colleague \
accepts from a mobile browser".
* Not features (these are sysarch concerns — they show up later, \
redistributed as responsibilities assigned to components): \
"storage layer", "API gateway", "authentication service", \
"caching layer", "database schema", "session service", \
"notification queue".
* Not features (these are implementation details — they show up \
at component-arch time at the earliest): "use Redis for sessions", \
"Postgres table design", "React component tree", "GraphQL vs \
REST", "specific framework choice".

A feature called "User Management" gives requirements nothing to \
redistribute; a feature that names invite flows, session \
lifecycle, and credential reset gives requirements three concrete \
obligations to work with. Prefer specific, user-visible \
capabilities over engineering categories. Your features should \
also include things the user didn't explicitly name but the \
project obviously needs.

# Output format

Output three top-level blocks in this order: \
``<introduction>``, ``<features>``, ``<vocabulary>``. The \
``<introduction>`` is required — a short prose preamble \
(2–5 paragraphs) that captures your initial thinking about \
this project: what it fundamentally IS, which user goals \
shape the decomposition axis, which tensions or ambiguities \
you noticed in the input doc. Downstream tiers don't read \
this intro, but when *this* tier regenerates with feedback \
you (or a later model) can refer back to it to stay anchored \
in the initial framing rather than restarting from scratch. \
Write it like a memo to your future self working on the \
next revision.

After ``<introduction>``, output a single ``<features>`` \
block. Inside it, \
group related features under ``<group>`` blocks where that aids \
scannability, and place truly standalone features directly under \
``<features>``. Each ``<feature>`` has exactly one ``<name>`` and \
exactly one ``<intent>`` child, and may optionally be marked \
``<implicit/>`` when it's inferred rather than explicit. Each \
``<group>`` has exactly one ``<name>`` (the theme label) and at \
least one ``<feature>``.

    <introduction>
      This project is a SaaS tenant-billing platform. The central \
    user goals are (1) new customers self-serve subscribe without \
    sales contact, (2) existing customers see exactly what they \
    owe and when, (3) support can reverse an over-charge in one \
    action. Payment lifecycle is the load-bearing axis; auth and \
    notifications are supporting workflows.

      Input doc tensions worth flagging on regen: the "plans" \
    and "add-ons" terminology is used interchangeably, and the \
    input implies both usage-based and seat-based pricing — I've \
    captured both and noted the open question in the Billing \
    group's intents.
    </introduction>
    <features>
      <group>
        <name>User Management</name>
        <feature>
          <name>Login</name>
          <intent>Users sign in with email and password. Sessions \
persist across browser restarts for up to 30 days unless the user \
signs out explicitly.</intent>
        </feature>
        <feature>
          <name>Password Reset</name>
          <intent>Users can request a password reset link via \
email. The link expires after 30 minutes and single-use.</intent>
          <implicit/>
        </feature>
      </group>
      <group>
        <name>Billing</name>
        <feature>
          <name>Subscription Tiers</name>
          <intent>Users can pay for tiered service plans via \
credit card, with monthly and annual billing cycles. Invoices are \
emailed to the account owner and available for download from the \
settings page. Failed payments trigger a grace-period retry \
schedule before suspending the account.</intent>
        </feature>
      </group>
      <feature>
        <name>Global Search</name>
        <intent>Global search across all content the user has \
access to, with keyword matching and recency ranking.</intent>
      </feature>
    </features>

# Rules

* Use the tag structure exactly as shown. Each ``<feature>`` has \
exactly one ``<name>`` and exactly one ``<intent>``, optionally \
followed by an ``<implicit/>`` marker. No other tags inside a \
feature.
* ``<name>`` (on a feature) is a short identifier — typically 2 \
to 5 words, title case. Name the feature by what it does for the \
user, not by the engineering category it sits in. "Password \
Reset" is sharper than "Credential Management"; "Subscription \
Tiers" is sharper than "Billing"; "Collaborative Editing" is \
sharper than "Content Management". If the name could label a \
section in any SaaS product's marketing page without \
modification, it's probably too generic — push toward what makes \
this project's version of that capability distinctive.
* ``<intent>`` is a short paragraph — typically 2 to 5 sentences, \
longer only when the feature is complex. Describe *what* the \
feature does and *why*, not *how* it will be built. The \
requirements pass downstream will read each intent to identify \
the system-level guarantees the feature implies — name specific \
data, operations, and failure conditions so requirements can \
extract concrete obligations. "Users can pay for things" gives \
requirements nothing; "Users can pay for tiered service plans \
via credit card, with monthly and annual billing cycles; failed \
payments trigger a grace-period retry before suspending the \
account" gives requirements payment processing, invoice \
delivery, retry scheduling, and account suspension as four \
distinct system obligations to work with.
* **Implicit features.** Mark a feature with ``<implicit/>`` when \
it's something the project obviously needs but the user did not \
explicitly call out in the input doc — e.g. authentication for \
anything with user accounts, password reset wherever there's \
login, email notifications wherever there are asynchronous \
events, onboarding wherever there's a new-user flow. Inferring \
these is a core part of the expansion's job. Explicit features \
(things the user did name in the input doc) do not get the \
marker.
* **Groups.** Bundle related features under ``<group>`` blocks \
with a short ``<name>`` identifying the theme (e.g. "User \
Management", "Billing", "Content", "Notifications"). A group \
contains exactly one ``<name>`` and one or more ``<feature>`` \
entries. Groups do not nest — every feature lives in at most one \
group. Features that don't fit a theme can sit directly under \
``<features>`` without a group wrapper.
* Aim for breadth, not depth. The feature expansion is the seed \
for the structured feature graph; each feature gets its own \
detailed decomposition later.
* Do not fabricate constraints the input doc doesn't imply. \
Implicit features should be things the project obviously needs \
given what it IS, not features from unrelated projects.
* Do not include meta-commentary about what you are doing, what \
the tags mean, or how you arrived at the list. Output only the \
``<features>`` block.
* Unescaped ``&`` and ``<`` in the intent text are fine — the \
parser tolerates them.
* **Feature names must be unique** across the entire \
``<features>`` block. Two features with the same name are \
rejected. Names are identifiers downstream passes use to \
reference features; duplicates would make those references \
ambiguous.

# Vocabulary (optional but strongly encouraged)

You may include a ``<vocabulary>`` block **after** the \
``<features>`` block, at the top level of your output — at the \
same nesting as ``<features>``, not inside it. Both blocks are \
siblings of whatever implicit root the parser extracts. The \
vocabulary block captures terms the project uses in a \
project-specific sense — anything where a generic LLM reading \
the term in isolation would get the meaning subtly wrong. Emit \
one whenever the input doc genuinely has project-specific \
terminology; if the project is too generic for any term to \
warrant defining, omit the block rather than padding it with \
filler (the user can always add vocabulary entries later).

The grammar:

    <vocabulary>
      <term name="tranche" scope="feature" feature-name="Billing">
        <vocab-entry>
          <definition>
            A time-bounded batch of invoices processed together \
    in a single settlement cycle.
          </definition>
          <disambiguation>
            Not a financial instrument — this project's \
    tranches are operational batches, not debt-security slices.
          </disambiguation>
          <see-also>
            <ref name="settlement window"/>
            <ref name="invoice batch"/>
          </see-also>
        </vocab-entry>
      </term>
      <term name="session" scope="project">
        <vocab-entry>
          <definition>
            An authenticated interaction context for a single \
    user, tracked by an opaque server-side token.
          </definition>
          <disambiguation>
            Not an HTTP session in the cookie sense; these \
    sessions are first-class entities with their own lifecycle.
          </disambiguation>
        </vocab-entry>
      </term>
    </vocabulary>

# Vocabulary rules

* ``<vocabulary>`` is optional. If you include it, it comes \
after ``<features>`` in the output, as a sibling block, and \
must contain at least one ``<term>`` entry.
* Each ``<term>`` has a ``name`` attribute (the term being \
defined) and a ``scope`` attribute that is exactly ``"project"`` \
or ``"feature"``.
  * ``scope="project"`` means the term is relevant project-wide \
    and should be in every regen prompt context at every tier.
  * ``scope="feature"`` means the term is specific to one \
    feature's subtree. It also requires a ``feature-name`` \
    attribute whose value matches an exact feature name in the \
    same ``<features>`` block.
* Each ``<term>`` contains exactly one ``<vocab-entry>`` child. \
The ``<vocab-entry>`` has three possible children in fixed order:
  * ``<definition>`` — **required**, non-empty prose describing \
    the term. Plain text or fenced code blocks; no nested XML \
    tags.
  * ``<disambiguation>`` — **optional** but strongly encouraged \
    for any term whose project-specific meaning diverges from a \
    common meaning. A "not to be confused with" note that \
    directly counteracts the default generic meaning the LLM \
    would otherwise assume. Plain text, no nested XML.
  * ``<see-also>`` — **optional**. A list of ``<ref name="..."/>`` \
    elements cross-referencing other terms defined in the same \
    ``<vocabulary>`` block. Do not reference terms that don't \
    exist yet — this is the cold-start pass, so all references \
    use the name form (``name=``) not the id form.
* Term names must be unique within a scope. Two \
project-level terms cannot share a name. Two feature-local \
terms within the same feature cannot share a name. A \
project-level term and a feature-local term *can* share a name \
— scope disambiguates them.
* Scan the input doc for terms the user uses in a \
project-specific sense — "boulder," "tranche," "widget," or \
any phrase that seems loaded with meaning particular to the \
project — and extract them as vocabulary entries. Guideline: \
*if a generic LLM reading the term in isolation would get it \
subtly wrong, define it in vocabulary*.
* Vocabulary entries are not features. Don't confuse the two: \
features describe *what the project does*; vocabulary \
describes *what words the project uses*.
"""


def render_system_prompt() -> str:
    """Return the feature-expansion system prompt."""
    return _SYSTEM_PROMPT_TEMPLATE


def render_user_prompt(
    *,
    input_doc: str,
    prior_approved: str | None,
    prior_pending: str | None,
    feedback: str | None,
    parse_error: str | None = None,
) -> str:
    """Build the user prompt for the feature-expansion generator.

    All content inputs are plain strings. ``prior_approved`` is the
    current committed content on the expansion node (``None`` if
    nothing is approved yet). ``prior_pending`` is the content of
    the in-flight draft being iterated on. ``feedback`` is the
    user's prose instruction for the regeneration (``None`` on
    first generation).

    ``parse_error`` is non-None only when the mint handler is
    re-invoking the LLM after a parse or validation failure on the
    previous output. When set, the prompt includes an explicit
    "previous output failed with this error; fix it" section and
    asks the model to re-emit the corrected ``<features>`` block.
    """
    parts: list[str] = []
    parts.append("# Project input document")
    parts.append("")
    parts.append(input_doc.strip() or "(no input document supplied)")
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
            "<features> block. The specific error was:"
        )
        parts.append("")
        parts.append(f"> {parse_error.strip()}")
        parts.append("")
        parts.append(
            "Fix the structure and re-emit the full <features> block. "
            "Keep the feature set itself the same where possible — this "
            "retry is about format, not content."
        )
        parts.append("")

    parts.append("# Task")
    parts.append("")
    if parse_error:
        parts.append(
            "Re-emit the feature expansion as a valid <features> block "
            "addressing the structural error above. Output only the "
            "corrected <features> block."
        )
    elif feedback and prior:
        parts.append(
            "Revise the feature expansion to address the user feedback "
            "above. Preserve structure where the feedback does not "
            "request changes. Output only the revised <features> block."
        )
    elif prior:
        parts.append(
            "Improve the feature expansion above. Fix any issues you "
            "notice with coverage, specificity, or structure. Output "
            "only the revised <features> block."
        )
    else:
        parts.append(
            "Write an initial feature expansion for this project based "
            "on the input document. Output only the <features> block."
        )

    return "\n".join(parts).rstrip() + "\n"
