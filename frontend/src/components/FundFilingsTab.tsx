interface FundFilingsTabProps {
  cik: string;
  name: string;
}

export default function FundFilingsTab({ cik, name }: FundFilingsTabProps) {
  const edgarUrl = `https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=${cik}&type=&dateb=&owner=include&count=40&search_text=&action=getcompany`;

  return (
    <div className="py-6 space-y-6">
      {/* EDGAR link */}
      <div className="bg-white border border-rule p-6">
        <div className="eyebrow text-ink2 mb-3">SEC EDGAR Filings</div>
        <p className="text-sm text-ink2 mb-4">
          All data for this fund is sourced from mandatory SEC filings. View the
          original filings on SEC EDGAR.
        </p>
        <a
          href={edgarUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-2 px-4 py-2.5 bg-navy text-white text-sm font-medium hover:bg-navy/90 transition-colors"
        >
          View filings on EDGAR
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
          </svg>
        </a>
      </div>

      {/* Source attribution */}
      <div className="bg-surface/50 border border-rule p-6">
        <div className="eyebrow text-ink2 mb-3">Source Data</div>
        <div className="text-sm text-ink2 space-y-2">
          <p>
            Fund-level analytics are derived from BDC 10-K and 10-Q filings with
            structured XBRL investment schedules. Portfolio characteristics, holdings,
            and returns are computed from these filings.
          </p>
          <p className="text-xs text-ink3">
            CIK: {cik} &middot; {name}
          </p>
        </div>
      </div>
    </div>
  );
}
