"""Prompt template for the implementation (``impl_*``) draft.

An impl node is the leaf of the architecture tree. One per
subcomponent; one per un-fanned-out top-level component. It
carries the prose design/build details for that leaf: behavior,
invariants, sequencing, edge cases — the stuff the comparch /
subcomparch docs deliberately left out to keep their compression
tight. See ``docs/architecture/v2-rearchitecture.md``
§Implementation nodes.

Output format (parsed by :mod:`backend.graph.parsers.xml_sections`
and validated by
:func:`backend.graph.parsers.validators.validate_implementation`):

    <implementation>
      <behavior>
      Prose paragraph(s) describing what the leaf does at
      runtime — the control flow, the happy-path operations,
      the observable side effects.
      </behavior>
      <invariants>
      Prose paragraph(s) stating what must hold before / after
      each operation. Typing, ownership, referential
      constraints, state-machine preconditions. Read by the
      plan prompt to know what the code must preserve.
      </invariants>
      <sequencing>
      Prose paragraph(s) on ordering across entry points —
      which operations must run before others, which are
      idempotent, which are order-sensitive.
      </sequencing>
      <edge-cases>
      Prose paragraph(s) naming failure / empty / race
      conditions and the leaf's handling. Every branch the
      implementation must handle should be mentioned.
      </edge-cases>
    </implementation>

Four sections in fixed order. All four are prose blobs — the
validator doesn't parse their contents; the plan prompt
(Phase 14) will consume the whole ``<implementation>`` block
verbatim to translate into (file, region, change) tuples.

Unlike comp / subcomp arch docs, impl does not project fragments.
The whole prose document lives in ``Node.content`` as one blob.
"""

from __future__ import annotations

SYSTEM_PROMPT = """\
You are authoring the **implementation document** for a single \
leaf in the component tree. This is the **last articulation \
layer before code territory**. Your downstream reader is the \
**plan prompt** (Phase 14), which will translate your prose \
into a concrete list of (file, region, change) tuples that the \
code generator will execute.

Your output replaces what used to live in
``<implementation>`` blocks back when the architecture doc \
had one. Distinct from the parent's technical specification so \
that iterating on "what actually happens here" doesn't \
re-thrash the parent's high-level choices.

You will be given the owning component's metadata (name, \
techspec, public surface, private surface), the component's \
external dependencies' public surfaces, and optionally a prior \
approved / pending draft, user feedback, and a parse-validate \
error. You produce a single ``<implementation>`` block \
containing four sections in a fixed order: behavior, \
invariants, sequencing, edge-cases.

# Output format

Emit exactly one ``<implementation>`` block with these four \
children in this order: ``<behavior>`` → ``<invariants>`` → \
``<sequencing>`` → ``<edge-cases>``. Example (abbreviated):

    <implementation>
      <behavior>
    On ``authenticate(credentials)``, hash the presented \
    password with bcrypt (work factor from config), compare \
    against the stored hash, and on success mint a new session \
    token — opaque UUID4 — and persist it with the principal \
    id and a 30-day TTL. On ``resolve_session(token)`` look the \
    token up in the sessions table; if found and not expired, \
    return the principal id; otherwise return None. Logout is \
    a DELETE on the session row.
      </behavior>
      <invariants>
    Every row in the sessions table is keyed by an opaque \
    token and carries a non-null principal id plus an \
    expiration timestamp. No row outlives its expiration — the \
    background reaper deletes expired rows on a 5-minute \
    interval. Principal id is an FK into the users table; \
    cascade-delete fires when the user is deleted. Passwords \
    never leave this leaf in plaintext.
      </invariants>
      <sequencing>
    Session rotation on activity is best-effort: rotate at \
    read time if the session is older than 24 hours, but \
    never block the read on rotation. The reaper runs in its \
    own task; it holds no lock on active reads. Logout \
    completes synchronously before responding to the client.
      </sequencing>
      <edge-cases>
    Bcrypt hash mismatch returns an opaque "invalid \
    credentials" error without revealing whether the username \
    exists. Expired token lookup returns None, not an error. \
    Concurrent logout + rotation on the same token is safe: \
    the DELETE wins, the rotation becomes a no-op. Database \
    unreachable surfaces as a 503 to the caller.
      </edge-cases>
    </implementation>

# Rules

## Structure

* Emit **exactly one** ``<implementation>`` root block. Nothing \
before, nothing after.
* The four children **must appear in this order**: \
``<behavior>`` → ``<invariants>`` → ``<sequencing>`` → \
``<edge-cases>``. Out-of-order sections are a structural error.
* No unknown top-level children under ``<implementation>``.

## Content

* Each section is **non-empty prose**. Plain paragraphs, or \
short bulleted lists inside the prose where they help \
readability. Don't use fenced code blocks — code generation is \
the plan prompt's job, not yours.
* ``<behavior>`` is what the leaf **does** at runtime. Name the \
operations, the persistent state they touch, the side effects \
they produce. If a caller invokes a method on this leaf's \
public surface, this section should make clear what happens \
step-by-step.
* ``<invariants>`` is what must **hold** — before any operation, \
after any operation, at all times. Data-shape invariants, \
ownership rules, referential constraints, state-machine \
preconditions. The plan prompt reads this to know what the \
code must preserve under edits.
* ``<sequencing>`` is about **ordering**: which operations must \
precede which, which are idempotent, which are order-sensitive, \
which run in background tasks vs synchronously. Concurrency \
and task scheduling live here.
* ``<edge-cases>`` names the failure / empty / race / \
boundary conditions and the leaf's handling. Every branch the \
implementation must cover should be mentioned. "It panics" is \
a valid answer; "we don't handle that" is not — if you're not \
handling it, say so and state the assumption that makes it \
safe.

## Style

* Prose, not pseudocode. The plan prompt is a strong reader; \
it will translate your prose into code structure. Don't try to \
pre-write code here — that's the plan's job and your code \
would clash with the project's conventions.
* Name specific types, specific operations, specific failure \
modes when they're project-distinctive. Avoid generic language \
that could describe any module.
* Don't restate the parent component's public surface — the \
plan prompt reads that separately. Focus on what this leaf \
*internally* does and guarantees.
* Unescaped ``&`` and ``<`` in prose are fine — the parser \
tolerates them.

## Implementation scope

* You are describing one leaf. Don't describe sibling leaves or \
the parent component's other slices. If you need to reference \
them, name the dependency's public surface and leave the \
internals to them.
* If the leaf's behavior spans multiple entry points, cover \
all of them in ``<behavior>`` — don't treat one as primary and \
the others as footnotes.
* Keep it proportionate to the leaf's complexity. A simple \
cache wrapper doesn't need 2000 words; a session-management \
engine does. Pad isn't helpful; underspecifying is worse.
"""


def render_user_prompt(
    *,
    owner_summary: str,
    parent_summary: str,
    dep_pubapi_summary: str,
    prior_approved: str | None,
    prior_pending: str | None,
    feedback: str | None,
    parse_error: str | None = None,
    vocab_summary: str = "",
    referenced_content_summary: str = "",
) -> str:
    """Build the user prompt for the impl generator.

    - ``owner_summary``: this leaf's own name + role +
      public/private surface summary (from the leaf's own
      comparch / subcomparch fragments).
    - ``parent_summary``: the owning parent component's
      techspec + public surface + private surface. Empty for
      un-fanned-out top-level impls (they are their own parent).
    - ``dep_pubapi_summary``: public surfaces of the leaf's
      dependencies. Scope is inherited: for subcomponent impls,
      includes same-parent siblings + parent's external deps;
      for top-level impls, the comp's own outbound deps.
    - ``prior_approved`` / ``prior_pending`` / ``feedback`` /
      ``parse_error``: standard regen/retry context.
    - ``vocab_summary`` / ``referenced_content_summary``:
      cross-cutting context shared with other tiers.
    """
    parts: list[str] = []
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
    parts.append("# Implementation leaf")
    parts.append("")
    parts.append(owner_summary.strip() or "(leaf details missing)")
    parts.append("")

    if parent_summary and parent_summary.strip():
        parts.append("# Owning parent component")
        parts.append("")
        parts.append(parent_summary.strip())
        parts.append("")

    if dep_pubapi_summary and dep_pubapi_summary.strip():
        parts.append("# Dependencies' public surfaces")
        parts.append("")
        parts.append(dep_pubapi_summary.strip())
        parts.append("")

    if prior_approved:
        parts.append("# Previously-approved implementation")
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
            "<implementation> block. The specific error was:"
        )
        parts.append("")
        parts.append(f"> {parse_error.strip()}")
        parts.append("")
        parts.append(
            "Fix the structure and re-emit the full <implementation> "
            "block. Preserve the content where the error is purely "
            "structural; this retry is about format."
        )
        parts.append("")

    parts.append("# Task")
    parts.append("")
    if parse_error:
        parts.append(
            "Re-emit the implementation as a valid <implementation> "
            "block addressing the structural error above. Output "
            "only the corrected <implementation> block."
        )
    elif feedback and (prior_pending or prior_approved):
        parts.append(
            "Revise the implementation to address the user feedback "
            "above. Preserve structure where the feedback does not "
            "request changes. Output only the revised "
            "<implementation> block."
        )
    elif prior_pending or prior_approved:
        parts.append(
            "Regenerate the implementation from scratch. Output only the <implementation> block."
        )
    else:
        parts.append(
            "Write the initial implementation document for this "
            "leaf. Output only the <implementation> block."
        )

    return "\n".join(parts).rstrip() + "\n"
