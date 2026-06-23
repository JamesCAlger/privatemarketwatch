import type { FundExposure } from '@/lib/types';
import ProportionDonut from './ProportionDonut';

interface ExposureSectionProps {
  exposure: FundExposure;
}

/**
 * Fund-level composition, rendered in the same format as the homepage:
 * an Instrument-type donut (lien-resolved debt + equity/structured/cash/other)
 * and a GICS Industry-exposure donut, both via ProportionDonut.
 */
export default function ExposureSection({ exposure }: ExposureSectionProps) {
  const a = exposure.assetSplit;
  const lien = exposure.lienSplit;
  const debt = a.debt ?? 0;
  const fl = lien.firstLien ?? 0;
  const sl = lien.secondLien ?? 0;
  const un = lien.unsecured ?? 0;
  const otherDl = Math.max(0, 1 - fl - sl - un);

  // Instrument type — same categories as the homepage instrument donut, scaled
  // to share of total portfolio fair value.
  const instrumentRaw = [
    { label: 'First Lien Senior Loans', pct: debt * fl },
    { label: 'Second Lien Loans', pct: debt * sl },
    { label: 'Unsecured Loans', pct: debt * un },
    { label: 'Other Direct Lending', pct: debt * otherDl },
    { label: 'Structured Credit', pct: a.structured ?? 0 },
    { label: 'Equity', pct: a.equity ?? 0 },
    { label: 'Fund Vehicles', pct: a.fund ?? 0 },
    { label: 'Cash & Equivalents', pct: a.cash ?? 0 },
    { label: 'Other', pct: a.other ?? 0 },
  ];
  const instrumentItems = instrumentRaw
    .map((x) => ({ label: x.label, pct: x.pct * 100 }))
    .filter((x) => x.pct > 0.05);
  const firstLienPct = instrumentItems.find((x) => x.label === 'First Lien Senior Loans')?.pct ?? 0;
  const instrumentCenter = { label: 'First Lien', value: `${firstLienPct.toFixed(0)}%`, note: 'of fair value' };

  // Industry exposure — GICS sectors, share of holdings.
  const sectorItems = (exposure.gicsSectors ?? []).map((g) => ({ label: g.sector, pct: g.pct * 100 }));
  const top5 = [...sectorItems].sort((x, y) => y.pct - x.pct).slice(0, 5).reduce((s, x) => s + x.pct, 0);
  const sectorTotal = sectorItems.reduce((s, x) => s + x.pct, 0);
  const sectorCenter = {
    label: 'Top 5',
    value: `${sectorTotal > 0 ? Math.round((top5 / sectorTotal) * 100) : 0}%`,
    note: 'of holdings',
  };

  const hasInstrument = instrumentItems.length > 0;
  const hasSectors = sectorItems.length > 0;
  if (!hasInstrument && !hasSectors) return null;

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
      {hasInstrument && (
        <div className="bg-white border border-rule p-7">
          <h3 className="font-display text-[22px] tracking-[-0.01em] text-ink">Instrument type</h3>
          <p className="text-xs text-ink3 mt-2 mb-3">Share of portfolio fair value</p>
          <ProportionDonut items={instrumentItems} centerStat={instrumentCenter} />
        </div>
      )}
      {hasSectors && (
        <div className="bg-white border border-rule p-7">
          <h3 className="font-display text-[22px] tracking-[-0.01em] text-ink">Industry exposure</h3>
          <p className="text-xs text-ink3 mt-2 mb-3">Share of holdings fair value</p>
          <ProportionDonut items={sectorItems} centerStat={sectorCenter} />
          <div className="border-t border-rule2 pt-3 mt-4 text-[11px] text-ink3">
            Unknown sector positions lack GICS classification in the source filing or could not be reconciled.
          </div>
        </div>
      )}
    </div>
  );
}
