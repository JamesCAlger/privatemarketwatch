'use client';

import { useState, useMemo } from 'react';
import { useRouter } from 'next/navigation';
import type { FundListItem } from '@/lib/types';
import { formatDollar } from '@/lib/format';
import { getFundNameParts } from '@/lib/nameFormat';

type SortKey = 'name' | 'totalAssets' | 'navPerShare' | 'distributionRate' | 'quarterlyReturn';

interface FundTableProps {
  funds: FundListItem[];
}

export default function FundTable({ funds }: FundTableProps) {
  const router = useRouter();
  const [search, setSearch] = useState('');
  const [sortKey, setSortKey] = useState<SortKey>('totalAssets');
  const [sortAsc, setSortAsc] = useState(false);

  const filtered = useMemo(() => {
    let result = funds;

    if (search.trim()) {
      const q = search.toLowerCase();
      result = result.filter(
        (f) => {
          const fundParts = getFundNameParts(f.name, f.ticker);
          return (
            f.name.toLowerCase().includes(q) ||
            fundParts.displayName.toLowerCase().includes(q) ||
            (f.ticker ?? '').toLowerCase().includes(q) ||
            (f.adviser ?? '').toLowerCase().includes(q)
          );
        },
      );
    }

    result = [...result].sort((a, b) => {
      let av: number | string | null;
      let bv: number | string | null;
      if (sortKey === 'name') {
        av = getFundNameParts(a.name, a.ticker).displayName.toLowerCase();
        bv = getFundNameParts(b.name, b.ticker).displayName.toLowerCase();
      } else {
        av = a[sortKey];
        bv = b[sortKey];
      }
      if (av == null && bv == null) return 0;
      if (av == null) return 1;
      if (bv == null) return -1;
      if (av < bv) return sortAsc ? -1 : 1;
      if (av > bv) return sortAsc ? 1 : -1;
      return 0;
    });

    return result;
  }, [funds, search, sortKey, sortAsc]);

  const handleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortAsc(!sortAsc);
    } else {
      setSortKey(key);
      setSortAsc(key === 'name');
    }
  };

  const SortHeader = ({ label, col, className }: { label: string; col: SortKey; className?: string }) => (
    <th
      className={`py-3 px-4 text-xs font-medium uppercase tracking-wider cursor-pointer select-none hover:text-white transition-colors ${
        sortKey === col ? 'text-white' : 'text-white/70'
      } ${className ?? ''}`}
      onClick={() => handleSort(col)}
    >
      <span className="inline-flex items-center gap-1">
        {label}
        {sortKey === col && (
          <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
              d={sortAsc ? 'M5 15l7-7 7 7' : 'M19 9l-7 7-7-7'} />
          </svg>
        )}
      </span>
    </th>
  );

  return (
    <div>
      {/* Filter pills */}
      <div className="flex gap-2 mb-3">
        <span className="px-3 py-1 text-[11px] font-medium tracking-[0.04em] bg-navy text-white">
          All
        </span>
        <span className="px-3 py-1 text-[11px] font-medium tracking-[0.04em] border border-rule text-ink3">
          Non-Traded BDC
        </span>
      </div>

      {/* Controls */}
      <div className="flex flex-col sm:flex-row gap-3 mb-4">
        <input
          type="text"
          placeholder={`Search ${funds.length} funds by name, ticker, or adviser...`}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="flex-1 px-4 py-2 text-sm border border-surface-muted bg-white focus:outline-none focus:ring-2 focus:ring-teal/30 focus:border-teal"
        />
      </div>

      {/* Table */}
      <div className="bg-white shadow-card overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-navy">
              <SortHeader label="Fund" col="name" className="text-left" />
              <SortHeader label="AUM" col="totalAssets" className="text-right" />
              <SortHeader label="NAV/Sh" col="navPerShare" className="text-right" />
              <SortHeader label="Dist Rate" col="distributionRate" className="text-right" />
              <SortHeader label="QoQ Return" col="quarterlyReturn" className="text-right" />
            </tr>
          </thead>
          <tbody>
            {filtered.length === 0 && (
              <tr>
                <td colSpan={5} className="py-8 text-center text-muted">
                  No funds match your search.
                </td>
              </tr>
            )}
            {filtered.map((fund, i) => {
              const fundParts = getFundNameParts(fund.name, fund.ticker);
              return (
              <tr
                key={fund.cik}
                onClick={() => router.push(`/funds/${fund.cik}`)}
                className={`border-b border-surface last:border-0 hover:bg-surface/50 transition-colors cursor-pointer ${
                  i % 2 === 1 ? 'bg-surface/30' : ''
                }`}
              >
                <td className="py-3 px-4">
                  <div className="font-medium text-navy truncate max-w-[280px]">{fundParts.displayName}</div>
                </td>
                <td className="py-3 px-4 text-right tabular-nums">
                  {formatDollar(fund.totalAssets)}
                </td>
                <td className="py-3 px-4 text-right tabular-nums">
                  {fund.navPerShare != null ? `$${fund.navPerShare.toFixed(2)}` : '--'}
                </td>
                <td className="py-3 px-4 text-right tabular-nums">
                  {fund.distributionRate != null
                    ? `${fund.distributionRate.toFixed(1)}%`
                    : '--'}
                </td>
                <td className="py-3 px-4 text-right tabular-nums">
                  {fund.quarterlyReturn != null ? (
                    <span className={`inline-block px-1.5 py-0.5text-xs font-medium ${
                      fund.quarterlyReturn >= 0
                        ? 'bg-teal/10 text-teal'
                        : 'bg-red/10 text-red'
                    }`}>
                      {fund.quarterlyReturn >= 0 ? '+' : ''}
                      {fund.quarterlyReturn.toFixed(1)}%
                    </span>
                  ) : (
                    <span className="text-muted">--</span>
                  )}
                </td>
              </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <p className="text-xs text-muted mt-2">
        {filtered.length} of {funds.length} funds shown
      </p>
    </div>
  );
}
