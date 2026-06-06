'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useState, useEffect, useRef } from 'react';
import { INDICES } from '@/lib/constants';
import type { IndexSummary } from '@/lib/types';
import HomepageSparkline from './HomepageSparkline';

interface HeaderProps {
  indexSummaries?: IndexSummary[];
}

const NAV_ITEMS = [
  { label: 'Funds', href: '/' },
  { label: 'Indices', href: '/indices' },
  { label: 'Methodology', href: '/methodology' },
  { label: 'About', href: '/about' },
];

function getNavActive(pathname: string): string {
  if (pathname.startsWith('/indices')) return 'Indices';
  if (pathname === '/' || pathname.startsWith('/funds')) return 'Funds';
  if (pathname.startsWith('/methodology')) return 'Methodology';
  if (pathname.startsWith('/about')) return 'About';
  return '';
}

export default function Header({ indexSummaries = [] }: HeaderProps) {
  const pathname = usePathname();
  const [menuOpen, setMenuOpen] = useState(false);
  const [hidden, setHidden] = useState(false);
  const lastScrollY = useRef(0);
  const active = getNavActive(pathname);

  useEffect(() => {
    const onScroll = () => {
      const y = window.scrollY;
      if (y > 120 && y > lastScrollY.current) {
        setHidden(true);
      } else {
        setHidden(false);
      }
      lastScrollY.current = y;
    };
    window.addEventListener('scroll', onScroll, { passive: true });
    return () => window.removeEventListener('scroll', onScroll);
  }, []);

  return (
    <header className={`bg-navy text-white/[0.78] sticky top-0 z-50 transition-transform duration-300 ${
      hidden ? '-translate-y-full' : 'translate-y-0'
    }`}>
      {/* Row 1: Utility bar */}
      <div className="hidden md:flex items-center justify-between px-[72px] py-2.5 border-b border-white/[0.06] text-[11px] tracking-[0.06em]">
        <span className="text-white/55">
          As of Q4 2025 &middot; Data derived from mandatory SEC filings
        </span>
        <div className="flex gap-[18px]">
          <span>EN &#x25BE;</span>
          <span className="cursor-default">For Advisors</span>
          <span className="cursor-default">For Institutions</span>
          <span className="cursor-default">Login</span>
        </div>
      </div>

      {/* Row 2: Main nav */}
      <div className="flex items-center justify-between px-4 md:px-[72px] py-4 md:py-5">
        {/* Logo + tagline */}
        <Link href="/" className="flex items-baseline gap-3.5 no-underline">
          <span className="font-display text-[26px] text-white tracking-[-0.005em] font-medium">
            Metris Lens
          </span>
          <span className="hidden sm:inline eyebrow text-accent tracking-[0.2em]">
            Data &middot; Indices &middot; Research
          </span>
        </Link>

        {/* Desktop nav items */}
        <nav className="hidden md:flex items-center gap-7 text-[13px] font-medium">
          {NAV_ITEMS.map(({ label, href }) => {
            const isActive = label === active;
            return (
              <Link
                key={label}
                href={href}
                className={`pb-1 border-b-2 transition-colors ${
                  isActive
                    ? 'border-accent text-white'
                    : 'border-transparent text-white/[0.78] hover:text-white'
                }`}
              >
                {label}
              </Link>
            );
          })}
          <Link
            href="/about"
            className="px-4 py-2 border border-accent text-accent text-xs tracking-[0.08em] uppercase hover:bg-accent hover:text-navy transition-colors"
          >
            Subscribe &rarr;
          </Link>
        </nav>

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

      {/* Row 3: Index ticker bar */}
      <div className="hidden md:grid grid-cols-[auto_1fr_1fr] items-stretch bg-navyDeep border-t border-white/[0.06] px-[72px]">
        <div className="py-2.5 pr-[18px] flex items-center border-r border-white/[0.14]">
          <span className="eyebrow text-accent tracking-[0.22em]">PMW Indices</span>
        </div>
        {INDICES.map((idx, i) => {
          const s = indexSummaries.find((x) => x.index === idx.key);
          if (!s) return null;
          const isPositive = (s.trailing12m ?? 0) >= 0;
          const retColor = isPositive ? '#7fd6a1' : '#e08c83';
          return (
            <Link
              key={idx.key}
              href={`/indices/${idx.slug}`}
              className={`py-2.5 px-[18px] flex justify-between items-center gap-3.5 no-underline hover:bg-white/[0.03] transition-colors ${
                i < INDICES.length - 1 ? 'border-r border-white/[0.14]' : ''
              }`}
            >
              <div className="flex flex-col gap-px">
                <span className="text-[10px] tracking-[0.16em] uppercase text-white/55">
                  {idx.shortName}
                </span>
                <span className="font-mono text-lg text-white font-medium tabular-nums">
                  {s.level?.toFixed(2)}
                </span>
              </div>
              <div className="flex items-center gap-2" style={{ color: retColor }}>
                {s.sparkline && s.sparkline.length >= 2 && (
                  <HomepageSparkline
                    data={s.sparkline}
                    color={retColor}
                    width={66}
                    height={20}
                  />
                )}
                <span className="font-mono text-[13px] font-semibold tabular-nums">
                  {isPositive ? '+' : ''}
                  {((s.trailing12m ?? 0) * 100).toFixed(1)}%
                </span>
              </div>
            </Link>
          );
        })}
      </div>

      {/* Mobile menu */}
      {menuOpen && (
        <nav className="md:hidden pb-4 border-t border-white/10 pt-3 space-y-1 px-4">
          <Link
            href="/"
            className="block px-2 py-2 text-sm text-white/80 hover:text-accent hover:bg-white/5 transition-colors font-medium"
            onClick={() => setMenuOpen(false)}
          >
            Fund Universe
          </Link>
          <div className="px-2 pt-2 pb-1 eyebrow text-accent">Indices</div>
          {INDICES.map((idx) => (
            <Link
              key={idx.slug}
              href={`/indices/${idx.slug}`}
              className="block px-2 py-2 text-sm text-white/80 hover:text-accent hover:bg-white/5 transition-colors"
              onClick={() => setMenuOpen(false)}
            >
              {idx.name}
            </Link>
          ))}
          <Link
            href="/methodology"
            className="block px-2 py-2 text-sm text-white/80 hover:text-accent hover:bg-white/5 transition-colors"
            onClick={() => setMenuOpen(false)}
          >
            Methodology
          </Link>
          <Link
            href="/about"
            className="block px-2 py-2 text-sm text-white/80 hover:text-accent hover:bg-white/5 transition-colors"
            onClick={() => setMenuOpen(false)}
          >
            About
          </Link>
          <div className="pt-2 px-2 text-xs text-white/30">
            As of Q4 2025
          </div>
        </nav>
      )}
    </header>
  );
}
