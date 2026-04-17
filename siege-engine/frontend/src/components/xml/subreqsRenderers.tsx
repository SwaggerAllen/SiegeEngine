import { CollapsibleSection } from './CollapsibleSection';
import type { XmlRendererMap } from './types';
import { findChild, findChildText } from './types';

/**
 * Renderer overrides for the subrequirements schema:
 *
 *   <subrequirements>
 *     <subresponsibility>
 *       <name>Card Tokenization</name>
 *       <intent>…</intent>
 *       <derived-from>
 *         <resp id="resp_..."/>
 *       </derived-from>
 *     </subresponsibility>
 *     …
 *   </subrequirements>
 *
 * Parallel to requirementsRenderers but with a <derived-from>
 * chip strip replacing the resp list. Each subresp becomes a
 * bordered card with name + intent + the parent resp IDs it
 * decomposes.
 */
export const subreqsRenderers: XmlRendererMap = {
  subrequirements: (node, ctx) => (
    <div className="not-prose space-y-3">
      {ctx.renderChildren(node.children)}
    </div>
  ),

  subresponsibility: (node) => {
    const name = findChildText(node, 'name') ?? 'Untitled';
    const intent = findChildText(node, 'intent') ?? '';
    const derivedNode = findChild(node, 'derived-from');
    const parentIds: string[] = derivedNode
      ? derivedNode.children
          .filter((c) => c.type === 'element' && c.name === 'resp')
          .map((c) => {
            if (c.type !== 'element') return '';
            const id = c.attributes.id;
            return typeof id === 'string' ? id : '';
          })
          .filter(Boolean)
      : [];
    const meta =
      parentIds.length > 0 ? (
        <span className="text-gray-500">{parentIds.length} from</span>
      ) : undefined;
    return (
      <CollapsibleSection summary={name} meta={meta}>
        {intent && <p className="text-sm text-gray-300 m-0">{intent}</p>}
        {parentIds.length > 0 && (
          <div className="space-y-1">
            <div className="text-[10px] uppercase tracking-wider text-gray-500">
              Derived from
            </div>
            <div className="flex flex-wrap gap-1">
              {parentIds.map((pid) => (
                <span
                  key={pid}
                  className="text-[10px] font-mono bg-gray-900/60 border border-gray-700 rounded px-1.5 py-0.5 text-gray-400"
                >
                  {pid}
                </span>
              ))}
            </div>
          </div>
        )}
      </CollapsibleSection>
    );
  },

  // Consumed by parent — null at top level.
  name: () => null,
  intent: () => null,
  'derived-from': () => null,
  resp: () => null,
};
