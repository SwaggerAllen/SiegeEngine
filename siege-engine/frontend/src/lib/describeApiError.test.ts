import { describe, it, expect } from 'vitest';
import { describeApiError } from './describeApiError';

function axiosErr(status: number, data: unknown, statusText = ''): unknown {
  return {
    response: { status, statusText, data },
    message: `Request failed with status code ${status}`,
  };
}

describe('describeApiError', () => {
  it('returns the fallback for null/undefined errors', () => {
    expect(describeApiError(null, 'fallback')).toBe('fallback');
    expect(describeApiError(undefined, 'fallback')).toBe('fallback');
  });

  it('renders FastAPI HTTPException detail strings with the status code', () => {
    const err = axiosErr(400, { detail: 'Project is read-only.' });
    expect(describeApiError(err, 'Failed')).toBe('400: Project is read-only.');
  });

  it('renders FastAPI 422 validation arrays with the field name', () => {
    const err = axiosErr(422, {
      detail: [
        { loc: ['body', 'artifacts_file'], msg: 'Field required', type: 'missing' },
      ],
    });
    expect(describeApiError(err, 'Failed to create project')).toBe(
      'Failed to create project: 422 artifacts_file: Field required',
    );
  });

  it('joins multiple 422 entries (up to 3)', () => {
    const err = axiosErr(422, {
      detail: [
        { loc: ['body', 'name'], msg: 'Field required', type: 'missing' },
        { loc: ['body', 'artifacts_file'], msg: 'Field required', type: 'missing' },
      ],
    });
    const out = describeApiError(err, 'Failed');
    expect(out).toContain('name: Field required');
    expect(out).toContain('artifacts_file: Field required');
  });

  it('handles a 422 entry with no loc by rendering just the message', () => {
    const err = axiosErr(422, { detail: [{ msg: 'Boom' }] });
    expect(describeApiError(err, 'Failed')).toBe('Failed: 422 Boom');
  });

  it('falls back to status + statusText when no detail is present', () => {
    const err = axiosErr(500, {}, 'Internal Server Error');
    expect(describeApiError(err, 'Failed')).toBe('Failed: 500 Internal Server Error');
  });

  it('uses the error message for network failures', () => {
    expect(describeApiError({ message: 'Network Error' }, 'Failed')).toBe(
      'Failed: Network Error',
    );
  });

  it('rewrites Zod errors with a contract-drift hint', () => {
    const err = { name: 'ZodError' };
    expect(describeApiError(err, 'Failed')).toContain('did not match the expected shape');
  });
});
