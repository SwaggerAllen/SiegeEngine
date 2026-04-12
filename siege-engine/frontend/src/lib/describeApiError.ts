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
  // Render the first entry so the user sees *something*.
  if (Array.isArray(detail) && detail.length > 0) {
    const first = detail[0];
    if (typeof first === 'object' && first !== null && 'msg' in first) {
      return `${fallback}: ${(first as { msg: string }).msg}`;
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
