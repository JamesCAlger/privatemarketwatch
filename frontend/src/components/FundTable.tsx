'use client';

import { useState, useMemo } from 'react';
import { useRouter } from 'next/navigation';
import type { FundListItem } from '@/lib/types';
import { formatDollar, formatPercent, formatNumber } from '@/lib/format';
import VehicleTypeBadge from './VehicleTypeBadge';

type SortKey = 'name' | 'totalAssets' | 'navPerShare' | 'distributionRate' | 'liquidity' | 'quarterlyReturn';
type VehicleFilter = 'all' | 'bdc' | 'interval_fund' | 'tender_offer_fund';

interface FundTableProps {
  funds: FundListItem[];
}

const LIQUIDITY_LABEL: Record<string, string> = {
  bdc: 'Publicly Traded',
  interval_fund: 'Semi-Liquid',
  tender_offer_fund: 'Semi-Liquid',
};
const LIQUIDITY_ORDER: Record<string, number> = {
  'Publicly Traded': 0,
  'Semi-Liquid': 1,
};

export default function FundTable({ funds }: FundTableProps) {
  const router = useRouter();
  const [search, setSearch] = useState('');
  const [vehicleFilter, setVehicleFilter] = useState<VehicleFilter>('all');
  const [sortKey, setSortKey] = useState<SortKey>('totalAssets');
  const [sortAsc, setSortAsc] = useState(false);

  const filtered = useMemo(() => {
    let result = funds;

    if (vehicleFilter !== 'all') {
      result = result.filter((f) => f.vehicleType === vehicleFilter);
    }

    if (search.trim()) {
      const q = search.toLowerCase();
      result = result.filter(
        (f) =>
          f.name.toLowerCase().includes(q) ||
          (f.adviser ?? '').toLowerCase().includes(q) ||
          (f.ticker ?? '').toLowerCase().includes(q),
      );
    }

    result = [...result].sort((a, b) => {
      let av: number | string | null;
      let bv: number | string | null;
      if (sortKey === 'name') {
        av = a.name.toLowerCase();
        bv = b.name.toLowerCase();
      } else if (sortKey === 'liquidity') {
        av = LIQUIDITY_ORDER[LIQUIDITY_LABEL[a.vehicleType] ?? ''] ?? 99;
        bv = LIQUIDITY_ORDER[LIQUIDITY_LABEL[b.vehicleType] ?? ''] ?? 99;
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
  }, [funds, search, vehicleFilter, sortKey, sortAsc]);

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

  const FILTERS: { key: VehicleFilter; label: string }[] = [
    { key: 'all', label: 'All' },
    { key: 'bdc', label: 'BDCs' },
    { key: 'interval_fund', label: 'Interval' },
    { key: 'tender_offer_fund', label: 'Tender Offer' },
  ];

  return (
    <div>
      {/* Controls */}
      <div className="flex flex-col sm:flex-row gap-3 mb-4">
        <input
          type="text"
          placeholder="Search by name, adviser, or ticker..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="flex-1 px-4 py-2 text-sm border border-surface-muted bg-white focus:outline-none focus:ring-2 focus:ring-teal/30 focus:border-teal"
        />
        <div className="flex gap-1">
          {FILTERS.map((f) => (
            <button
              key={f.key}
              onClick={() => setVehicleFilter(f.key)}
              className={`text-xs px-3 py-2 transition-colors ${
                vehicleFilter === f.key
                  ? 'bg-navy text-white font-medium'
                  : 'text-muted hover:text-navy hover:bg-surface bg-white border border-surface-muted'
              }`}
            >
              {f.label}
            </button>
          ))}
        </div>
      </div>

      {/* Table */}
      <div className="bg-white shadow-card overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-navy">
              <SortHeader label="Fund" col="name" className="text-left" />
              <th className="py-3 px-4 text-left text-xs font-medium text-white/70 uppercase tracking-wider">Type</th>
              <SortHeader label="Liquidity" col="liquidity" className="text-left" />
              <SortHeader label="AUM" col="totalAssets" className="text-right" />
              <SortHeader label="NAV/Sh" col="navPerShare" className="text-right" />
              <SortHeader label="Dist Rate" col="distributionRate" className="text-right" />
              <SortHeader label="QoQ Return" col="quarterlyReturn" className="text-right" />
            </tr>
          </thead>
          <tbody>
            {filtered.length === 0 && (
              <tr>
                <td colSpan={7} className="py-8 text-center text-muted">
                  No funds match your search.
                </td>
              </tr>
            )}
            {filtered.map((fund, i) => (
              <tr
                key={fund.cik}
                onClick={() => router.push(`/funds/${fund.cik}`)}
                className={`border-b border-surface last:border-0 hover:bg-surface/50 transition-colors cursor-pointer ${
                  i % 2 === 1 ? 'bg-surface/30' : ''
                }`}
              >
                <td className="py-3 px-4">
                  <div className="font-medium text-navy truncate max-w-[280px]">{fund.name}</div>
                  {fund.ticker && (
                    <span className="text-xs text-muted">{fund.ticker}</span>
                  )}
                </td>
                <td className="py-3 px-4">
                  <VehicleTypeBadge vehicleType={fund.vehicleType} />
                </td>
                <td className="py-3 px-4 text-sm text-muted">
                  {LIQUIDITY_LABEL[fund.vehicleType] ?? '--'}
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
            ))}
          </tbody>
        </table>
      </div>

      <p className="text-xs text-muted mt-2">
        {filtered.length} of {funds.length} funds shown
      </p>
    </div>
  );
}
