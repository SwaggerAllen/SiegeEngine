import XMLViewer from 'react-xml-viewer';

interface Props {
  /** Raw XML string — LLM-emitted ``<features>``/``<requirements>``/etc. */
  content: string;
  /** Optional className forwarded to the wrapping container. */
  className?: string;
}

// Dark-mode theme matching the rest of the dashboard palette.
// react-xml-viewer's defaults are tuned for light backgrounds.
const DARK_THEME = {
  tagColor: '#f97316', // orange-500
  textColor: '#e5e7eb', // gray-200
  attributeKeyColor: '#60a5fa', // blue-400
  attributeValueColor: '#86efac', // green-300
  separatorColor: '#9ca3af', // gray-400
  commentColor: '#6b7280', // gray-500
  cdataColor: '#86efac', // green-300
  fontFamily:
    'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace',
};

/**
 * Render a block of LLM-emitted XML (a ``<features>``,
 * ``<requirements>``, etc. payload) as a pretty-printed,
 * syntax-highlighted, collapsible viewer.
 *
 * We render the canonical stored string directly — the viewer
 * handles pretty-printing internally, so the byte-for-byte content
 * on the server stays identical to what the LLM produced.
 */
export function XmlBlock({ content, className = '' }: Props) {
  return (
    <div
      className={
        'text-xs bg-gray-900/60 border border-gray-700 rounded p-3 ' +
        'overflow-x-auto ' +
        className
      }
      data-testid="xml-block"
    >
      <XMLViewer
        xml={content}
        theme={DARK_THEME}
        indentSize={2}
        collapsible
        invalidXml={
          <pre className="whitespace-pre-wrap break-words text-gray-400">
            {content}
          </pre>
        }
      />
    </div>
  );
}
