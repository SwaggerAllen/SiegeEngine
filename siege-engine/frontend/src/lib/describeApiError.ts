/**
 * Extract a human-readable error message from an axios error.
 *
 * Priority:
 *   1. ``err.response.data.detail`` — FastAPI HTTPException or our
 *      global unhandled-exception handler in backend/main.py
 *   2. ``err.response.statusText`` with a leading status code
 *   3. ``err.message`` — network / timeout errors
 *   4. The caller-supplied fallback
 *
 * Zod parse errors (schema validation on the frontend side) are
 * also caught and rewritten to "response did not match the expected
 * shape" so they don't leak raw validation trees into the UI.
 */
export function describeApiError(err: unknown, fallback: string): string {
  if (!err) return fallback;

  // Zod validation errors thrown by our schema parsers — signals
  // backend/frontend drift, not a server failure.
  if (
    typeof err === 'object' &&
    err !== null &&
    'name' in err &&
    (err as { name?: unknown }).name === 'ZodError'
  ) {
    return `${fallback}: server response did not match the expected shape. See console for details.`;
  }

  // Axios error shape: { response?: { status, statusText, data }, message }
  const e = err as {
    response?: {
      status?: number;
      statusText?: string;
      data?: { detail?: string | unknown };
    };
    message?: string;
  };

  const detail = e.response?.data?.detail;
  if (typeof detail === 'string' && detail.trim()) {
    const status = e.response?.status;
    return status ? `${status}: ${detail}` : detail;
  }

  // Some backends return structured validation errors as arrays.
  // FastAPI 422 detail is ``[{loc, msg, type}, …]``: surface the
  // first few with their field names so the user can tell which
  // input is missing, not just *that* something is.
  if (Array.isArray(detail) && detail.length > 0) {
    const rendered = detail
      .slice(0, 3)
      .map((entry) => {
        if (typeof entry !== 'object' || entry === null || !('msg' in entry)) return null;
        const v = entry as { loc?: unknown[]; msg?: unknown };
        const msg = typeof v.msg === 'string' ? v.msg : '';
        if (!msg) return null;
        // ``loc`` is like ``['body', 'name']`` or ``['body', 'artifacts_file']``.
        // Drop the wrapper segments — the user doesn't care that it's
        // "body" — and keep the field name.
        const loc = Array.isArray(v.loc)
          ? v.loc
              .filter((p) => p !== 'body' && p !== 'query' && p !== 'path' && p !== '__root__')
              .join('.')
          : '';
        return loc ? `${loc}: ${msg}` : msg;
      })
      .filter((s): s is string => Boolean(s));
    if (rendered.length > 0) {
      const status = e.response?.status;
      const joined = rendered.join('; ');
      return status ? `${fallback}: ${status} ${joined}` : `${fallback}: ${joined}`;
    }
  }

  if (e.response?.status) {
    const label = e.response.statusText || 'error';
    return `${fallback}: ${e.response.status} ${label}`;
  }

  if (e.message) {
    return `${fallback}: ${e.message}`;
  }

  return fallback;
}
