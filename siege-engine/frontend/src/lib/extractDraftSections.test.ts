import { describe, expect, it } from 'vitest';
import { extractDraftSections } from './extractDraftSections';

describe('extractDraftSections', () => {
  describe('expansion', () => {
    it('unrolls features out of <features>', () => {
      const xml =
        '<expansion>' +
        '<introduction>Preamble that should be ignored.</introduction>' +
        '<features>' +
        '<feature><name>Login</name><intent>Let users log in.</intent></feature>' +
        '<feature><name>Billing</name><intent>Let admins bill.</intent></feature>' +
        '</features>' +
        '</expansion>';
      const sections = extractDraftSections(xml, 'expansion');
      expect(sections).not.toBeNull();
      expect(sections?.map((s) => s.label)).toEqual(['Login', 'Billing']);
      expect(sections?.map((s) => s.kind)).toEqual(['feature', 'feature']);
      expect(sections?.[0].xml).toContain('<name>Login</name>');
    });

    it('unrolls features nested inside <group>', () => {
      const xml =
        '<features>' +
        '<group><name>Auth</name>' +
        '<feature><name>Login</name><intent>a</intent></feature>' +
        '</group>' +
        '<feature><name>Billing</name><intent>b</intent></feature>' +
        '</features>';
      const sections = extractDraftSections(xml, 'expansion');
      expect(sections?.map((s) => s.label)).toEqual(['Login', 'Billing']);
    });

    it('returns null on empty or unparseable input', () => {
      expect(extractDraftSections('', 'expansion')).toBeNull();
      expect(extractDraftSections('  ', 'expansion')).toBeNull();
      expect(
        extractDraftSections('<not-expansion></not-expansion>', 'expansion'),
      ).toBeNull();
    });
  });

  describe('requirements', () => {
    it('returns one section per <responsibility>', () => {
      const xml =
        '<reqs>' +
        '<introduction>ignored</introduction>' +
        '<requirements>' +
        '<responsibility><name>Identity</name><intent>i</intent></responsibility>' +
        '<responsibility><name>Billing</name><intent>b</intent></responsibility>' +
        '</requirements>' +
        '</reqs>';
      const sections = extractDraftSections(xml, 'requirements');
      expect(sections?.map((s) => s.label)).toEqual(['Identity', 'Billing']);
      expect(sections?.[0].kind).toBe('responsibility');
    });

    it('handles sibling top-level tags (bootstrap draft shape)', () => {
      // Real bootstrap drafts emit <introduction>…</introduction>
      // followed by <requirements>…</requirements> as siblings, not
      // wrapped under a single root. The extractor must find the
      // requirements block anyway.
      const xml =
        '<introduction>Long intro paragraph.</introduction>' +
        '<requirements>' +
        '<responsibility><name>Credential Verification</name></responsibility>' +
        '<responsibility><name>Billing Lifecycle</name></responsibility>' +
        '</requirements>';
      const sections = extractDraftSections(xml, 'requirements');
      expect(sections).not.toBeNull();
      expect(sections?.map((s) => s.label)).toEqual([
        'Credential Verification',
        'Billing Lifecycle',
      ]);
    });
  });

  describe('expansion sibling shape', () => {
    it('finds features when siblings with <introduction>', () => {
      const xml =
        '<introduction>ignored</introduction>' +
        '<features>' +
        '<feature><name>Login</name><intent>i</intent></feature>' +
        '</features>';
      const sections = extractDraftSections(xml, 'expansion');
      expect(sections?.map((s) => s.label)).toEqual(['Login']);
    });
  });

  describe('sysarch', () => {
    it('returns per-component sections keyed by alias', () => {
      const xml =
        '<sysarch>' +
        '<techspec>Python + React.</techspec>' +
        '<components>' +
        '<component alias="billing">' +
        '<name>Billing</name>' +
        '<kind>domain</kind>' +
        '<role>Owns invoices.</role>' +
        '</component>' +
        '<component alias="auth">' +
        '<name>Auth</name>' +
        '<kind>domain</kind>' +
        '<role>Identifies callers.</role>' +
        '</component>' +
        '</components>' +
        '<policies></policies>' +
        '</sysarch>';
      const sections = extractDraftSections(xml, 'sysarch');
      // techspec + each component + policies → 4 entries
      expect(sections).not.toBeNull();
      const labels = sections!.map((s) => s.label);
      expect(labels).toContain('Billing');
      expect(labels).toContain('Auth');
      expect(labels).toContain('Techspec');
      expect(labels).toContain('Policies');
      const billing = sections!.find((s) => s.label === 'Billing');
      expect(billing?.kind).toBe('component');
      expect(billing?.xml).toContain('Owns invoices.');
    });
  });
});
