import Link from 'next/link';
import { INDICES } from '@/lib/constants';

export default function Footer() {
  return (
    <footer className="hero-gradient mt-16">
      <div className="mx-auto max-w-6xl px-4 sm:px-6 py-12">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-10 text-sm">
          {/* Brand block */}
          <div>
            <div className="flex items-center gap-2.5 mb-3">
              <svg width="24" height="24" viewBox="0 0 28 28" fill="none">
                <path d="M4 7L12 14L4 21" stroke="#2A9D8F" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"/>
                <path d="M12 7L20 14L12 21" stroke="#3DB8A9" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" opacity="0.7"/>
              </svg>
              <span className="font-bold text-white text-base">Private Market Watch</span>
            </div>
            <p className="text-white/50 text-xs leading-relaxed max-w-xs">
              Fund data, portfolio analytics, and position-level indices for
              private credit and equity markets -- built from mandatory SEC filings.
            </p>
          </div>

          {/* Quick links */}
          <div className="grid grid-cols-2 gap-6">
            <div>
              <h3 className="font-semibold text-white/70 text-xs uppercase tracking-wider mb-3">Indices</h3>
              <ul className="space-y-2 text-white/50">
                {INDICES.map((idx) => (
                  <li key={idx.slug}>
                    <Link href={`/indices/${idx.slug}`} className="hover:text-teal transition-colors flex items-center gap-2">
                      <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ backgroundColor: idx.color }} />
                      {idx.shortName}
                    </Link>
                  </li>
                ))}
              </ul>
            </div>
            <div>
              <h3 className="font-semibold text-white/70 text-xs uppercase tracking-wider mb-3">Resources</h3>
              <ul className="space-y-2 text-white/50">
                <li><Link href="/" className="hover:text-teal transition-colors">Home</Link></li>
                <li><Link href="/methodology" className="hover:text-teal transition-colors">Methodology</Link></li>
                <li><Link href="/about" className="hover:text-teal transition-colors">About</Link></li>
              </ul>
            </div>
          </div>

          {/* Data sources + disclaimer */}
          <div>
            <h3 className="font-semibold text-white/70 text-xs uppercase tracking-wider mb-3">Data Sources</h3>
            <ul className="space-y-1.5 text-white/50 text-xs mb-4">
              <li>SEC EDGAR -- BDC XBRL (10-K/10-Q)</li>
              <li>SEC EDGAR -- N-PORT (quarterly TSV)</li>
              <li>SEC EDGAR -- N-CEN / N-2 (universe)</li>
            </ul>
            <p className="text-white/30 text-xs leading-relaxed">
              Does not constitute investment advice. Past performance is not
              indicative of future results.
            </p>
          </div>
        </div>

        <div className="mt-10 pt-6 border-t border-white/10 flex flex-col sm:flex-row items-center justify-between gap-3 text-xs text-white/30">
          <span>All data derived from mandatory SEC regulatory filings.</span>
          <span>Independent. Transparent. Rules-based.</span>
        </div>
      </div>
    </footer>
  );
}
