'use client';

import { useState, useEffect } from 'react';

interface TOCSection {
  id: string;
  title: string;
}

interface MethodologyTOCProps {
  sections: readonly TOCSection[];
}

export default function MethodologyTOC({ sections }: MethodologyTOCProps) {
  const [activeId, setActiveId] = useState(sections[0]?.id ?? '');

  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            setActiveId(entry.target.id);
          }
        }
      },
      { rootMargin: '-20% 0px -70% 0px', threshold: 0 },
    );

    for (const section of sections) {
      const el = document.getElementById(section.id);
      if (el) observer.observe(el);
    }

    return () => observer.disconnect();
  }, [sections]);

  return (
    <nav className="hidden lg:block w-52 shrink-0">
      <div className="sticky top-20">
        <p className="eyebrow text-accent mb-3">Contents</p>
        <ul className="space-y-0.5 text-sm">
          {sections.map((s, i) => {
            const isActive = s.id === activeId;
            return (
              <li key={s.id}>
                <a
                  href={`#${s.id}`}
                  className={`flex items-center gap-2.5 py-1.5 transition-colors ${
                    isActive
                      ? 'text-teal font-medium'
                      : 'text-ink3 hover:text-teal'
                  }`}
                >
                  <span className={`w-5 h-5 rounded-full text-xs flex items-center justify-center shrink-0 font-medium ${
                    isActive
                      ? 'bg-teal text-white'
                      : 'bg-surface-muted text-navy/40'
                  }`}>
                    {i + 1}
                  </span>
                  {s.title}
                </a>
              </li>
            );
          })}
        </ul>
      </div>
    </nav>
  );
}
