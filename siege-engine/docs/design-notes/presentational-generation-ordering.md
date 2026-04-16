# Presentational/Domain Generation Ordering — Design Note

## Decision

Keep the current model: sysarch mints both domain and presentational
components as `comp_*` nodes with a `kind` field. No new `view_*` tier.

## Change needed

Add a scheduler gate: presentational components' subreqs and comparch
generation jobs are not eligible until **all** of their `domain_parent`
edge targets have approved comparch content. This ensures presentational
comparch has the full domain architecture (techspec, pubapi, privapi,
subcomponent structure) available as context, not just sysarch-level
role handles.

The gate is a scheduler query predicate, not a handler change:
"for every presentational comp whose subreqs is not yet generated,
check that all domain_parent targets have non-empty comparch content."

## Responsibility assignment

Responsibilities are assigned 1:1 to domain components (unchanged).
Presentational components get their own responsibilities through
their own subreqs pass, which runs after domain comparch is complete.
The presentational subreqs prompt sees the domain parent's full
architecture and derives UI-specific responsibilities from it.

The earlier idea of assigning responsibilities to both domain and
presentational components (1:1+optional-mirror) is deferred. The
current approach of separate subreqs passes for each component kind
works and is simpler to validate.

## Future consideration

If the current model proves awkward (LLM struggles to produce good
presentational responsibilities from domain context alone, or the
`kind` field causes confusion), revisit the `view_*` tier idea:
presentational top-levels as their own node tier, children stay
`comp_*`. The scheduler gate we're adding now is the same gate
that a `view_*` tier would use, so the implementation cost of
upgrading later is low.
