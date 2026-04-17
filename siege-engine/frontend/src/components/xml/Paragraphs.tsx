/**
 * Splits a prose string on blank-line paragraph breaks and
 * renders each chunk in its own ``<p>``. Used by tier content
 * renderers (techspec, pubapi, privapi, role, api-intent,
 * rationale) to turn walls of text into scannable paragraph
 * blocks.
 *
 * Input rules:
 *   - Paragraphs are separated by one or more blank lines
 *     (``\n\n+``). Whitespace around each paragraph is trimmed.
 *   - Empty strings render nothing.
 *   - A single paragraph (no blank-line breaks) renders one
 *     ``<p>`` — no regression vs. the old single-``<p>`` layout.
 *
 * The ``<p>`` keeps ``whitespace-pre-wrap`` so any literal
 * newlines the LLM emits within a paragraph stay visible. Blank
 * lines between paragraphs become the visual gap between
 * ``<p>`` blocks instead of collapsing into the flow.
 */
export function Paragraphs({ text, className }: { text: string; className?: string }) {
  const trimmed = text.trim();
  if (!trimmed) return null;
  const paragraphs = trimmed
    .split(/\n\s*\n/)
    .map((p) => p.trim())
    .filter((p) => p.length > 0);
  const cls = className ?? 'text-sm text-gray-300 m-0 whitespace-pre-wrap';
  return (
    <div className="space-y-3">
      {paragraphs.map((p, i) => (
        <p key={i} className={cls}>
          {p}
        </p>
      ))}
    </div>
  );
}
