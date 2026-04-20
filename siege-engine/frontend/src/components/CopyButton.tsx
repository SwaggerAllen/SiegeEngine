import { useCallback, useState } from 'react';

/**
 * Small "Copy to clipboard" button with a 2-second "Copied"
 * affordance. Used across panels that surface copyable prose
 * (draft XML, feedback history, prompt previews).
 */
export function CopyButton({
  content,
  label = 'Copy',
  title = 'Copy to clipboard',
  className,
}: {
  content: string;
  label?: string;
  title?: string;
  className?: string;
}) {
  const [copied, setCopied] = useState(false);
  const handleCopy = useCallback(() => {
    void navigator.clipboard.writeText(content).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }, [content]);
  return (
    <button
      type="button"
      onClick={handleCopy}
      className={
        className ??
        'px-3 py-1 text-xs rounded border border-gray-700 text-gray-400 hover:bg-gray-800 hover:text-gray-200'
      }
      title={title}
    >
      {copied ? 'Copied' : label}
    </button>
  );
}
