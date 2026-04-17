"""Prompt template for the domain fan-in (``fanin_*``) synthesis.

Fan-in is the bottom-up counterpart to a domain component's
top-down architecture doc. It exists once per fanned-out domain
comp and sits at the bottom of its subtree. Its job is to
articulate — after all the subs' impls have been approved — what
this component, **as built**, actually exposes and does at the
component level.

The architecture doc (comparch) says what the component was
**meant** to do. The fan-in says what the subs collectively
**did**. The two views are consumed side-by-side by downstream
presentational components' comparch / subcomparch regen, so
drift between the contract and the built reality surfaces at
the presentational layer.

Fan-in has **no draft lifecycle**. The handler calls the LLM,
validates the output, and overwrites ``Node.content`` directly
via a dedicated ``FanInContentUpdated`` event. No approve /
reject UI. Real edits happen at the impl tier below; fan-in
regens mechanically on impl approval.

Output format (parsed by :mod:`backend.graph.parsers.xml_sections`
and validated by
:func:`backend.graph.parsers.validators.validate_fanin`):

    <fanin>
      <summary>
      One-paragraph articulation of what this component, as built,
      exposes and does at the component level. The
      "synthesis-of-what-exists" framing — not "what we meant
      to build", but "what the subs collectively ended up
      doing".
      </summary>
      <exposed-surface>
      Pubapi-shaped prose naming every operation, entity, and
      event the subs collectively surface upward. Reads like a
      public-surface fragment but is written from the impls,
      not from the contract.
      </exposed-surface>
      <realized-behavior>
      How the subs compose to produce the component-level
      behavior: sequencing across subs, invariants that span
      subs, observable behavior at the component boundary.
      </realized-behavior>
    </fanin>

Three sections in fixed order. All three are prose blobs — the
validator enforces presence + order but doesn't parse the
contents. The downstream reader (a presentational comparch /
subcomparch regen) consumes the whole ``<fanin>`` block as
bottom-up context alongside the domain spec.
"""

from __future__ import annotations

SYSTEM_PROMPT = """\
You are writing the **domain fan-in synthesis** for a single \
fanned-out component. This is a **bottom-up articulation** of \
what the component, **as built**, exposes and does at the \
component level, synthesized from its subcomponents' approved \
implementations and public surfaces.

Your downstream reader is the **presentational regeneration \
prompt**. When a presentational component that points at this \
domain comp via a ``domain_parent`` edge regenerates, it sees \
your output side-by-side with the domain comp's own technical \
specification and public surface. The domain spec describes \
**what was intended**; your fan-in describes **what exists**. \
Any drift between the two is a signal the presentational \
layer must address — but that's the presentational's job, not \
yours. Your job is purely to describe what exists.

# What you are NOT doing

You are **not** reconciling against a contract. You do not see \
the owning component's own technical specification or public \
surface, and you do not have access to the top-down design \
intent. Do not hedge with "per the design" or "as specified" \
phrasing — you don't know what was specified, and that framing \
leaks a contract you can't see into synthesis you can.

You are **not** prescribing changes. Describe the current \
state. Whether the current state is right or wrong is the \
presentational regen's problem.

You are **not** explaining internals. You describe what the \
component exposes and does **at the component boundary** — the \
shape visible to a consumer of the whole component. Internal \
sub-to-sub sequencing is in scope only as it affects observable \
behavior at that boundary.

# Inputs you receive

You are given:

1. The owning component's name + id (a handle, not a spec).
2. Each **direct subcomponent's public surface** — the pubapi \
fragment each sub exposes to callers.
3. Each **implementation document** under the component's \
subtree — the ``<implementation>`` blocks that describe each \
sub's behavior, invariants, sequencing, and edge-cases.

Synthesize those three inputs into a single ``<fanin>`` block.

# Output format

Emit exactly one ``<fanin>`` block with these three children in \
this order: ``<summary>`` → ``<exposed-surface>`` → \
``<realized-behavior>``. Example (abbreviated):

    <fanin>
      <summary>
    Session management for the whole application. Maintains a \
    persistent session store with token-indexed rows, offers \
    authenticate / resolve / logout entry points, and runs a \
    background reaper that evicts expired rows on a fixed cadence. \
    Passwords never leave the boundary in plaintext.
      </summary>
      <exposed-surface>
    Callable entry points exposed by the component as a whole:

    - ``authenticate(credentials)`` — returns an opaque session \
    token on success, raises a generic "invalid credentials" \
    error on failure.
    - ``resolve_session(token)`` — returns the principal id \
    bound to a live session, or None for unknown / expired tokens.
    - ``logout(token)`` — deletes the session row synchronously.

    No events are emitted at the component boundary. The reaper \
    is internal.
      </exposed-surface>
      <realized-behavior>
    Authentication flows through the credential-check sub first, \
    which hashes and compares the presented password, then \
    invokes the token-mint sub to produce an opaque UUID4 and \
    write the session row. Resolution reads directly from the \
    session-store sub, bypassing the credential-check sub. The \
    reaper sub holds no lock on active reads; logout wins over \
    concurrent rotation because the DELETE path is unconditional. \
    The component as a whole is safe to call concurrently on \
    distinct tokens; same-token concurrency is resolved by \
    last-writer-wins at the session-store layer.
      </realized-behavior>
    </fanin>

# Rules

## Structure

* Emit **exactly one** ``<fanin>`` root block. Nothing before, \
nothing after.
* The three children **must appear in this order**: \
``<summary>`` → ``<exposed-surface>`` → ``<realized-behavior>``. \
Out-of-order sections are a structural error.
* No unknown top-level children under ``<fanin>``.

## Content

* Each section is **non-empty prose**. Plain paragraphs, or \
short bulleted lists inside the prose where they help \
readability. Code-shaped content in the ``<exposed-surface>`` \
section is fine as inline formatting; you do not need to emit \
full fenced code blocks.
* ``<summary>`` is one paragraph — a reader should be able to \
understand what the component does at the boundary from this \
section alone. No meta-commentary about the synthesis process.
* ``<exposed-surface>`` lists **every** operation / entity / \
event visible at the component boundary. Pull these from the \
**public surfaces** of the subs, not their private surfaces \
or impl internals. If two subs surface the same operation, \
describe it once at the component level.
* ``<realized-behavior>`` describes how the subs **compose** — \
which sub invokes which, sequencing that spans subs, \
invariants that only hold at the component level (not within \
any single sub), and behavior observable to a caller of the \
whole component. Do not re-describe a single sub's internal \
behavior unless that behavior is externally observable at the \
component boundary.

## Style

* Describe **what exists**. Do not hedge ("the component \
appears to", "it seems that"). The impls are authoritative — \
articulate them directly.
* Do not reference the top-down design intent. You don't see \
it, and you shouldn't claim you do.
* Name specific operations, types, and failure modes when they \
show up in the impls. Avoid generic language that could \
describe any component.
* Unescaped ``&`` and ``<`` in prose are fine — the parser \
tolerates them.

## Scope

* Describe **this** component's fan-in only. Do not describe \
parent or sibling components, even if they are dependencies — \
those have their own fan-ins.
* If the subs contradict each other (e.g. two subs surface \
operations with incompatible contracts), describe both \
realities as-is. Reconciliation is not your job; surfacing \
the reality is.
"""


def render_user_prompt(
    *,
    owner_summary: str,
    sub_pubapi_fragments: list[dict[str, str]],
    impl_contents: list[dict[str, str]],
    vocab_summary: str = "",
    referenced_content_summary: str = "",
) -> str:
    """Build the user prompt for the fan-in synthesizer.

    - ``owner_summary``: the owning component's name + id — just
      a handle, not a spec. The fan-in is bottom-up and does not
      see the component's own techspec / pubapi.
    - ``sub_pubapi_fragments``: list of ``{"sub_name", "sub_id",
      "pubapi"}`` dicts, one per direct subcomponent. Empty
      pubapi strings are dropped at render time.
    - ``impl_contents``: list of ``{"owner_name", "owner_id",
      "content"}`` dicts, one per impl in the component's
      subtree. For a fanned-out comp, these are the per-sub
      impls. Empty content strings are dropped.
    - ``vocab_summary`` / ``referenced_content_summary``:
      cross-cutting context shared with every other tier's
      regen prompt.

    There is no prior-approved / prior-pending / feedback
    threading — fan-in has no draft lifecycle. ``parse_error``
    is threaded to support the parse-validate retry loop but
    there is no feedback path.
    """
    return _render_user_prompt_impl(
        owner_summary=owner_summary,
        sub_pubapi_fragments=sub_pubapi_fragments,
        impl_contents=impl_contents,
        vocab_summary=vocab_summary,
        referenced_content_summary=referenced_content_summary,
        parse_error=None,
    )


def render_user_prompt_with_retry(
    *,
    owner_summary: str,
    sub_pubapi_fragments: list[dict[str, str]],
    impl_contents: list[dict[str, str]],
    vocab_summary: str = "",
    referenced_content_summary: str = "",
    parse_error: str | None = None,
) -> str:
    """Same as ``render_user_prompt`` but accepts a ``parse_error``.

    Used by the parse-validate retry loop in
    :mod:`backend.graph.handlers.fanin_generation` — on retry,
    the loop feeds the previous attempt's validation error back
    into the prompt so the LLM can correct the structural issue.
    """
    return _render_user_prompt_impl(
        owner_summary=owner_summary,
        sub_pubapi_fragments=sub_pubapi_fragments,
        impl_contents=impl_contents,
        vocab_summary=vocab_summary,
        referenced_content_summary=referenced_content_summary,
        parse_error=parse_error,
    )


def _render_user_prompt_impl(
    *,
    owner_summary: str,
    sub_pubapi_fragments: list[dict[str, str]],
    impl_contents: list[dict[str, str]],
    vocab_summary: str,
    referenced_content_summary: str,
    parse_error: str | None,
) -> str:
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

    parts.append("# Owning component")
    parts.append("")
    parts.append(owner_summary.strip() or "(owner details missing)")
    parts.append("")

    parts.append("# Subcomponent public surfaces")
    parts.append("")
    rendered_pubapis = _render_sub_pubapi_block(sub_pubapi_fragments)
    parts.append(rendered_pubapis or "(no subcomponent public surfaces available)")
    parts.append("")

    parts.append("# Implementations")
    parts.append("")
    rendered_impls = _render_impl_block(impl_contents)
    parts.append(rendered_impls or "(no implementation documents available)")
    parts.append("")

    if parse_error:
        parts.append("# Previous output failed structural validation")
        parts.append("")
        parts.append(
            "Your previous response did not parse into a valid "
            "<fanin> block. The specific error was:"
        )
        parts.append("")
        parts.append(f"> {parse_error.strip()}")
        parts.append("")
        parts.append(
            "Fix the structure and re-emit the full <fanin> block. "
            "Preserve the content where the error is purely "
            "structural; this retry is about format."
        )
        parts.append("")

    parts.append("# Task")
    parts.append("")
    if parse_error:
        parts.append(
            "Re-emit the fan-in synthesis as a valid <fanin> block "
            "addressing the structural error above. Output only "
            "the corrected <fanin> block."
        )
    else:
        parts.append(
            "Write the fan-in synthesis for this component. "
            "Describe what the subs collectively expose and do at "
            "the component boundary — bottom-up, grounded in the "
            "impls and public surfaces above. Output only the "
            "<fanin> block."
        )

    return "\n".join(parts).rstrip() + "\n"


def _render_sub_pubapi_block(entries: list[dict[str, str]]) -> str:
    """Render each sub's pubapi fragment as a labeled subsection."""
    sections: list[str] = []
    for entry in entries:
        name = (entry.get("sub_name") or "").strip() or "(unnamed)"
        sub_id = (entry.get("sub_id") or "").strip()
        body = (entry.get("pubapi") or "").strip()
        if not body:
            continue
        header = f"## {name} (`{sub_id}`)" if sub_id else f"## {name}"
        sections.append(f"{header}\n\n{body}")
    return "\n\n".join(sections)


def _render_impl_block(entries: list[dict[str, str]]) -> str:
    """Render each impl's content as a labeled subsection."""
    sections: list[str] = []
    for entry in entries:
        name = (entry.get("owner_name") or "").strip() or "(unnamed)"
        owner_id = (entry.get("owner_id") or "").strip()
        body = (entry.get("content") or "").strip()
        if not body:
            continue
        header = f"## {name} (`{owner_id}`)" if owner_id else f"## {name}"
        sections.append(f"{header}\n\n{body}")
    return "\n\n".join(sections)
