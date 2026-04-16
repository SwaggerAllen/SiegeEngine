import { useState, type ReactNode } from 'react';

interface Props {
  document: ReactNode;
  nodes: ReactNode;
  prompt?: ReactNode;
  idPrefix: string;
  nodesLabel?: string;
}

export function BootstrapSubtabs({
  document,
  nodes,
  prompt,
  idPrefix,
  nodesLabel = 'Nodes',
}: Props) {
  const [active, setActive] = useState<'document' | 'nodes' | 'prompt'>('document');
  const baseClasses =
    'px-3 py-1.5 text-xs border-b-2 -mb-px transition-colors shrink-0 whitespace-nowrap';
  const activeClasses = 'border-blue-500 text-white';
  const idleClasses =
    'border-transparent text-gray-400 hover:text-gray-200 hover:border-gray-600 cursor-pointer';

  return (
    <div className="h-full flex flex-col">
      <nav
        className="border-b border-gray-800 px-3 flex items-center gap-1 shrink-0 overflow-x-auto"
        role="tablist"
        aria-label={`${idPrefix} subtabs`}
      >
        <button
          type="button"
          role="tab"
          aria-selected={active === 'document'}
          aria-controls={`subtabpanel-${idPrefix}-document`}
          onClick={() => setActive('document')}
          className={
            active === 'document'
              ? `${baseClasses} ${activeClasses}`
              : `${baseClasses} ${idleClasses}`
          }
        >
          Document
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={active === 'nodes'}
          aria-controls={`subtabpanel-${idPrefix}-nodes`}
          onClick={() => setActive('nodes')}
          className={
            active === 'nodes'
              ? `${baseClasses} ${activeClasses}`
              : `${baseClasses} ${idleClasses}`
          }
        >
          {nodesLabel}
        </button>
        {prompt && (
          <button
            type="button"
            role="tab"
            aria-selected={active === 'prompt'}
            aria-controls={`subtabpanel-${idPrefix}-prompt`}
            onClick={() => setActive('prompt')}
            className={
              active === 'prompt'
                ? `${baseClasses} ${activeClasses}`
                : `${baseClasses} ${idleClasses}`
            }
          >
            Prompt
          </button>
        )}
      </nav>
      <div className="flex-1 overflow-auto">
        {active === 'document' && (
          <div
            role="tabpanel"
            id={`subtabpanel-${idPrefix}-document`}
            className="h-full"
          >
            {document}
          </div>
        )}
        {active === 'nodes' && (
          <div
            role="tabpanel"
            id={`subtabpanel-${idPrefix}-nodes`}
            className="h-full"
          >
            {nodes}
          </div>
        )}
        {active === 'prompt' && prompt && (
          <div
            role="tabpanel"
            id={`subtabpanel-${idPrefix}-prompt`}
            className="h-full"
          >
            {prompt}
          </div>
        )}
      </div>
    </div>
  );
}
