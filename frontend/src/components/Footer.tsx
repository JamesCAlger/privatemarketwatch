import Link from 'next/link';
import { INDICES } from '@/lib/constants';

export default function Footer() {
  return (
    <footer className="bg-navy text-white/[0.78] mt-16">
      <div className="px-4 md:px-[120px] pt-14 pb-9">
        <div className="grid grid-cols-1 md:grid-cols-[2fr_1fr_1fr_1fr] gap-7">
          {/* Brand blurb */}
          <div>
            <div className="flex items-baseline gap-2.5">
              <span className="font-display text-xl text-white tracking-[-0.005em] font-medium">
                Metris Lens
              </span>
              <span className="eyebrow text-accent tracking-[0.2em]">
                Data &middot; Indices &middot; Research
              </span>
            </div>
            <p className="text-xs leading-relaxed mt-3 max-w-xs">
              Independent, rules-based benchmarks for private credit and equity
              markets -- built entirely from mandatory SEC filings. Does not
              constitute investment advice.
            </p>
          </div>

          {/* Indices */}
          <div>
            <div className="eyebrow text-accent mb-2.5">Indices</div>
            {INDICES.map((idx) => (
              <Link
                key={idx.slug}
                href={`/indices/${idx.slug}`}
                className="block text-xs py-1 text-white/[0.78] hover:text-white transition-colors"
              >
                {idx.shortName}
              </Link>
            ))}
          </div>

          {/* Platform */}
          <div>
            <div className="eyebrow text-accent mb-2.5">Platform</div>
            <Link href="/" className="block text-xs py-1 text-white/[0.78] hover:text-white transition-colors">
              Funds
            </Link>
            <Link href="/methodology" className="block text-xs py-1 text-white/[0.78] hover:text-white transition-colors">
              Methodology
            </Link>
            <Link href="/about" className="block text-xs py-1 text-white/[0.78] hover:text-white transition-colors">
              About
            </Link>
          </div>

          {/* Data Sources */}
          <div>
            <div className="eyebrow text-accent mb-2.5">Data Sources</div>
            <div className="text-xs py-1">SEC EDGAR -- BDC XBRL</div>
            <div className="text-xs py-1">SEC EDGAR -- N-CEN / N-2</div>
          </div>
        </div>

        {/* Bottom strip */}
        <div className="border-t border-white/10 mt-7 pt-3.5 text-[11px] opacity-60 flex flex-col sm:flex-row justify-between gap-2">
          <span>&copy; 2026 Blue Obsidian Enterprises &middot; metrislens.com</span>
          <div className="flex gap-4">
            <Link href="/privacy" className="hover:text-white transition-colors">
              Privacy
            </Link>
            <Link href="/terms" className="hover:text-white transition-colors">
              Terms
            </Link>
          </div>
        </div>
      </div>
    </footer>
  );
}
