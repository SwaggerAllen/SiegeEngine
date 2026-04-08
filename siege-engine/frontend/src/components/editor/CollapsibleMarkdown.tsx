import { useState, useMemo } from 'react';
import Markdown from 'react-markdown';

interface Section {
  heading: string;
  level: number;
  body: string;
}

function splitIntoSections(markdown: string): { preamble: string; sections: Section[] } {
  const lines = markdown.split('\n');
  let preamble = '';
  const sections: Section[] = [];
  let currentSection: Section | null = null;
  let bodyLines: string[] = [];

  for (const line of lines) {
    const match = line.match(/^(#{1,4})\s+(.+)$/);
    if (match) {
      // Flush previous section
      if (currentSection) {
        currentSection.body = bodyLines.join('\n');
        sections.push(currentSection);
      } else {
        preamble = bodyLines.join('\n');
      }
      currentSection = { heading: match[2], level: match[1].length, body: '' };
      bodyLines = [];
    } else {
      bodyLines.push(line);
    }
  }

  // Flush final section
  if (currentSection) {
    currentSection.body = bodyLines.join('\n');
    sections.push(currentSection);
  } else {
    preamble = bodyLines.join('\n');
  }

  return { preamble, sections };
}

interface CollapsibleMarkdownProps {
  children: string;
  className?: string;
}

export function CollapsibleMarkdown({ children, className }: CollapsibleMarkdownProps) {
  const { preamble, sections } = useMemo(() => splitIntoSections(children), [children]);
  const [collapsed, setCollapsed] = useState<Set<number>>(() => new Set());

  const toggle = (idx: number) => {
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(idx)) next.delete(idx);
      else next.add(idx);
      return next;
    });
  };

  // If no sections, just render plain markdown
  if (sections.length === 0) {
    return (
      <div className={className}>
        <Markdown>{preamble}</Markdown>
      </div>
    );
  }

  return (
    <div className={className}>
      {preamble.trim() && <Markdown>{preamble}</Markdown>}
      {sections.map((section, idx) => {
        const isCollapsed = collapsed.has(idx);
        const HeadingTag = `h${section.level}` as keyof JSX.IntrinsicElements;
        return (
          <div key={idx}>
            <HeadingTag
              onClick={() => toggle(idx)}
              className="cursor-pointer select-none flex items-center gap-1.5 group"
            >
              <span
                className="text-gray-500 group-hover:text-gray-300 transition-transform duration-150 text-[10px] inline-block shrink-0"
                style={{ transform: isCollapsed ? undefined : 'rotate(90deg)' }}
              >▶</span>
              {section.heading}
            </HeadingTag>
            {!isCollapsed && section.body.trim() && (
              <Markdown>{section.body}</Markdown>
            )}
          </div>
        );
      })}
    </div>
  );
}
