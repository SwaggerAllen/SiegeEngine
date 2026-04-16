# Commercial License Feature Boundary — Working Notes

Principle: **individual capability is free, organizational process is commercial.**

## Free (AGPL)

- Full generation chain with default bundle
- All six flow types (scaffolding, feature request, refactor, bug-fix propagation, downward propagation, upward propagation)
- All review, approval, and feedback flows
- David chat + collaborative discussions
- Decomposition graph + all structural visualizations
- Vocabulary, references, policies — all node tiers
- Bundle authoring and usage at ALL levels (L0–L3) — if you can write it, you can use it
- Bundle scanning (the capability itself)
- Bundle publishing and sharing
- Webhooks + external API (the surface)
- Local gitea + single external forge adapter
- Single-user or small-team (local auth)
- Multiple projects (don't gate project count)
- Cross-project coordination via git
- Graduated autonomy controls (auto-approval thresholds, flow-specific overrides)

## Commercial

- SSO/SAML + JIT provisioning + multi-IdP
- Permission atoms + scoped roles + custom role definitions
- Multi-project dashboards + cross-project lobby + cross-project review queue
- Bundle *administration* (multi-approver workflows, role-based approval chains, change-request tracking, version pinning governance)
- Bundle security scanning *management* (automated CI scanning, policy enforcement, alerts on upstream changes — not the scan itself)
- Audit log export + compliance reporting
- Integration health monitoring + managed connector library
- Advanced telemetry dashboards (cost projection, per-team rollups, historical trends)
- Cross-project API publishing (automated sync workflow — manual snapshot via ref nodes is free)
- Priority support + SLA guarantees

## Explicitly NOT gated

- Any generation tier or prompt quality feature
- Any review or feedback mechanism
- David in any form
- Security scanning capability
- Project count
- Any single-project capability
- Bundle capability at any level (L0–L3)

## Decide later (observe user behavior)

- Forge adapter count: ship GitHub + gitea free, charge for additional adapters? Or free adapters, commercial multi-forge?

## Spec changes still needed

- ✅ Presentational/domain generation layer separation (done — A.3.1 step 6)
- ✅ Multi-instance federation deferred (done — git handles coordination)
- ✅ Engine-first framing (done — Part A intro)
- ✅ Meaning-engine model (done — A.3.1a)
- ✅ Propagation flows (done — A.2.5, A.2.6, A.2.7)
- ✅ Reference edges simplified (done — A.1.3, A.1.13)
- ✅ Resp 1:1+optional-mirror (done — A.1.2)
- [ ] A.11 update: bundle vulnerability scanning; all levels free; organizational admin commercial
- [ ] A.13 update: pluggable integration surface; specific integrations community-contributed
- [ ] A.14 update: local auth free, SSO/SAML + custom roles commercial
- [ ] A.15 update: cross-project API publishing design; multi-project dashboards commercial
- [ ] A.6 update: per-project lobby free, cross-project commercial
- [ ] A.12 update: per-call telemetry free, advanced dashboards commercial
- [ ] New section A.22: formal open/commercial split
