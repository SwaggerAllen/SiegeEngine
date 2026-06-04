# Catapult — Default bundle examples (v4)

YAML examples for the bundle's tier, edge, fragment,
predicate, and flow declarations, plus Liquid template
samples and per-flow sketches. Companion to
`catapult-default-bundle-v4.md`.

This file is reference material; the chain doesn't read it
during extraction (it'd burn tokens). Bundle authors and
implementers read it.

---

# Part 1 — Schema declarations

## 1.1 Project layout

Project repo root after bootstrap with the default bundle:

```
my-project/
├── catapult.yaml                  # active-bundle pointer
├── bundles/
│   └── default/
│       ├── bundle.yaml            # registry: tier + edge + fragment + predicate files
│       ├── plan.yaml              # phase-plan rule
│       ├── tiers/
│       │   ├── feature_expansion.yaml
│       │   ├── requirements.yaml
│       │   ├── sysarch.yaml
│       │   ├── comp.yaml
│       │   ├── comparch.yaml
│       │   ├── subcomp.yaml
│       │   ├── subcomparch.yaml
│       │   ├── impl.yaml
│       │   ├── fanin.yaml
│       │   ├── code.yaml
│       │   ├── policy.yaml
│       │   ├── vocab.yaml
│       │   └── ref.yaml
│       ├── edges/
│       │   ├── fulfills.yaml
│       │   ├── dependency.yaml
│       │   ├── domain_parent.yaml
│       │   ├── decomposition.yaml
│       │   └── policy_application.yaml
│       ├── fragments.yaml         # fragment kind registry
│       ├── predicates.yaml        # named predicate compositions
│       ├── prompts/
│       │   ├── feature_expansion.md.liquid
│       │   ├── requirements.md.liquid
│       │   ├── sysarch.md.liquid
│       │   ├── comparch.md.liquid
│       │   ├── subcomparch.md.liquid
│       │   ├── impl.md.liquid
│       │   ├── fanin.md.liquid
│       │   ├── vocab.md.liquid
│       │   ├── ref.md.liquid
│       │   └── review/
│       │       └── <tier>.md.liquid (one per reviewed tier)
│       ├── grammars/
│       │   └── <tier>.xsd          (per-tier body schemas)
│       └── flows/
│           ├── feature_request/
│           ├── refactor/
│           ├── bug_fix/
│           ├── downward_propagation/
│           ├── upward_propagation/
│           └── plan_change/
├── inputs/
│   └── project_doc.md             # the project's primary input
├── feature_expansion/
│   └── proj/
│       ├── body.md
│       └── review.md
├── requirements/
│   └── proj/
│       ├── body.md
│       └── review.md
├── sysarch/
│   └── proj/
│       ├── body.md
│       └── review.md
├── comparch/
│   └── comp_<id>/
│       ├── body.md
│       └── review.md
├── subcomparch/
│   └── comp_<parent>/subs/comp_<id>/
│       ├── body.md
│       └── review.md
├── impl/
│   └── comp_<parent>/subs/comp_<id>/p<phase>/
│       ├── body.md
│       └── review.md
├── fanin/
│   └── comp_<id>/p<phase>/
│       ├── body.md
│       └── review.md
└── ref/
    └── ref_<id>/
        ├── body.md
        └── review.md
```

## 1.2 `catapult.yaml`

```yaml
# catapult.yaml — repo root
bundle: bundles/default
version: "1.0"
```

That's the entire file. Catapult reads it on each fetch to
determine which bundle to load. Changing `bundle:` switches
the project to a different bundle on the next commit.

## 1.3 `bundle.yaml`

```yaml
# bundles/default/bundle.yaml
name: catapult-default
version: "1.0"

tiers:
  - tiers/feature_expansion.yaml
  - tiers/requirements.yaml
  - tiers/sysarch.yaml
  - tiers/comp.yaml
  - tiers/comparch.yaml
  - tiers/subcomp.yaml
  - tiers/subcomparch.yaml
  - tiers/impl.yaml
  - tiers/fanin.yaml
  - tiers/code.yaml
  - tiers/policy.yaml
  - tiers/vocab.yaml
  - tiers/ref.yaml

edges:
  - edges/fulfills.yaml
  - edges/dependency.yaml
  - edges/domain_parent.yaml
  - edges/decomposition.yaml
  - edges/policy_application.yaml

fragments: fragments.yaml
predicates: predicates.yaml
plan_rule: plan.yaml

input_roles:
  - role: project_doc
    cardinality: { max: 1 }      # one project_doc per project
    path: inputs/project_doc.md   # default path for git ingestion

flows:
  - flows/feature_request/flow.yaml
  - flows/refactor/flow.yaml
  - flows/bug_fix/flow.yaml
  - flows/downward_propagation/flow.yaml
  - flows/upward_propagation/flow.yaml
  - flows/plan_change/flow.yaml
```

## 1.4 Tier declaration: `comparch`

```yaml
# bundles/default/tiers/comparch.yaml
tier: comparch
scope: per(comp)
identity: id
thinking_effort: max

fields:
  decomposition_summary: draft.decomposition_summary

handle:
  fields:    [id, decomposition_summary]
  fragments: []   # comparch's output is on the comp, not on itself

draft:
  root_tag: comparch
  grammar: grammars/comparch.xsd
  body_path: comparch/${self.parent.id}/body.md
  review_path: comparch/${self.parent.id}/review.md

generator: llm
prompt: prompts/comparch.md.liquid
review:
  prompt: prompts/review/comparch.md.liquid
  grammar: grammars/review.xsd

context:
  - self.parent.handle
  - self.parent.fulfills → resp.handle
  - self.parent.dependency → target.handle.fragments[pubapi]
  - self.parent.domain_parent → target.synthesis        # when presentational
  - self.applied_policies → policy.handle
  - self.reference → ref.handle                          # attached refs
  - self.vocab → vocab.handle

produces:
  - fragment: { owner: self.parent, kind: techspec,
                authored: draft.techspec }
  - fragment: { owner: self.parent, kind: pubapi,
                authored: draft.pubapi }
  - fragment: { owner: self.parent, kind: privapi,
                authored: draft.privapi }
  - fragment: { owner: self.parent, kind: policies,
                authored: draft.policies }
  - fragment: { owner: self.parent, kind: failure_surface,
                authored: draft.failure_surface }
```

Field-by-field commentary:

- `scope: per(comp)` — one comparch per top-level component.
- `identity: id` — downstream references resolve via comparch's
  id (rare; most references go to the comp).
- `thinking_effort: max` — comparch carries the
  reconciliation pass; deep reasoning pays off here.
- `fields:` — only the decomposition summary lives as a field on
  the comparch node itself; everything else is fragments on the
  parent comp.
- `handle:` — empty `fragments:` because comparch's outputs are
  attributed to the comp, not to itself.
- `draft:` — body path is parameterized by the parent comp's id.
- `context:` — the comparch context walk is the most elaborate in
  the bundle; reads parent comp handle, fulfilled responsibilities,
  dependencies' pubapi, domain parents' fanin synthesis (when
  presentational), applied policies, attached refs, and relevant
  vocab.
- `produces:` — five fragments written on the parent comp from
  five matching body sections.

## 1.5 Tier declaration: `impl` (phased)

```yaml
# bundles/default/tiers/impl.yaml
tier: impl
scope: per(impl_owner) × phase
identity: id

# `impl_owner` is a named predicate covering both subcomps and
# un-fanned-out top-level comps (see predicates.yaml).

fields:
  approach: draft.approach

handle:
  fields:    [id, approach]
  fragments: []

draft:
  root_tag: implementation
  grammar: grammars/impl.xsd
  body_path: impl/${self.parent.parent.id}/subs/${self.parent.id}/p${self.phase}/body.md
  review_path: impl/${self.parent.parent.id}/subs/${self.parent.id}/p${self.phase}/review.md

generator: llm
prompt: prompts/impl.md.liquid
review:
  prompt: prompts/review/impl.md.liquid
  grammar: grammars/review.xsd

context:
  - self.parent.handle
  - self.parent.parent.handle
  - sysarch.project_techspec
  - sysarch.project_policies
  - self.parent.applied_policies → policy.handle
  - self.related_features → feature.handle
  - self.parent.dependency → target.handle.fragments[pubapi]
  - self.prior_phases → target.handle
  - self.reference → ref.handle
  - self.vocab → vocab.handle
```

Notes on phased scope:

- `scope: per(impl_owner) × phase` produces one impl node per
  `(owner, phase)` pair. The platform iterates `phase` over the
  phase plan's assigned phases for each owner.
- `body_path:` includes `p${self.phase}` so each phase's body
  lands in its own subdirectory.
- `self.prior_phases → target.handle` is the cross-phase delta
  walk; the platform resolves it as iterating from phase 1 to
  `self.phase - 1` for the same owner.

## 1.6 Edge declaration: `fulfills`

```yaml
# bundles/default/edges/fulfills.yaml
edge: fulfills
type: reference

source: comp
target: resp           # resolves through requirements body

declared_in: sysarch.draft.components[].responsibilities[].@id

cardinality:
  source: { min: 1 }                # every comp fulfills >= 1 resp
  target: { min: 1, max: 1 }        # every resp by exactly 1 comp
```

`declared_in` tells the reducer where to look in the source
body to derive the edge. For each component in sysarch's
`<components>` block, the reducer reads the
`<responsibilities>` children and emits a `fulfills` edge
per `@id` reference.

## 1.7 Edge declaration: `dependency`

```yaml
# bundles/default/edges/dependency.yaml
edge: dependency
type: dependency

# Two source/target shapes; bundle uses a union via the
# `source_when:` discriminator.
source:
  - tier: comp
    declared_in: sysarch.draft.components[].dependencies[].@to
  - tier: subcomp
    declared_in: comparch.draft.sub_dependencies[]
    scope: within(comparch)
target: same_as_source

cardinality:
  source: { min: 0 }
  target: { min: 0 }

graph_constraint: [acyclic, no_self_loop]
```

The `scope: within(comparch)` on the subcomp variant enforces
that subcomp-to-subcomp dependencies only resolve within the
same parent's fanout.

## 1.8 Edge declaration: `policy_application`

```yaml
# bundles/default/edges/policy_application.yaml
edge: policy_application
type: policy_application

source: policy
target: comp                       # or subcomp via reachability

declared_in:
  - sysarch.draft.policies[].applies_to[]      # project-level
  - comparch.draft.policies[].applies_to[]     # comp-local

cardinality:
  source: { min: 0 }                # a target can have 0 policies
  target: { min: 1 }                # every policy must apply somewhere

reachability:
  transitive_through: [decomposition]
  override_with: redeclared_at_intermediate_level
```

The `reachability:` block tells the platform that policies
applied to a comp also apply transitively to the comp's
subcomps via decomposition edges. An intermediate redeclaration
(a comparch declaring a policy that applies to specific
subcomps) overrides the parent's policy for those subcomps.

## 1.9 Predicates

```yaml
# bundles/default/predicates.yaml
predicates:
  has_foundation_child:
    count(decomposed_by(child)
          where child.is_foundation == true) >= 1

  is_domain:
    kind == domain

  is_presentational:
    kind == presentational

  is_fanned_out:
    count(decomposed_by(subcomp)) > 0

  impl_owner:
    # union of "subcomp" and "un-fanned-out top-level comp"
    (tier == subcomp)
    OR (tier == comp AND parent_tier == sysarch
        AND count(decomposed_by(subcomp)) == 0)

  awaits_domain_fanin:
    is_presentational
    AND any(domain_parent → target.synthesis_ready == false)
```

These are reusable expressions composed of the platform's
six predicate operator families. Named predicates can
reference other named predicates (`impl_owner` references
`tier`, `parent_tier`, `count`).

## 1.10 Fragment registry

```yaml
# bundles/default/fragments.yaml
fragments:
  techspec:
    owners: [comp, subcomp]

  pubapi:
    owners: [comp, subcomp]

  privapi:
    owners: [comp, subcomp]

  policies:
    owners: [comp, subcomp]

  failure_surface:
    owners: [comp, subcomp]
```

Each fragment kind declares which tiers can own instances.
The bundle's tier declarations are responsible for the
`produces:` claims that actually write the fragments.

## 1.11 Context walks

A context walk's general syntax:

```
self.<edge_name>[(filter)] → <target_tier>.<projection>
```

Examples from the default bundle:

```yaml
# Self-handle (no edge walk)
self.parent.handle

# Single-step edge walk yielding handles
self.parent.fulfills → resp.handle

# Edge walk yielding one fragment slice
self.parent.dependency → target.handle.fragments[pubapi]

# Synthesis-tier walk
self.parent.domain_parent → target.synthesis

# Iterated prior-phases (platform-resolved phase iteration)
self.prior_phases → target.handle

# Project-level scalar reference
sysarch.project_techspec
```

The platform's predicate-evaluator and edge-derivation
machinery resolve each walk at `get_context` time and yield
Liquid variables to the prompt template.

## 1.12 Liquid template excerpt

```liquid
# bundles/default/prompts/comparch.md.liquid

You are drafting the component architecture for
{{ parent.name }}. This component is **{{ parent.kind }}**;
{% if parent.is_foundation %}it is the foundation
component, which other components depend on.
{% endif %}

## Responsibilities this component fulfills

{% for resp in fulfills %}
### {{ resp.name }} ({{ resp.id }})

{{ resp.summary }}
{% endfor %}

## Components this depends on

{% for dep in dependencies %}
- **{{ dep.name }}** ({{ dep.id }}): {{ dep.pubapi | indent: 2 }}
{% endfor %}

{% if domain_parents %}
## Domain parents (fanin synthesis)

{% for parent in domain_parents %}
- **{{ parent.name }}**: {{ parent.synthesis }}
{% endfor %}
{% endif %}

## Applied policies

{% for policy in applied_policies %}
- **{{ policy.trigger }}**: {{ policy.required }}
  Rationale: {{ policy.rationale }}
{% endfor %}

{% if refs.size > 0 %}
## Attached references

{% for ref in refs %}
### {{ ref.title }}

{{ ref.body }}
{% endfor %}
{% endif %}

## Your task

Produce a comparch body in this shape:

[... rest of the prompt with structural guidance ...]
```

Liquid's `{% for %} {% if %}` syntax is sandboxed; templates
can't execute arbitrary code. Variables are populated by
the bundle's `context:` walks.

## 1.13 The plan rule

```yaml
# bundles/default/plan.yaml
plan_rule:
  inputs:
    - source: user_pin
      tier: feature
      default_phase: 1
    - source: foundation_override
      condition: comp.is_foundation == true
      phase: 1

  cascade:
    - from: feature
      to: resp
      via: fulfills_inverse        # resp's implicating features
      aggregator: min               # earliest phase wins
    - from: resp
      to: comp
      via: fulfills
      aggregator: min
    - from: comp
      to: subcomp
      via: decomposition
      aggregator: min
    - from: subcomp
      to: impl
      via: scope_resolution        # impl for subcomp at each phase
      aggregator: identity

  validators:
    - rule: dependency_ordering
      message: "comp depending on dep cannot be in earlier phase"
      check: |
        for each dependency(source, target):
          phase(source) >= phase(target)
```

The plan rule is declarative — the platform evaluates the
cascade against current state and writes the phase_plan
projection. Recompute fires when any input changes.

## 1.14 Input documents

```markdown
<!-- inputs/project_doc.md -->

# My Project

A subscription billing platform with a customer portal and an
operator console.

## What it's for

Customers manage their subscriptions through a web interface;
operators handle billing exceptions and audit incidents
through a separate console.

## Primary workflows

[... etc. — standard project description prose ...]
```

The input document is plain markdown. Catapult's projection
stores `(role, body_sha)`; the bundle's
feature_expansion context walk references it as
`{{ project_doc }}` in the Liquid template.

Adding a second input doc with `role: project_doc` would
either replace the first (if the bundle declares
`cardinality: { max: 1 }`) or concatenate (default).

---

# Part 2 — Flow declarations

Each flow ships in `bundles/default/flows/<name>/`. The
sketches below show the YAML schema delta and the planning
tier's prompt shape; full flow declarations include grammars
for the plan body and `prior_*` context bindings.

## 2.1 `feature_request`

```yaml
# bundles/default/flows/feature_request/flow.yaml
flow: feature_request

seed:
  shape: prose
  prompt: |
    Describe the feature change you want. Be specific about
    what the chain should produce; vague seeds produce vague
    plans.

walk: downward_cascade
walk_anchor: feature_expansion(proj)   # cascade starts at the singleton

planning_tier:
  tier: feature_request_plan
  scope: per(scaffold_tier)            # one plan per visited tier
  scope_filter:
    in_cascade_visit_set                # platform-managed visit set

  prompt: feature_request/plan.md.liquid
  grammar: feature_request/plan.xsd
  review: feature_request/review.md.liquid

completion:
  predicate: count(open_visit) == 0    # all planned visits done
```

The planning tier visits each scaffold tier the cascade
touches. The plan body declares "what should this tier do
about the feature request"; downstream regeneration of the
scaffold tier consumes the plan via context walk.

## 2.2 `refactor`

```yaml
# bundles/default/flows/refactor/flow.yaml
flow: refactor

seed:
  shape: prose
  constraints:
    - "describes a structural change, not new functionality"

walk: downward_cascade
walk_anchor: sysarch(proj)             # refactors usually start at sysarch

planning_tier:
  tier: refactor_plan
  scope: per(scaffold_tier)
  scope_filter: in_cascade_visit_set
  prompt: refactor/plan.md.liquid
  grammar: refactor/plan.xsd
  review: refactor/review.md.liquid

completion:
  predicate: count(open_visit) == 0
```

## 2.3 `bug_fix`

```yaml
# bundles/default/flows/bug_fix/flow.yaml
flow: bug_fix

seed:
  shape: defect_report
  fields:
    - observed_behavior: prose
    - expected_behavior: prose
    - reproduction: prose (optional)
    - originating_scope: node_id        # where the defect lives

walk: downward_cascade
walk_anchor: ${seed.originating_scope}

planning_tier:
  tier: bug_fix_plan
  scope: per(scaffold_tier)
  scope_filter: in_cascade_visit_set
  prompt: bug_fix/plan.md.liquid
  grammar: bug_fix/plan.xsd
  review: bug_fix/review.md.liquid

completion:
  predicate: count(open_visit) == 0
```

## 2.4 `downward_propagation`

```yaml
# bundles/default/flows/downward_propagation/flow.yaml
flow: downward_propagation

seed:
  shape: scope_re_approved
  fields:
    - source_scope: node_id
    - re_approved_at: timestamp
    - change_summary: prose             # what changed about the approval

walk: downward_cascade
walk_anchor: ${seed.source_scope}

planning_tier:
  tier: propagation_plan
  scope: per(scaffold_tier)
  scope_filter: in_cascade_visit_set
  prompt: downward_propagation/plan.md.liquid
  grammar: downward_propagation/plan.xsd
  review: downward_propagation/review.md.liquid

completion:
  predicate: count(open_visit) == 0
```

## 2.5 `upward_propagation`

```yaml
# bundles/default/flows/upward_propagation/flow.yaml
flow: upward_propagation

seed:
  shape: downstream_argument
  fields:
    - source_scope: node_id              # where the argument originates
    - target_argument: prose             # what's wrong upstream
    - upstream_anchor: node_id           # where the upstream fix should land

walk: up_then_down
walk_up_anchor:   ${seed.upstream_anchor}
walk_down_anchor: ${seed.source_scope}

planning_tiers:
  - tier: assessment_plan                # the upstream plan
    scope: per(walk_up_target)
    prompt: upward_propagation/assessment.md.liquid
    grammar: upward_propagation/assessment.xsd
    review: upward_propagation/assessment_review.md.liquid

  - tier: propagation_plan               # downstream plans after upstream regen
    scope: per(scaffold_tier)
    scope_filter: in_walk_down_visit_set
    prompt: upward_propagation/plan.md.liquid
    grammar: upward_propagation/plan.xsd
    review: upward_propagation/plan_review.md.liquid

completion:
  predicate: |
    count(open_upward_visit) == 0
    AND count(open_downward_visit) == 0
```

The `up_then_down` walk primitive is the only place the
default bundle uses anything beyond `downward_cascade`. It
fires the assessment plans first, then waits for upstream
regenerations to land, then opens downstream propagation
plans.

## 2.6 `plan_change`

```yaml
# bundles/default/flows/plan_change/flow.yaml
flow: plan_change

seed:
  shape: plan_diff
  fields:
    - changes:
        - moved:
            feature_id: string
            from_phase: int
            to_phase: int
        - split:
            phase: int
            into: [int]
        - dropped:
            phase: int

walk: downward_cascade
walk_anchor: phase_plan
walk_visit_filter: |
  scope.phase IN changed_phases
  AND scope.tier IN [impl, fanin, code]

planning_tier:
  tier: plan_change_plan
  scope: per(phased_scope)
  scope_filter: in_cascade_visit_set
  prompt: plan_change/plan.md.liquid
  grammar: plan_change/plan.xsd
  review: plan_change/review.md.liquid

completion:
  predicate: count(open_visit) == 0
```

Differs from `downward_propagation` in scope: plan_change
only visits phased tiers whose phase assignment changed,
not the entire downstream chain. The plan_change_plan body
describes what the phased tier needs to do given the new
phase membership.

---

# Part 3 — Worked example: comparch context bundle

To make the per-tier context bundles concrete, here's what
a comparch generator sees for a fictional billing component
in a partially-scaffolded project.

## State at the time

- `sysarch` approved with five comps: `comp_foundation`,
  `comp_auth`, `comp_billing` (domain),
  `comp_ui_billing` (presentational with
  `domain_parent → comp_billing`), `comp_audit_log`.
- `requirements` approved with responsibilities including
  "Authentication," "Billing Lifecycle," "Audit Trail,"
  "Durable Storage Substrate."
- `comp_billing` fulfills "Billing Lifecycle" and "Audit Trail."
- `comp_billing` depends on `comp_foundation` and `comp_auth`.
- `comp_foundation` and `comp_auth` have approved comparches
  with pubapi fragments.
- The user has attached two refs to `comp_billing`:
  `ref_stripe_api` (a Stripe API summary) and `ref_pci_compliance`
  (a PCI compliance checklist).

## What the comparch generator's context bundle contains

After the platform evaluates comparch's `context:` walks
against this state:

```yaml
self:
  parent:                                # comp_billing
    handle:
      id: comp_billing
      name: Billing Service
      kind: domain
      is_foundation: false

fulfills:                                # parent.fulfills walk
  - id: resp_billing_lifecycle
    name: Billing Lifecycle
    summary: "Charge customers' cards each billing cycle; ..."
    feats: [feat_subscription_management, feat_payment_collection]
  - id: resp_audit_trail
    name: Audit Trail
    summary: "Record every privileged action on billing state ..."
    feats: [feat_admin_audit_log]

dependencies:                            # parent.dependency walk
  - id: comp_foundation
    name: Foundation
    pubapi: |
      Storage: key-value with transactional batch writes...
      Logging: structured emit with severity tagging...
  - id: comp_auth
    name: Auth Service
    pubapi: |
      verify_credentials(email, password) -> session_token | error
      lookup_session(token) -> account | null

domain_parents: []                       # comp_billing is domain, not presentational

applied_policies:                        # parent.applied_policies walk
  - trigger: "any operation touching billing or auth state"
    required: "land in audit log via resp_audit_trail"
    rationale: "every privileged mutation must be reconstructable"
  - trigger: "any persisted credential or payment token"
    required: "encrypted at rest in storage substrate"
    rationale: "database snapshot leak must not yield plaintext"

refs:                                    # parent.reference walk
  - id: ref_stripe_api
    title: Stripe API summary
    body: "Stripe charges through the v2 endpoint requires ..."
  - id: ref_pci_compliance
    title: PCI compliance checklist
    body: "Storing card data requires PCI-DSS Level 1 ..."

vocab:                                   # parent.vocab walk
  - name: billing cycle
    definition: "30-day period during which a subscription is active ..."
  - name: card-on-file
    definition: "tokenized payment method stored on Stripe ..."
```

The Liquid template iterates these variables and produces the
prompt the LLM sees. The reviewer's prompt template receives
the same context (plus `draft`) so the reviewer judges output
against the same input the generator saw.

This is what handle quality looks like in practice — each
variable is a compressed slice of upstream state, dense
enough for the prompt to reason about but small enough to
fit alongside the prompt's instructions.
