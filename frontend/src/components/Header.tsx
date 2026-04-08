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
    <header className={`bg-navy sticky top-0 z-50 transition-transform duration-300 ${
      hidden ? '-translate-y-full' : 'translate-y-0'
    }`}>
      <div className="mx-auto max-w-6xl px-4 sm:px-6">
        <div className="flex h-14 md:h-[84px] items-center gap-10">
          {/* Logo */}
          <Link href="/" className="font-bold text-white text-lg md:text-xl shrink-0">
            Private Market Watch
          </Link>

          {/* Desktop nav -- beside the logo */}
          <nav className="hidden md:flex items-center gap-6 text-sm">
            <div
              className="relative"
              onMouseEnter={() => setIndicesOpen(true)}
              onMouseLeave={() => setIndicesOpen(false)}
            >
              <button className={`hover:text-teal transition-colors ${
                pathname.startsWith('/indices') ? 'text-teal font-medium' : 'text-white/70'
              }`}>
                Indices
              </button>
              {indicesOpen && (
                <div className="absolute top-full left-0 pt-1">
                  <div className="bg-white border border-surface-muted rounded-md shadow-lg py-1 min-w-[220px]">
                    {INDICES.map((idx) => (
                      <Link
                        key={idx.slug}
                        href={`/indices/${idx.slug}`}
                        className="block px-4 py-2 text-sm text-navy hover:bg-surface transition-colors"
                        onClick={() => setIndicesOpen(false)}
                      >
                        {idx.shortName}
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

          {/* Spacer to push hamburger right */}
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
          <nav className="md:hidden pb-4 border-t border-white/10 pt-3 space-y-2">
            {INDICES.map((idx) => (
              <Link
                key={idx.slug}
                href={`/indices/${idx.slug}`}
                className="block px-2 py-1.5 text-sm text-white/80 hover:text-teal"
                onClick={() => setMenuOpen(false)}
              >
                <span
                  className="inline-block w-2 h-2 rounded-full mr-2"
                  style={{ backgroundColor: idx.color }}
                />
                {idx.name}
              </Link>
            ))}
            <Link
              href="/methodology"
              className="block px-2 py-1.5 text-sm text-white/80 hover:text-teal"
              onClick={() => setMenuOpen(false)}
            >
              Methodology
            </Link>
            <Link
              href="/about"
              className="block px-2 py-1.5 text-sm text-white/80 hover:text-teal"
              onClick={() => setMenuOpen(false)}
            >
              About
            </Link>
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
      className={`hover:text-teal transition-colors ${
        isActive ? 'text-teal font-medium' : 'text-white/70'
      }`}
    >
      {children}
    </Link>
  );
}
