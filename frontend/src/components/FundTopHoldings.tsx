import type { FundHolding } from '@/lib/types';
import { formatDollar, formatPercent } from '@/lib/format';

interface FundTopHoldingsProps {
  holdings: FundHolding[];
}

const CLASSIFICATION_LABELS: Record<string, string> = {
  DIRECT_LENDING: 'Direct Lending',
  COMMON_EQUITY: 'Common Equity',
  PREFERRED_EQUITY: 'Preferred Equity',
  PRIVATE_CREDIT_FUND: 'Credit Fund',
  PRIVATE_EQUITY_FUND: 'PE Fund',
  STRUCTURED_CREDIT: 'Structured Credit',
  HEDGE_FUND: 'Hedge Fund',
  REAL_ESTATE_FUND: 'RE Fund',
  DIRECT_REAL_ESTATE: 'Real Estate',
  CASH: 'Cash',
  UNCLASSIFIED: 'Other',
};

function formatCategory(cat: string | null | undefined): string {
  if (!cat) return '--';
  return CLASSIFICATION_LABELS[cat] ?? cat.toLowerCase().replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}

export default function FundTopHoldings({ holdings }: FundTopHoldingsProps) {
  if (holdings.length === 0) return null;

  // Decide which optional columns to show based on cross-holding coverage
  const n = holdings.length;
  const hasRate = holdings.filter((h) => h.interestRate != null && h.interestRate > 0).length;
  const hasMat = holdings.filter((h) => h.maturityDate != null).length;
  const hasLien = holdings.filter((h) => h.lienPosition != null).length;
  const showRate = hasRate / n >= 0.3;
  const showMaturity = hasMat / n >= 0.3;
  const showLien = hasLien / n >= 0.3;

  return (
    <div className="bg-white rounded-lg shadow-card overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="bg-navy">
            <th className="py-3 px-4 text-left text-xs font-medium text-white/70 uppercase tracking-wider">
              Issuer
            </th>
            <th className="py-3 px-4 text-left text-xs font-medium text-white/70 uppercase tracking-wider">
              Type
            </th>
            {showLien && (
              <th className="py-3 px-4 text-left text-xs font-medium text-white/70 uppercase tracking-wider">
                Lien
              </th>
            )}
            {showRate && (
              <th className="py-3 px-4 text-right text-xs font-medium text-white/70 uppercase tracking-wider">
                Rate
              </th>
            )}
            {showMaturity && (
              <th className="py-3 px-4 text-right text-xs font-medium text-white/70 uppercase tracking-wider">
                Maturity
              </th>
            )}
            <th className="py-3 px-4 text-right text-xs font-medium text-white/70 uppercase tracking-wider">
              Fair Value
            </th>
            <th className="py-3 px-4 text-right text-xs font-medium text-white/70 uppercase tracking-wider">
              % Portfolio
            </th>
          </tr>
        </thead>
        <tbody>
          {holdings.map((h, i) => (
            <tr
              key={i}
              className={`border-b border-surface last:border-0 ${
                i % 2 === 1 ? 'bg-surface/30' : ''
              }`}
            >
              <td className="py-2.5 px-4 font-medium text-navy max-w-[240px] truncate">
                {h.issuerName}
              </td>
              <td className="py-2.5 px-4 text-muted text-xs">
                {formatCategory(h.assetCategory)}
              </td>
              {showLien && (
                <td className="py-2.5 px-4 text-xs">
                  {h.lienPosition ? (
                    <span className="inline-block px-2 py-0.5 rounded-full bg-surface text-navy text-[11px] font-medium">
                      {h.lienPosition}
                    </span>
                  ) : '--'}
                </td>
              )}
              {showRate && (
                <td className="py-2.5 px-4 text-right tabular-nums">
                  {h.interestRate != null && h.interestRate > 0 ? `${h.interestRate.toFixed(1)}%` : '--'}
                </td>
              )}
              {showMaturity && (
                <td className="py-2.5 px-4 text-right tabular-nums text-muted text-xs">
                  {h.maturityDate ?? '--'}
                </td>
              )}
              <td className="py-2.5 px-4 text-right tabular-nums font-medium">
                {formatDollar(h.fairValue)}
              </td>
              <td className="py-2.5 px-4 text-right tabular-nums">
                {h.pctOfPortfolio != null ? formatPercent(h.pctOfPortfolio) : '--'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
