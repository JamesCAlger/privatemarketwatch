import Link from 'next/link';

export default function Footer() {
  return (
    <footer className="bg-navy mt-16">
      <div className="mx-auto max-w-6xl px-4 sm:px-6 py-8">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-8 text-sm">
          <div>
            <h3 className="font-semibold text-white mb-2">Navigation</h3>
            <ul className="space-y-1 text-white/60">
              <li><Link href="/" className="hover:text-teal transition-colors">Home</Link></li>
              <li><Link href="/indices/direct-lending" className="hover:text-teal transition-colors">Direct Lending</Link></li>
              <li><Link href="/indices/direct-equity" className="hover:text-teal transition-colors">Direct Equity</Link></li>
              <li><Link href="/methodology" className="hover:text-teal transition-colors">Methodology</Link></li>
              <li><Link href="/about" className="hover:text-teal transition-colors">About</Link></li>
            </ul>
          </div>
          <div>
            <h3 className="font-semibold text-white mb-2">Disclaimer</h3>
            <p className="text-white/60 text-xs leading-relaxed">
              Does not constitute investment advice. Past performance is not
              indicative of future results. No warranty is made as to the
              accuracy or completeness of the data.
            </p>
          </div>
        </div>
        <div className="mt-8 pt-4 border-t border-white/10 text-center text-xs text-white/40">
          All data derived from mandatory SEC regulatory filings. Independent. Transparent. Rules-based.
        </div>
      </div>
    </footer>
  );
}
