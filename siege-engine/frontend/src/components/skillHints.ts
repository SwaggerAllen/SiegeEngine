import type { ScopeStatus } from '../api/siege';

/**
 * Pick the most likely next-step Claude Code skill for a scope given
 * its current state. The user is the actor; the panel surfaces the
 * skill to invoke and the dashboard stays read-only.
 *
 * Status → skill mapping:
 *   absent    — no artifact yet → /draft-<tier>
 *   drafted   — draft on disk, no review → /review-<tier>
 *   reviewed  — review on disk, awaiting approval → /mark-approved
 *   approved  — landed; iterate via /regen-<tier>-with-feedback
 *
 * The id arg is whatever the skill expects after the slash — usually
 * a comp_id for top-level tiers, a sub_id for sub-tiers. ``'proj'``
 * is the conventional sentinel for project-wide substrate
 * (feature_expansion / requirements / sysarch).
 */
export function hintForStatus(
  tier: string,
  status: ScopeStatus | undefined,
  id: string,
): string {
  const effective: ScopeStatus = status ?? 'absent';
  switch (effective) {
    case 'absent':
      return `/draft-${tier} ${id}`;
    case 'drafted':
      return `/review-${tier} ${id}`;
    case 'reviewed':
      return `/mark-approved ${tier} ${id}`;
    case 'approved':
      return `/regen-${tier}-with-feedback ${id}`;
  }
}
