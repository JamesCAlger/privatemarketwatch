'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useState, useEffect, useRef } from 'react';
import { INDICES } from '@/lib/constants';

export default function Header() {
  const pathname = usePathname();
  const [menuOpen, setMenuOpen] = useState(false);
  const [indicesOpen, setIndicesOpen] = useState(false);
  const [hidden, setHidden] = useState(false);
  const lastScrollY = useRef(0);

  useEffect(() => {
    const onScroll = () => {
      const y = window.scrollY;
      if (y > 56 && y > lastScrollY.current) {
        setHidden(true);
        setIndicesOpen(false);
      } else {
        setHidden(false);
      }
      lastScrollY.current = y;
    };
    window.addEventListener('scroll', onScroll, { passive: true });
    return () => window.removeEventListener('scroll', onScroll);
  }, []);

  return (
    <header className={`bg-navy sticky top-0 z-50 transition-transform duration-300 border-b border-teal/30 ${
      hidden ? '-translate-y-full' : 'translate-y-0'
    }`}>
      <div className="mx-auto max-w-6xl px-4 sm:px-6">
        <div className="flex h-14 md:h-16 items-center gap-8">
          {/* Logo */}
          <Link href="/" className="flex items-center gap-2.5 shrink-0 group">
            <svg width="28" height="28" viewBox="0 0 28 28" fill="none" className="shrink-0">
              <path d="M4 7L12 14L4 21" stroke="#2A9D8F" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"/>
              <path d="M12 7L20 14L12 21" stroke="#3DB8A9" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" opacity="0.7"/>
            </svg>
            <span className="font-bold text-white text-base md:text-lg tracking-tight">
              Private Market Watch
            </span>
          </Link>

          {/* Desktop nav */}
          <nav className="hidden md:flex items-center gap-1 text-sm flex-1">
            <div
              className="relative"
              onMouseEnter={() => setIndicesOpen(true)}
              onMouseLeave={() => setIndicesOpen(false)}
            >
              <button className={`relative px-3 py-5 hover:text-teal transition-colors ${
                pathname.startsWith('/indices') ? 'text-white font-medium' : 'text-white/70'
              }`}>
                Indices
                <svg className="inline-block ml-1 w-3 h-3 opacity-50" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                </svg>
                {pathname.startsWith('/indices') && (
                  <span className="absolute bottom-0 left-3 right-3 h-0.5 bg-teal rounded-full" />
                )}
              </button>
              {indicesOpen && (
                <div className="absolute top-full left-0 pt-0.5">
                  <div className="bg-white border border-surface-muted rounded-lg shadow-panel py-1.5 min-w-[240px]">
                    {INDICES.map((idx) => (
                      <Link
                        key={idx.slug}
                        href={`/indices/${idx.slug}`}
                        className="flex items-center gap-3 px-4 py-2.5 text-sm text-navy hover:bg-surface transition-colors"
                        onClick={() => setIndicesOpen(false)}
                      >
                        <span
                          className="w-2 h-2 rounded-full shrink-0"
                          style={{ backgroundColor: idx.color }}
                        />
                        <span>{idx.shortName}</span>
                      </Link>
                    ))}
                  </div>
                </div>
              )}
            </div>
            <NavLink href="/methodology" current={pathname}>
              Methodology
            </NavLink>
            <NavLink href="/about" current={pathname}>
              About
            </NavLink>
          </nav>

          {/* As-of date indicator (desktop) */}
          <div className="hidden md:block text-xs text-white/40 shrink-0">
            As of Q4 2025
          </div>

          {/* Spacer for mobile */}
          <div className="flex-1 md:hidden" />

          {/* Mobile hamburger */}
          <button
            className="md:hidden p-2 text-white/70"
            onClick={() => setMenuOpen(!menuOpen)}
            aria-label="Toggle menu"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              {menuOpen ? (
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              ) : (
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
              )}
            </svg>
          </button>
        </div>

        {/* Mobile menu */}
        {menuOpen && (
          <nav className="md:hidden pb-4 border-t border-white/10 pt-3 space-y-1">
            {INDICES.map((idx) => (
              <Link
                key={idx.slug}
                href={`/indices/${idx.slug}`}
                className="flex items-center gap-2.5 px-2 py-2 text-sm text-white/80 hover:text-teal rounded-md hover:bg-white/5 transition-colors"
                onClick={() => setMenuOpen(false)}
              >
                <span
                  className="w-2 h-2 rounded-full shrink-0"
                  style={{ backgroundColor: idx.color }}
                />
                {idx.name}
              </Link>
            ))}
            <Link
              href="/methodology"
              className="block px-2 py-2 text-sm text-white/80 hover:text-teal rounded-md hover:bg-white/5 transition-colors"
              onClick={() => setMenuOpen(false)}
            >
              Methodology
            </Link>
            <Link
              href="/about"
              className="block px-2 py-2 text-sm text-white/80 hover:text-teal rounded-md hover:bg-white/5 transition-colors"
              onClick={() => setMenuOpen(false)}
            >
              About
            </Link>
            <div className="pt-2 px-2 text-xs text-white/30">
              As of Q4 2025
            </div>
          </nav>
        )}
      </div>
    </header>
  );
}

function NavLink({
  href,
  current,
  children,
}: {
  href: string;
  current: string;
  children: React.ReactNode;
}) {
  const isActive = current === href;
  return (
    <Link
      href={href}
      className={`relative px-3 py-5 hover:text-teal transition-colors ${
        isActive ? 'text-white font-medium' : 'text-white/70'
      }`}
    >
      {children}
      {isActive && (
        <span className="absolute bottom-0 left-3 right-3 h-0.5 bg-teal rounded-full" />
      )}
    </Link>
  );
}
