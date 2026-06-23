'use client';

import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { useState, useEffect, useRef, useCallback, useMemo } from 'react';

interface FundSearchItem {
  cik: string;
  name: string;
  ticker: string | null;
  adviser: string | null;
}

interface HeaderProps {
  fundCount?: number;
  fundSearchItems?: FundSearchItem[];
}

const NAV_ITEMS = [
  { label: 'Funds', href: '/' },
  { label: 'Methodology', href: '/methodology' },
  { label: 'About', href: '/about' },
];

function getNavActive(pathname: string): string {
  if (pathname === '/' || pathname.startsWith('/funds')) return 'Funds';
  if (pathname.startsWith('/methodology')) return 'Methodology';
  if (pathname.startsWith('/about')) return 'About';
  return '';
}

export default function Header({ fundCount, fundSearchItems = [] }: HeaderProps) {
  const pathname = usePathname();
  const router = useRouter();
  const [menuOpen, setMenuOpen] = useState(false);
  const [hidden, setHidden] = useState(false);
  const lastScrollY = useRef(0);
  const active = getNavActive(pathname);

  const [searchQuery, setSearchQuery] = useState('');
  const [searchFocused, setSearchFocused] = useState(false);
  const [selectedIdx, setSelectedIdx] = useState(-1);
  const searchRef = useRef<HTMLDivElement>(null);

  const searchResults = useMemo(() => searchQuery.trim().length >= 2
    ? fundSearchItems.filter((f) => {
        const q = searchQuery.toLowerCase();
        return (
          f.name.toLowerCase().includes(q) ||
          (f.ticker && f.ticker.toLowerCase().includes(q)) ||
          (f.adviser && f.adviser.toLowerCase().includes(q)) ||
          f.cik.includes(q)
        );
      }).slice(0, 8)
    : [], [searchQuery, fundSearchItems]);

  const showDropdown = searchFocused && searchResults.length > 0;

  const handleSearchKey = useCallback((e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setSelectedIdx((i) => Math.min(i + 1, searchResults.length - 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setSelectedIdx((i) => Math.max(i - 1, 0));
    } else if (e.key === 'Enter' && selectedIdx >= 0 && searchResults[selectedIdx]) {
      router.push(`/funds/${searchResults[selectedIdx].cik}`);
      setSearchQuery('');
      setSearchFocused(false);
    } else if (e.key === 'Escape') {
      setSearchFocused(false);
    }
  }, [searchResults, selectedIdx, router]);

  useEffect(() => { setSelectedIdx(-1); }, [searchQuery]);

  // Close dropdown on click outside
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (searchRef.current && !searchRef.current.contains(e.target as Node)) {
        setSearchFocused(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

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
      <div className="hidden md:block border-b border-white/[0.06]">
        <div className="max-w-[1180px] mx-auto flex items-center justify-between px-6 py-2.5 text-[11px] tracking-[0.06em]">
          <span className="text-white/55">
            As of Q4 2025
          </span>
          <div className="flex gap-[18px]">
            <span>EN &#x25BE;</span>
            <span className="cursor-default">For Advisors</span>
            <span className="cursor-default">For Institutions</span>
            <span className="cursor-default">Login</span>
          </div>
        </div>
      </div>

      {/* Row 2: Main nav */}
      <div className="max-w-[1180px] mx-auto flex items-center justify-between px-4 md:px-6 py-4 md:py-5">
        {/* Logo + tagline */}
        <Link href="/" className="flex items-baseline gap-3.5 no-underline shrink-0">
          <span className="font-display text-[26px] text-white tracking-[-0.005em] font-medium whitespace-nowrap">
            Metris Lens
          </span>
          <span className="hidden lg:inline eyebrow text-accent tracking-[0.2em] whitespace-nowrap">
            Data &middot; Research
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

      {/* Row 3: Fund lookup bar */}
      <div className="hidden md:block bg-navyDeep border-t border-white/[0.06]">
        <div ref={searchRef} className="max-w-[1180px] mx-auto px-6 py-2 flex items-center gap-3 relative">
          <label htmlFor="fund-search" className="eyebrow text-accent tracking-[0.22em] shrink-0 cursor-default">
            Fund Lookup
          </label>
          <input
            id="fund-search"
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            onFocus={() => setSearchFocused(true)}
            onKeyDown={handleSearchKey}
            placeholder={`Search ${fundCount ?? ''} funds by name, ticker, or CIK...`}
            className="flex-1 bg-white/[0.07] border border-white/[0.12] text-white text-[12px] px-3 py-1.5 placeholder:text-white/30 focus:outline-none focus:border-accent/50 min-w-0"
          />
          {showDropdown && (
            <div className="absolute top-full left-0 right-[18px] mt-1 bg-navy border border-white/[0.15] shadow-lg z-50 max-h-[320px] overflow-y-auto">
              {searchResults.map((f, i) => (
                <Link
                  key={f.cik}
                  href={`/funds/${f.cik}`}
                  className={`block px-3 py-2.5 no-underline transition-colors ${
                    i === selectedIdx ? 'bg-white/[0.08]' : 'hover:bg-white/[0.05]'
                  }`}
                  onClick={() => { setSearchQuery(''); setSearchFocused(false); }}
                >
                  <div className="flex items-baseline gap-2">
                    <span className="text-[12px] text-white font-medium truncate">{f.name}</span>
                    {f.ticker && (
                      <span className="font-mono text-[11px] text-accent tabular-nums shrink-0">{f.ticker}</span>
                    )}
                  </div>
                  {f.adviser && (
                    <div className="text-[10px] text-white/40 mt-0.5 truncate">{f.adviser}</div>
                  )}
                </Link>
              ))}
            </div>
          )}
        </div>
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
