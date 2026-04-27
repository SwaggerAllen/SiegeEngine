import { useMemo, type ReactNode } from 'react';
import { parseXmlAll } from './parser';
import { renderUnknownElement } from './defaultRenderers';
import type { XmlNode, XmlRendererMap, XmlRenderContext } from './types';

interface Props {
  /** Raw XML string (typically the committed LLM output). */
  content: string;
  /**
   * Per-tag renderer overrides. Keys are lowercase tag names.
   * Tags without an entry fall through to the schema-agnostic
   * default renderer. Pass ``{}`` (or omit) to render with
   * defaults only.
   */
  renderers?: XmlRendererMap;
  /** Extra classes applied to the outer wrapper. */
  className?: string;
  /**
   * Optional fallback invoked when parsing fails — useful when
   * the content is meant to be XML but came back malformed (e.g.
   * a CLI failure mid-stream). Defaults to showing the raw string
   * in a ``<pre>``.
   */
  fallback?: (raw: string, error: Error) => ReactNode;
}

/**
 * Render a block of LLM-emitted XML as a formatted document.
 *
 * This component is schema-agnostic on its own — you get a
 * reasonable prose rendering of any XML tree out of the box — and
 * becomes schema-specific when you pass a ``renderers`` map. Each
 * pipeline bootstrap doc (features, reqs, sysarch, manifest)
 * ships its own renderer map alongside its React panel
 * and composes them in.
 *
 * Parsing happens in ``useMemo`` so re-renders don't re-parse
 * identical content. Parse failures surface the raw string via
 * ``fallback`` rather than crashing the tree — the generation
 * handler guarantees validated output on the happy path, so
 * seeing the fallback usually means something went wrong upstream
 * and the user would rather see the broken text than a blank
 * panel.
 */
export function XmlDocument({
  content,
  renderers = {},
  className,
  fallback,
}: Props) {
  const parsed = useMemo(() => {
    try {
      const roots = parseXmlAll(content);
      if (roots.length === 0) {
        return {
          roots: null,
          error: new Error('No root element found in XML'),
        };
      }
      return { roots, error: null as Error | null };
    } catch (err) {
      return {
        roots: null,
        error: err instanceof Error ? err : new Error(String(err)),
      };
    }
  }, [content]);

  if (parsed.roots === null) {
    if (fallback) return <>{fallback(content, parsed.error!)}</>;
    return (
      <pre className="whitespace-pre-wrap break-words text-xs text-gray-400">
        {content}
      </pre>
    );
  }

  // Render every top-level element in document order. Bootstrap
  // tiers (expansion / requirements / sysarch) emit two roots —
  // an ``<introduction>`` preamble plus the main block — so a
  // single-root render would silently drop everything past the
  // introduction.
  return (
    <div
      className={
        className ?? 'prose prose-invert prose-sm max-w-none prose-headings:mb-2'
      }
    >
      {parsed.roots.map((root, i) => (
        <XmlNodeView key={i} node={root} depth={0} renderers={renderers} />
      ))}
    </div>
  );
}

/** Render a single ``XmlNode`` — text nodes pass through, elements
 *  dispatch via the renderer map with a fallback to the default. */
function XmlNodeView({
  node,
  depth,
  renderers,
}: {
  node: XmlNode;
  depth: number;
  renderers: XmlRendererMap;
}) {
  if (node.type === 'text') {
    const trimmed = node.value.trim();
    if (!trimmed) return null;
    return <>{trimmed}</>;
  }

  const ctx: XmlRenderContext = {
    depth,
    renderers,
    renderChildren: (children) =>
      children.map((child, i) => (
        <XmlNodeView
          key={i}
          node={child}
          depth={depth + 1}
          renderers={renderers}
        />
      )),
    renderNode: (n, key) => (
      <XmlNodeView
        key={key}
        node={n}
        depth={depth + 1}
        renderers={renderers}
      />
    ),
  };

  const custom = renderers[node.name];
  if (custom) return <>{custom(node, ctx)}</>;
  return <>{renderUnknownElement(node, ctx)}</>;
}
