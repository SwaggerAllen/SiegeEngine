# Catapult — Default bundle examples and flow sketches

**Status:** working file. YAML examples for tier, edge,
fragment, context, and flow declarations, plus the working
sketches for each of the default bundle's six flows.

This file is reference content for the platform spec
(`catapult-spec-v3.md`) and the default bundle spec
(`catapult-default-bundle-v3.md`). Feature_expansion and
sysarch don't read it — examples and sketches burn tokens
during extraction without informing it. Bundle authors read
it; implementers read it; the platform's own components
attach it via `reference` edges from the default-bundle
feature node.

---

# Part 1 — Schema declaration examples

YAML sketches illustrating the four reactive-schema primitives
(tiers, edges, fragments, context) declared in platform spec
§A.3. Examples use the default bundle's tier and edge names
because they're concrete and recognizable; the same shapes
apply to any L2+ bundle.

## 1.1 Tier declaration

A tier declaration sets the tier's scope, identity, fields,
handle, and (optionally) draft grammar and generator.

```yaml
tiers:
  comp:
    scope: child_of(sysarch)
    identity: alias
    fields:
      name:       draft.name
      kind:       { from: draft.kind, enum: [domain, presentational] }
      role:       draft.role
      api_intent: draft.api-intent
    handle:
      fields:    [id, alias, name, kind, role, api_intent]
      fragments: [techspec, pubapi, privapi]
    # comp has no draft of its own — it's minted by sysarch's fanout;
    # its fragments are written by comparch via `produces:`
```

A tier without a `draft` produces no content of its own; it
exists purely as a join target. Most tiers have drafts.

## 1.2 Edge declarations

Five platform-level edge types: `fanout`, `reference`,
`dependency`, `policy_application`, `synthesis`. Bundles
declare named instances typed against one of these.

```yaml
- fanout:
    parent: sysarch
    child: comp
    property: draft.components
    cardinality: { child: { min: 1 } }

- reference:
    type: fulfills                              # comp → resp
    source: comp
    target: resp
    declared_in: comp.draft.responsibilities[].@id
    cardinality:
      source: { min: 1 }                        # every comp fulfills ≥1 resp
      target: { min: 1, max: 1 }                # every resp fulfilled by exactly 1 comp

- dependency:
    source: subcomp
    target: subcomp
    declared_in: comparch.draft.sub_dependencies[]
    from: @from                                 # resolves via subcomp.identity (alias)
    to:   @to
    scope: within(comparch)                     # both endpoints in same comparch's fanout
    graph_constraint: [acyclic, no_self_loop]
```

Cardinality endpoints use `{ min, max }` bounds. `{ min: 1,
max: 1 }` is exactly-one; `{ min: 1 }` is at-least-one;
`{ min: 0 }` is optional; `max: many` is the default.
Cardinality can be filtered (`when: kind == presentational`)
and scoped (`per_source(subreqs)`).

## 1.3 Context walks

A tier's `context:` is a list of typed edge walks its generator
reads. Each entry yields handles, fragments, or synthesis views.

```yaml
comparch:
  scope: per(comp)
  context:
    - self.parent.handle
    - self.parent.fulfills → resp.handle
    - self.parent.decomposed_by(subresp)
    - self.parent.dependency → target.handle.fragments[pubapi]
    - self.parent.domain_parent → target.synthesis
```

Context is the only readiness signal the scheduler needs. A
`(tier, scope)` pair is ready when every traversal in its
`context:` resolves to a ready source.

## 1.4 Fragment production

A tier can declare that its draft writes a fragment owned by a
different node:

```yaml
comparch:
  produces:
    - fragment: { owner: self.parent, kind: techspec, authored: draft.techspec }
    - fragment: { owner: self.parent, kind: pubapi,   authored: draft.pubapi }
    - fragment: { owner: self.parent, kind: privapi,  authored: draft.privapi }
```

This is how `comparch` populates its parent `comp`'s fragments
without `comparch` and `comp` being the same tier.

---

# Part 2 — Flow declaration sketches

Working sketches for each of the default bundle's six flows.
Each flow is declared per platform spec §A.4: a seed shape, an
optional phase-zero tier, a direction, and the per-tier
(planning, regeneration) prompt pair.

Flows are sketched one at a time. Each sketch covers:

- **Declaration YAML** — the bundle entry that names the flow
  and its parts.
- **Phase-zero tier declaration** (where applicable) — the
  bundle-declared singleton-per-flow-run tier with its scope,
  draft grammar, handle, and prompt template.
- **Plan grammar** — the XML structure planning prompts emit,
  including `<implicated-children>` and (where applicable)
  `<structural-ops>`.
- **Planning prompt template** — generic over tier; composes
  with tier-specific instructions from `scaffold/`.
- **Regeneration prompt template** — generic over tier.
- **Walked example** — a worked single-tier visit showing what
  the LLM sees and what it produces.

Open question to validate as we work through flows: the
generic-over-tier prompt composition. The bet is that
tier-specific framing (what does `comparch` produce; what's
its draft grammar for) lives on the tier declaration in
`scaffold/tiers/<tier>.yaml`, and the flow's plan/regen
prompts reference those fields generically. If sketching a
flow forces tier-specific copy into the flow prompt, the
composition needs revisiting.

## 2.1 Downward propagation

To be sketched.

## 2.2 Feature request

To be sketched.

## 2.3 Refactor

To be sketched.

## 2.4 Bug-fix propagation

To be sketched.

## 2.5 Upward propagation

To be sketched.

## 2.6 Scaffolding

To be sketched. Likely the simplest because it has no
phase-zero and no upstream context to merge — every visit
runs plan + regen against the tier's standard regen context
and the parent's plan, full stop.
