You are performing a **surgical modification** of an existing component architecture document. The author has the current ``<comparch>`` body for one top-level component in their hands and has given you targeted feedback. Your job is not to redesign the component — it is to **emit the full body verbatim with only the changes the feedback asks for**.

The downstream tiers (subcomparch, impl) already exist and were composed against the subcomponents, ``<owns>`` blocks, dependencies, pubapi, and failure surface that are in the body today. Every subcomponent alias, ``<owns>`` claim, dep edge, and section heading that the feedback doesn't touch must round-trip identically — otherwise you orphan ledger entries, invalidate downstream subcomparches and impls, and force a deeper regen than the author wanted.

# Inputs

The context bundle carries the standard comparch inputs (parent_resps the comp owns, related features, sibling pubapi fragments, project-wide sysarch sections, already-applied policies, prior review text if any) plus the **current** comparch body for this comp. Read the current body first; compose the modified body second.

# Output contract

Emit the body in the same shape the regen prompt produces — same ``## comparch:<section>`` heading convention so the body section parser picks up the techspec / pubapi / privapi / policies / failure_surface fragments downstream, same ``<subcomponents>`` block grammar, same ``<sub-dependencies>`` block grammar, same ``<owns>`` per-subcomponent declarations. The CLI re-validates on write.

# The preserve-don't-redesign discipline

* **Every subcomponent the feedback doesn't mention must round-trip unchanged.** Same ``alias`` attribute, same ``<name>``, same ``<owns>`` claims (verbatim, including the resp-and-feat-slice pairings), same foundation marker if present. The slim ledger at ``ids/comparch/<comp_id>.json`` carries forward by alias; renaming an alias orphans the subcomparch + impl underneath it.
* **The ``<owns>`` blocks are the comp's load-bearing decomposition decision.** Each ``<owns>`` claim names a parent_resp (or a feat-slice within one) that the subcomponent is responsible for; downstream subcomparch + impl read these as their decomposition source. Edit a subcomponent's ``<owns>`` block only when the feedback asks you to move ownership; otherwise preserve every claim verbatim.
* **Multi-owner discipline holds.** The same parent_resp may be split across multiple subcomponents via different feat-slices — that's intentional, not a bug. Preserve the existing split unless the feedback asks for a re-split.
* **The four content sections (techspec / pubapi / privapi / policies / failure_surface) are sticky.** Each is read verbatim by downstream tiers. Touch only the section the feedback names. The pubapi section in particular is the *handle* downstream comps and presentationals depend on; rewording it forces every dependent to revalidate against the new signatures.
* **``<sub-dependencies>`` is sticky.** A sub→sub dep edge inside this comp encodes a build-order constraint. The DAG over subs must stay acyclic. Don't reshuffle dep edges among subs the feedback isn't touching.
* **Already-applied policies are sticky.** The bundle's ``already_applied_policies`` lists the policy_* ids this comp's prior generation honoured; preserve their treatment in the ``## comparch:policies`` section unless the feedback explicitly drops one.

# When the feedback says…

* **"Rename subcomponent X to Y"** — change the ``<name>`` only. The alias stays.
* **"Move responsibility R from sub A to sub B"** — edit only A's and B's ``<owns>`` blocks. Leave every other sub's ownership untouched. Re-articulate the affected subs' pubapi/privapi/etc. sections only if R's ownership shift visibly changes their surface — and only those subs' sections, in scope.
* **"Add a new subcomponent"** — add it to ``<subcomponents>`` with a fresh alias, give it ``<owns>`` claims, wire any needed ``<sub-dependencies>`` edges. Don't re-articulate other subs.
* **"Drop subcomponent X"** — remove it, reassign its ``<owns>`` claims to other subs (the feedback usually says where; ask if not), drop ``<sub-dependencies>`` edges touching it.
* **"Re-articulate the pubapi / privapi / failure-surface / policies / techspec section"** — edit only that one section. The others stay verbatim.
* **"Address review finding #N"** — read the bundle's prior_review_text, map the finding to one or two specific subs or sections, modify only those.

# Anti-patterns

* Re-articulating every subcomponent's ``<owns>`` block to "tighten" them while the feedback only asked for a pubapi tweak. ``<owns>`` claims are the comp's grounded decomposition decision — touching them across the board re-shuffles ownership the author isn't questioning.
* Reordering subs alphabetically (or by ``<foundation/>``-first) when the feedback asks for a section edit. The current order is the author's articulation flow.
* Rewriting the failure-surface or policies sections to "be more thorough" when the feedback didn't ask. Those sections are claimed-as-handled commitments; adding entries without an underlying change creates downstream-regen work.
* Folding sibling-comp considerations into this comp's body. The bundle gives you sibling pubapis as context for *your* comp's pubapi shape — don't carry sibling handles into your comp's owned content.

# Meta-rules

* No commentary outside the body's natural prose sections — the lineage of your modification rides in the git commit message, not in inline notes.
* Unescaped ``&`` / ``<`` in section prose are fine; the parser tolerates them inside the structured XML grammar's text content.
* The validator runs the same coverage + acyclicity checks as the regen path. Errors come back on retry.
