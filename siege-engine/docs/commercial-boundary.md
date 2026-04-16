# Commercial License Feature Boundary — Working Notes

Principle: **individual capability is free, organizational process is commercial.**

## Free (AGPL)

- Full generation chain with default bundle
- All six flow types (scaffolding, feature request, refactor, bug-fix propagation, downward propagation, upward propagation)
- All review, approval, and feedback flows
- David chat + collaborative discussions
- Decomposition graph + all structural visualizations
- Vocabulary, references, policies — all node tiers
- Bundle scanning (the capability itself)
- Bundle publishing and sharing
- Webhooks + external API (the surface)
- Local gitea + single external forge adapter
- Single-user or small-team (local auth)
- Prompt overrides (L0 bundle customization)
- Multiple projects (don't gate project count)
- Cross-project coordination via git

## Commercial

- SSO/SAML + JIT provisioning + multi-IdP
- Permission atoms + scoped roles + custom role definitions
- Multi-project dashboards + cross-project lobby + cross-project review queue
- Custom bundles L1+ (custom grammars, declarative mint specs, data-driven tier hierarchies)
- Bundle approval workflows (multi-approver gates, role-based chains, change-request tracking)
- Bundle security scanning *management* (automated CI scanning, policy enforcement, alerts on upstream changes — not the scan itself)
- Audit log export + compliance reporting
- Integration health monitoring + managed connector library
- Advanced telemetry dashboards (cost projection, per-team rollups, historical trends)
- Priority support + SLA guarantees

## Explicitly NOT gated

- Any generation tier or prompt quality feature
- Any review or feedback mechanism
- David in any form
- Security scanning capability
- Project count
- Any single-project capability

## Decide later (observe user behavior)

- Graduated autonomy controls (auto-approval thresholds, flow-specific overrides) — core workflow vs organizational policy concern
- Cross-project API publishing: manual snapshot export/import free, automated sync commercial?
- Forge adapter count: ship GitHub + gitea free, charge for additional adapters? Or free adapters, commercial multi-forge?

## Spec changes needed

- Add presentational/domain generation layer separation to A.3.2
- Add cross-project API publishing design to A.15 (post-MVP implementation, design now)
- Explicitly document pluggable integration surface in A.13
- Add bundle vulnerability scanning to A.11
- New section (A.22 or B.X) documenting the open/commercial split
- Multi-instance federation: deferred entirely, git handles coordination for now
