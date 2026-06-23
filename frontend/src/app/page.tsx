import {
  getFundList,
  getFundSummary,
  getMetadata,
  getPortfolioCharacteristics,
  getManagerConcentration,
  getGicsSectorBreakdown,
  getCreditRisk,
  getPikEligibility,
  getTopConstituents,
  getConcentrationCurve,
  getSpreadTimeSeries,
  getSpreadByFundSize,
} from '@/lib/data';
import { formatDollar, formatNumber, formatQuarter, formatPercent, formatYears } from '@/lib/format';
import { combineConcentration } from '@/lib/data';
import Link from 'next/link';
import FundTable from '@/components/FundTable';
import ProportionDonut from '@/components/ProportionDonut';
import CreditStressChart from '@/components/CreditStressChart';
import PikEligibilityChart from '@/components/PikEligibilityChart';
import SpreadTimeChart from '@/components/SpreadTimeChart';
import SpreadByFundSizeChart from '@/components/SpreadByFundSizeChart';
import { formatDisplayName } from '@/lib/nameFormat';
import StatStrip from '@/components/StatStrip';

export default function HomePage() {
  const funds = getFundList();
  const summary = getFundSummary();
  const metadata = getMetadata();
  const gicsSectorBreakdown = getGicsSectorBreakdown();
  const portfolioCharacteristics = getPortfolioCharacteristics();
  const managerConcentration = getManagerConcentration();
  const creditRisk = getCreditRisk();
  const pikEligibility = getPikEligibility();
  const spreadTimeSeries = getSpreadTimeSeries();
  const spreadByFundSize = getSpreadByFundSize();
  const topConstituents = getTopConstituents();
  const concentrationCurve = getConcentrationCurve();

  // Aggregate BDC portfolio fair value (current quarter, all classifications)
  const portfolioFv = portfolioCharacteristics?.portfolioFv ?? portfolioCharacteristics?.totalFv ?? 0;

  // Combine manager concentration across the direct-lending and equity books
  const combinedManagers = combineConcentration(
    managerConcentration,
    ['DIRECT_LENDING', 'COMMON_EQUITY'],
  );

  // Donut items for Industry Exposure + Manager Concentration
  const sectorItems = gicsSectorBreakdown.map((s) => ({
    label: s.sector,
    pct: s.pctOfTotal * 100,
  }));
  function top5Share(items: { pct: number }[]): number {
    const total = items.reduce((s, x) => s + x.pct, 0);
    const top5Sum = [...items].sort((a, b) => b.pct - a.pct).slice(0, 5).reduce((s, x) => s + x.pct, 0);
    return total > 0 ? (top5Sum / total) * 100 : 0;
  }
  const sectorCenterStat = { label: 'Top 5', value: top5Share(sectorItems).toFixed(0) + '%', note: 'of holdings' };

  // Position concentration — ordered quantile brackets of fair value, rendered as bars
  const combinedCurve = concentrationCurve['COMBINED']?.position ?? [];
  const top5ConcPct = ((combinedCurve[0]?.fvPct ?? 0) + (combinedCurve[1]?.fvPct ?? 0)) * 100;
  const posConcMax = combinedCurve.reduce((m, b) => Math.max(m, b.fvPct * 100), 0);

  // Manager concentration — top managers by share, capped to the same number of
  // bars as position concentration so the two charts line up side by side.
  // The remaining managers (plus any source "Other") roll up into a final "Other" bar.
  const namedManagers = combinedManagers.filter((m) => m.name !== 'Other');
  const sourceOther = combinedManagers.find((m) => m.name === 'Other');
  const managerBarCount = combinedCurve.length || 6;
  const topNamed = namedManagers.slice(0, managerBarCount - 1);
  const otherPct =
    namedManagers.slice(managerBarCount - 1).reduce((s, m) => s + m.pctOfIndex, 0) +
    (sourceOther?.pctOfIndex ?? 0);
  const managerItems = [
    ...topNamed.map((m) => ({
      label: formatDisplayName(m.name, { kind: 'manager' }),
      pct: m.pctOfIndex * 100,
    })),
    ...(otherPct > 0 ? [{ label: 'Other', pct: otherPct * 100 }] : []),
  ];
  const managerTop5Pct = namedManagers.slice(0, 5).reduce((s, m) => s + m.pctOfIndex, 0) * 100;
  const managerMax = managerItems.reduce((m, x) => Math.max(m, x.pct), 0);

  // Instrument type donut — split direct lending by lien, then other classifications.
  // Sourced from the holdings-based classificationFv so the slices reconcile to the
  // headline portfolio fair value (same current-quarter, all-classification basis).
  const cfv = portfolioCharacteristics?.classificationFv ?? {};
  const dlFv = cfv['DIRECT_LENDING'] ?? 0;
  const lien = portfolioCharacteristics?.lienSplit;
  // DL lien tiers — First Lien is the remainder so the five DL slices sum to exactly dlFv.
  const secondFv = lien ? dlFv * lien.secondLien : 0;
  const subFv = lien ? dlFv * (lien.subordinated ?? 0) : 0;
  const unsecFv = lien ? dlFv * lien.unsecured : 0;
  const otherDlFv = lien ? dlFv * (lien.unknown ?? 0) : 0;
  const firstLienFv = lien ? Math.max(0, dlFv - secondFv - subFv - unsecFv - otherDlFv) : dlFv;
  const structuredFv = cfv['STRUCTURED_CREDIT'] ?? 0;
  const preferredFv = cfv['PREFERRED_EQUITY'] ?? 0;
  const commonFv = cfv['COMMON_EQUITY'] ?? 0;
  const cashFv = cfv['CASH'] ?? 0;
  // Everything else (funds, real estate, unclassified) as the remainder, so the
  // whole donut sums to EXACTLY portfolioFv — the same figure as the headline.
  const otherFv = Math.max(0, portfolioFv - dlFv - structuredFv - preferredFv - commonFv - cashFv);
  const instrumentRaw: { label: string; fv: number }[] = [
    { label: 'First Lien', fv: firstLienFv },
    { label: 'Second Lien', fv: secondFv },
    { label: 'Subordinated', fv: subFv },
    { label: 'Unsecured', fv: unsecFv },
    { label: 'Other Lending', fv: otherDlFv },
    { label: 'Structured', fv: structuredFv },
    { label: 'Preferred', fv: preferredFv },
    { label: 'Common Equity', fv: commonFv },
    // Cash & equivalents — analytics-only classification, included for a holistic view.
    { label: 'Cash', fv: cashFv },
    { label: 'Other', fv: otherFv },
  ].filter((x) => x.fv > 0);
  const instrumentTotal = instrumentRaw.reduce((s, x) => s + x.fv, 0);
  const instrumentDonutItems = instrumentRaw.map((x) => ({
    label: x.label,
    pct: instrumentTotal > 0 ? (x.fv / instrumentTotal) * 100 : 0,
  }));
  const firstLienPct = instrumentDonutItems.find((x) => x.label === 'First Lien')?.pct ?? 0;
  const instrumentCenterStat = { label: 'First Lien', value: firstLienPct.toFixed(0) + '%', note: 'of fair value' };

  // Portfolio characteristics stats
  const pc = portfolioCharacteristics;
  const hasPC = pc && pc.positionCount > 0;

  // Movers data
  const topLeverage = buildTopLeverage(funds);
  const largestNavMoves = buildLargestNavMoves(funds);
  const topYield = buildTopYield(funds);

  return (
    <div>
      {/* ================================================================ */}
      {/* HERO                                                             */}
      {/* ================================================================ */}
      <div className="border-b border-rule pt-6 pb-8">
        <div className="max-w-[1180px] mx-auto px-4 md:px-6">
          <h1 className="font-display text-[56px] md:text-[80px] leading-[1.08] tracking-[-0.028em] text-ink mb-2 font-medium max-w-[920px]">
            BDC holdings.
          </h1>
          <h1 className="font-display text-[56px] md:text-[80px] leading-[1.08] tracking-[-0.028em] text-ink3 mb-6 font-medium">
            Loan by loan.
          </h1>
          <p className="text-[19px] md:text-[21px] leading-snug text-ink3 max-w-[1000px] mb-6">
            Private markets are no longer walled off from ordinary investors, yet
            these funds are still far easier to buy than to inspect. Metris Lens
            brings position-level transparency out from behind the paywall.
          </p>
          <div className="flex flex-wrap gap-3 mb-8">
            <Link
              href="#universe"
              className="inline-block px-[22px] py-3 bg-navy text-white text-[13px] font-medium tracking-[0.06em] no-underline hover:bg-navy/90 transition-colors"
            >
              Browse the fund universe &rarr;
            </Link>
            <Link
              href="/methodology"
              className="inline-block px-[22px] py-3 border border-rule text-ink2 text-[13px] font-medium tracking-[0.06em] no-underline hover:bg-surface/50 transition-colors"
            >
              View methodology &#x2197;
            </Link>
          </div>
        </div>
      </div>

      {/* ================================================================ */}
      {/* ORIENTATION -- mission statement + stat strip                    */}
      {/* ================================================================ */}
      <div className="border-b border-rule">
        <div className="max-w-[1180px] mx-auto px-4 md:px-6 py-10">
          {/* Stat strip */}
          <StatStrip
            totalFv={portfolioFv}
            holdingsCount={metadata.holdingsCount}
            totalFunds={summary.totalFunds}
            avgSpread={portfolioCharacteristics?.was ?? null}
            quarters={spreadTimeSeries.length}
          />
        </div>
      </div>

      {/* ================================================================ */}
      {/* MAIN CONTENT                                                     */}
      {/* ================================================================ */}
      <div className="max-w-[1180px] mx-auto px-4 md:px-6 py-7 space-y-14">

        {/* Section subtitle introducing the portfolio charts */}
        <div className="max-w-[760px]">
          <div className="eyebrow text-accent mb-3">Inside the portfolio</div>
          <h2 className="font-display text-[26px] md:text-[30px] tracking-[-0.01em] text-ink leading-tight">
            What these funds actually hold
          </h2>
          <p className="text-[15px] leading-relaxed text-ink2 mt-3">
            Aggregated across the covered universe: instrument and industry mix,
            concentration, spreads, and credit stress at the position level.
          </p>
        </div>

        {/* Industry Exposure + Manager Concentration (two-column donuts) */}
        {/* Instrument Type + Industry Exposure (top row) */}
        {(instrumentDonutItems.length > 0 || sectorItems.length > 0) && (
          <section>
            <div className="grid grid-cols-1 md:[@media(min-height:760px)]:grid-cols-2 gap-6">
              {instrumentDonutItems.length > 0 && (
                <div className="bg-white border border-rule p-7">
                  <h3 className="font-display text-[22px] tracking-[-0.01em] text-ink">Instrument type</h3>
                  <p className="text-xs text-ink3 mt-2 mb-3">Share of portfolio fair value (incl. cash)</p>
                  <ProportionDonut items={instrumentDonutItems} centerStat={instrumentCenterStat} />
                  <div className="border-t border-rule2 pt-3 mt-4 text-[11px] text-ink3">
                    Other Direct Lending is direct lending whose lien seniority was not disclosed in the source filing, so it cannot be placed in a first lien, second lien, subordinated, or unsecured bucket. Other includes real estate holdings, indirect exposure via credit and equity fund vehicles, and opaque SPVs such as co-investment JVs and feeder funds.
                  </div>
                </div>
              )}
              {sectorItems.length > 0 && (
                <div className="bg-white border border-rule p-7">
                  <h3 className="font-display text-[22px] tracking-[-0.01em] text-ink">Industry exposure</h3>
                  <p className="text-xs text-ink3 mt-2 mb-3">Share of holdings fair value</p>
                  <ProportionDonut items={sectorItems} centerStat={sectorCenterStat} />
                  <div className="border-t border-rule2 pt-3 mt-4 text-[11px] text-ink3">
                    Unknown sector positions lack GICS classification in the source filing or could not be reconciled.
                  </div>
                </div>
              )}
            </div>
          </section>
        )}

        {/* Position concentration (ordered bars) + Manager concentration (donut) */}
        {(combinedCurve.length > 0 || managerItems.length > 0) && (
          <section>
            <div className="grid grid-cols-1 md:[@media(min-height:760px)]:grid-cols-2 gap-6">
              {combinedCurve.length > 0 && (
                <div className="bg-white border border-rule p-7">
                  <h3 className="font-display text-[22px] tracking-[-0.01em] text-ink">Position concentration</h3>
                  <p className="text-xs text-ink3 mt-2 mb-3">Share of fair value, by position quantile</p>
                  <div className="space-y-2">
                    {combinedCurve.map((b, i) => {
                      const pct = b.fvPct * 100;
                      const barW = posConcMax > 0 ? (pct / posConcMax) * 100 : 0;
                      return (
                        <div key={i}>
                          <div className="flex justify-between items-baseline text-xs mb-1">
                            <span className="text-ink2 truncate pr-2">{b.label}</span>
                            <span className="font-mono tabular-nums text-ink font-medium shrink-0">
                              {pct.toFixed(1)}%
                              <span className="text-ink3 font-normal ml-1.5">({b.count.toLocaleString()})</span>
                            </span>
                          </div>
                          <div className="h-5 bg-rule2 relative">
                            <div
                              className="absolute left-0 top-0 bottom-0 bg-navy"
                              style={{ width: `${barW}%` }}
                            />
                          </div>
                        </div>
                      );
                    })}
                  </div>
                  <div className="border-t border-rule2 pt-3 mt-4 text-[11px] text-ink3">
                    Top 5% of positions hold{' '}
                    <span className="font-mono text-ink tabular-nums font-medium">{top5ConcPct.toFixed(1)}%</span>{' '}
                    of portfolio fair value.
                  </div>
                </div>
              )}
              {managerItems.length > 0 && (
                <div className="bg-white border border-rule p-7">
                  <h3 className="font-display text-[22px] tracking-[-0.01em] text-ink">Manager concentration</h3>
                  <p className="text-xs text-ink3 mt-2 mb-3">Share of portfolio fair value</p>
                  <div className="space-y-2">
                    {managerItems.map((m, i) => {
                      const barW = managerMax > 0 ? (m.pct / managerMax) * 100 : 0;
                      return (
                        <div key={i}>
                          <div className="flex justify-between items-baseline text-xs mb-1">
                            <span className="text-ink2 truncate pr-2">{m.label}</span>
                            <span className="font-mono tabular-nums text-ink font-medium shrink-0">
                              {m.pct.toFixed(1)}%
                            </span>
                          </div>
                          <div className="h-5 bg-rule2 relative">
                            <div
                              className="absolute left-0 top-0 bottom-0 bg-navy"
                              style={{ width: `${barW}%` }}
                            />
                          </div>
                        </div>
                      );
                    })}
                  </div>
                  <div className="border-t border-rule2 pt-3 mt-4 text-[11px] text-ink3">
                    Top 5 managers hold{' '}
                    <span className="font-mono text-ink tabular-nums font-medium">{managerTop5Pct.toFixed(1)}%</span>{' '}
                    of portfolio fair value.
                  </div>
                </div>
              )}
            </div>
          </section>
        )}

        {/* Spread Analysis */}
        {spreadTimeSeries.length > 1 && (() => {
          const latest = spreadTimeSeries[spreadTimeSeries.length - 1];
          const latestBps = Math.round(latest.was * 100);
          const peak = Math.max(...spreadTimeSeries.map((d) => d.was));
          const peakBps = Math.round(peak * 100);
          return (
            <section>
              <div className="grid grid-cols-1 md:[@media(min-height:760px)]:grid-cols-2 gap-6">
                {/* Spread over time */}
                <div className="bg-white border border-rule p-7">
                  <div className="flex flex-wrap items-baseline justify-between gap-4 mb-1">
                    <h3 className="font-display text-[22px] tracking-[-0.01em] text-ink">Spread analysis</h3>
                    <div className="text-right">
                      <span className="font-mono text-[18px] text-ink font-semibold tabular-nums">
                        {latestBps} bps
                      </span>
                      <span className="text-[11px] text-ink3 ml-1.5 font-mono tabular-nums">
                        from {peakBps} peak
                      </span>
                    </div>
                  </div>
                  <p className="text-xs text-ink3 mb-3">
                    FV-weighted average credit spread over base rate &middot; {spreadTimeSeries.length}-quarter history
                  </p>
                  <SpreadTimeChart data={spreadTimeSeries} />
                  <div className="border-t border-rule2 pt-3 mt-4 text-[11px] text-ink3">
                    Direct lending positions &middot; {latest.positionCount.toLocaleString()} positions &middot; {formatDollar(latest.totalFv)} FV
                  </div>
                </div>

                {/* Spread by fund size */}
                {spreadByFundSize.length > 0 && (
                  <div className="bg-white border border-rule p-7">
                    <h3 className="font-display text-[22px] tracking-[-0.01em] text-ink">Spread by fund size</h3>
                    <p className="text-xs text-ink3 mt-2 mb-3">
                      Fund total assets tercile &middot; latest quarter
                    </p>
                    <SpreadByFundSizeChart data={spreadByFundSize} />
                    <div className="border-t border-rule2 pt-3 mt-4 text-[11px] text-ink3">
                      {spreadByFundSize.reduce((s, d) => s + d.fundCount, 0)} funds with spread data.
                      Small-fund premium: {Math.round((spreadByFundSize[0]?.was ?? 0) * 100) - Math.round((spreadByFundSize[spreadByFundSize.length - 1]?.was ?? 0) * 100)} bps over large.
                    </div>
                  </div>
                )}
              </div>
            </section>
          );
        })()}

        {/* Credit Stress */}
        {creditRisk.length > 1 && (() => {
          const latest = creditRisk[creditRisk.length - 1];
          const latestTotal = latest.byFv.deepDistress + latest.byFv.nonAccrual + latest.byFv.markedBelowCost;
          const yearAgoIdx = creditRisk.length - 5;
          const yearAgo = yearAgoIdx >= 0 ? creditRisk[yearAgoIdx] : null;
          const yearAgoTotal = yearAgo
            ? yearAgo.byFv.deepDistress + yearAgo.byFv.nonAccrual + yearAgo.byFv.markedBelowCost
            : null;
          const delta = yearAgoTotal != null ? latestTotal - yearAgoTotal : null;
          return (
            <section>
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                <div className="bg-white border border-rule p-7">
                <div className="flex flex-wrap items-baseline justify-between gap-4 mb-1">
                  <h3 className="font-display text-[22px] tracking-[-0.01em] text-ink">Credit stress, by quarter</h3>
                  <div className="text-right">
                    <span className="font-mono text-[26px] text-ink font-semibold tabular-nums leading-none">
                      {(latestTotal * 100).toFixed(1)}%
                    </span>
                    <div className="text-[10px] text-ink3 uppercase tracking-[0.1em] mt-1">
                      of fair value flagged &middot; {formatQuarter(latest.quarter)}
                    </div>
                    {delta != null && (
                      <div className="text-[11px] text-ink2 font-mono tabular-nums mt-1">
                        {delta > 0 ? '+' : ''}{(delta * 100).toFixed(1)} pp YoY
                      </div>
                    )}
                  </div>
                </div>
                <p className="text-xs text-ink3 mb-3">
                  Cumulative % of fair value showing each signal
                </p>
                <CreditStressChart data={creditRisk} />
                <div className="flex flex-wrap justify-between items-baseline mt-4 pt-3 border-t border-rule2 text-[11px] text-ink3">
                  <span>
                    Portfolio FV{' '}
                    <span className="font-mono text-ink2 tabular-nums">{formatDollar(latest.totalFv)}</span>
                    {' '}across {formatNumber(latest.totalPositions)} positions.
                  </span>
                  <span>Source: SEC 10-K / 10-Q filings</span>
                </div>
                </div>

                {/* PIK-eligible loans, by quarter */}
                {pikEligibility.length > 1 && (() => {
                  const pikLatest = pikEligibility[pikEligibility.length - 1];
                  const pikYearAgoIdx = pikEligibility.length - 5;
                  const pikYearAgo = pikYearAgoIdx >= 0 ? pikEligibility[pikYearAgoIdx] : null;
                  const pikDelta = pikYearAgo ? pikLatest.byCount - pikYearAgo.byCount : null;
                  return (
                    <div className="bg-white border border-rule p-7">
                      <div className="flex flex-wrap items-baseline justify-between gap-4 mb-1">
                        <h3 className="font-display text-[22px] tracking-[-0.01em] text-ink">Loans with PIK terms, by quarter</h3>
                        <div className="text-right">
                          <span className="font-mono text-[26px] text-ink font-semibold tabular-nums leading-none">
                            {(pikLatest.byCount * 100).toFixed(1)}%
                          </span>
                          <div className="text-[10px] text-ink3 uppercase tracking-[0.1em] mt-1">
                            of loans &middot; {formatQuarter(pikLatest.quarter)}
                          </div>
                          {pikDelta != null && (
                            <div className="text-[11px] text-ink2 font-mono tabular-nums mt-1">
                              {pikDelta > 0 ? '+' : ''}{(pikDelta * 100).toFixed(1)} pp YoY
                            </div>
                          )}
                        </div>
                      </div>
                      <p className="text-xs text-ink3 mb-3">
                        Share of direct-lending loans with PIK features
                      </p>
                      <PikEligibilityChart data={pikEligibility} />
                      <div className="flex flex-wrap justify-between items-baseline mt-4 pt-3 border-t border-rule2 text-[11px] text-ink3">
                        <span>PIK flag set or PIK rate disclosed &middot; proxy for PIK terms, not current PIK income.</span>
                        <span className="font-mono text-ink2 tabular-nums">
                          {pikLatest.pikCount.toLocaleString()} / {pikLatest.totalPositions.toLocaleString()} loans
                        </span>
                      </div>
                    </div>
                  );
                })()}
              </div>
            </section>
          );
        })()}

        {/* Top Positions */}
        {(() => {
          // Flatten top constituents across DIRECT_LENDING only (largest category)
          const dlPositions = topConstituents['DIRECT_LENDING'] ?? [];
          const topPositions = dlPositions.slice(0, 10);

          if (topPositions.length === 0) return null;
          return (
            <section>
              <div>
                {/* Top Positions Table */}
                {topPositions.length > 0 && (
                  <div className="bg-white border border-rule p-7">
                    <h3 className="font-display text-[22px] tracking-[-0.01em] text-ink">Largest positions</h3>
                    <p className="text-xs text-ink3 mt-2 mb-4">Top {topPositions.length} direct lending positions by fair value</p>
                    <div className="overflow-x-auto">
                      <table className="w-full text-xs">
                        <thead>
                          <tr className="border-b border-rule text-[10px] uppercase tracking-[0.12em] text-ink3">
                            <th className="text-left py-2 pr-3 font-medium">Issuer</th>
                            <th className="text-left py-2 pr-3 font-medium">Fund</th>
                            <th className="text-right py-2 pr-3 font-medium">Fair Value</th>
                            <th className="text-right py-2 pr-3 font-medium">Unreal. G/L</th>
                            <th className="text-right py-2 font-medium">Rate</th>
                          </tr>
                        </thead>
                        <tbody>
                          {topPositions.map((p, i) => {
                            // Strip a trailing ",N" position index and any trailing comma.
                            const cleanName = p.issuerName.replace(/,\s*\d+$/, '').replace(/,\s*$/, '').trim();
                            return (
                              <tr key={i} className="border-b border-rule2 hover:bg-surface/30">
                                <td className="py-2 pr-3 text-ink font-medium" title={cleanName}>
                                  {cleanName}
                                </td>
                                <td className="py-2 pr-3 text-ink3" title={p.vehicleName}>
                                  {p.vehicleName}
                                </td>
                                <td className="py-2 pr-3 text-right font-mono tabular-nums text-ink">
                                  {formatDollar(p.fairValue ?? 0)}
                                </td>
                                <td className={`py-2 pr-3 text-right font-mono tabular-nums ${
                                  p.unrealizedGlPct != null
                                    ? p.unrealizedGlPct >= 0 ? 'text-green' : 'text-red'
                                    : 'text-ink3'
                                }`}>
                                  {p.unrealizedGlPct != null
                                    ? `${p.unrealizedGlPct >= 0 ? '+' : ''}${p.unrealizedGlPct.toFixed(1)}%`
                                    : '--'}
                                </td>
                                <td className="py-2 text-right text-ink3">
                                  {p.rateType ?? '--'}
                                </td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    </div>
                  </div>
                )}
              </div>
            </section>
          );
        })()}
      </div>

      {/* ================================================================ */}
      {/* PORTFOLIO CHARACTERISTICS -- dark band                            */}
      {/* ================================================================ */}
      {hasPC && (
        <div className="bg-navy mt-14">
          <div className="max-w-[1180px] mx-auto px-4 md:px-6 py-10">
            <div className="grid grid-cols-1 md:grid-cols-[auto_1fr] gap-8 items-start">
              <div className="md:pr-6">
                <div className="eyebrow text-accent mb-2">Private Credit</div>
                <h2 className="font-display text-[26px] text-white tracking-[-0.01em] leading-tight">
                  Portfolio<br />Characteristics
                </h2>
                <p className="text-white/40 text-xs mt-2">
                  As of {pc.asOf ? formatQuarter(dateToQuarter(pc.asOf)) : '--'}
                </p>
              </div>
              <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-5 gap-0">
                {[
                  { label: 'Wtd. Avg. Coupon', value: pc.wac != null ? `${pc.wac.toFixed(1)}%` : '--', sub: pc.wacCoverage != null ? `${(pc.wacCoverage * 100).toFixed(0)}% coverage` : undefined },
                  { label: 'Wtd. Avg. Spread', value: pc.was != null ? `${(pc.was * 100).toFixed(0)} bps` : '--', sub: pc.wasCoverage != null ? `${(pc.wasCoverage * 100).toFixed(0)}% coverage` : undefined },
                  { label: 'Wtd. Avg. Maturity', value: pc.wam != null ? formatYears(pc.wam) : '--', sub: pc.wamCoverage != null ? `${(pc.wamCoverage * 100).toFixed(0)}% coverage` : undefined },
                  { label: 'First Lien', value: formatPercent(pc.lienSplit.firstLien), sub: 'of direct lending' },
                  { label: 'Floating Rate', value: formatPercent(pc.rateTypeSplit.floating), sub: 'of debt' },
                ].map((stat, i) => (
                  <div
                    key={stat.label}
                    className={`py-4 px-5 ${i > 0 ? 'md:border-l md:border-white/[0.08]' : ''}`}
                  >
                    <div className="text-[10px] uppercase tracking-[0.14em] text-white/40 mb-2">
                      {stat.label}
                    </div>
                    <div className="font-mono text-[36px] text-accent tabular-nums leading-none">
                      {stat.value}
                    </div>
                    {stat.sub && (
                      <div className="text-[10px] text-white/30 mt-1.5">{stat.sub}</div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ================================================================ */}
      {/* MOVERS                                                           */}
      {/* ================================================================ */}
      <div className="max-w-[1180px] mx-auto px-4 md:px-6 py-10 space-y-14">
        {(topLeverage.length > 0 || largestNavMoves.length > 0 || topYield.length > 0) && (
          <section>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
              {/* Top Leverage */}
              {topLeverage.length > 0 && (
                <MoversCard
                  title="Top Leverage"
                  dotColor="bg-red"
                  items={topLeverage}
                  maxVal={topLeverage[0]?.value ?? 1}
                  barColor="bg-red/60"
                  valueFmt={(v) => `${v.toFixed(2)}x`}
                />
              )}

              {/* Largest NAV Moves */}
              {largestNavMoves.length > 0 && (
                <MoversCard
                  title="Largest NAV Moves"
                  dotColor="bg-navy"
                  items={largestNavMoves}
                  maxVal={Math.max(...largestNavMoves.map((m) => Math.abs(m.value)))}
                  barColor="bg-navy/40"
                  valueFmt={(v) => `${v >= 0 ? '+' : ''}${v.toFixed(1)}%`}
                />
              )}

              {/* Yield Leaderboard */}
              {topYield.length > 0 && (
                <MoversCard
                  title="Yield Leaderboard"
                  dotColor="bg-accent"
                  items={topYield}
                  maxVal={topYield[0]?.value ?? 1}
                  barColor="bg-accent"
                  valueFmt={(v) => `${v.toFixed(1)}%`}
                />
              )}
            </div>
          </section>
        )}

        {/* 8. Fund Universe */}
        <section id="universe">
          <div className="bg-white border border-rule">
            <div className="p-7 pb-0">
              <h2 className="font-display text-[26px] tracking-[-0.01em] text-ink">
                Fund universe{' '}
                <span className="text-ink3 font-normal">
                  &middot; {formatNumber(summary.totalFunds)} funds &middot; {formatDollar(summary.totalAum)}
                </span>
              </h2>
            </div>
            <div className="p-7 pt-4">
              <FundTable funds={funds} />
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Movers card                                                         */
/* ------------------------------------------------------------------ */

interface MoverItem {
  name: string;
  cik: string;
  value: number;
}

function MoversCard({
  title,
  dotColor,
  items,
  maxVal,
  barColor,
  valueFmt,
}: {
  title: string;
  dotColor: string;
  items: MoverItem[];
  maxVal: number;
  barColor: string;
  valueFmt: (v: number) => string;
}) {
  return (
    <div className="bg-white border border-rule p-6">
      <div className="flex items-center gap-2 mb-4">
        <span className={`w-2 h-2 rounded-full ${dotColor}`} />
        <span className="eyebrow text-ink2">{title}</span>
      </div>
      <div className="space-y-2.5">
        {items.map((item) => {
          const barW = maxVal > 0 ? (Math.abs(item.value) / maxVal) * 100 : 0;
          return (
            <div key={item.cik}>
              <div className="flex justify-between text-xs mb-1">
                <span className="text-ink2 truncate pr-2 flex-1 min-w-0" title={item.name}>{item.name}</span>
                <span className="font-mono tabular-nums text-ink font-semibold shrink-0">
                  {valueFmt(item.value)}
                </span>
              </div>
              <div className="h-2 bg-rule2 relative">
                <div
                  className={`absolute left-0 top-0 bottom-0 ${barColor}`}
                  style={{ width: `${barW}%` }}
                />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Data builders                                                       */
/* ------------------------------------------------------------------ */

function shortName(f: import('@/lib/types').FundListItem): string {
  // Strip the trailing "(CIK NNN)" and inline ticker "(ABC)"; let CSS truncate
  // to the actual cell width rather than a fixed character count.
  return f.name
    .replace(/\s*\(CIK\s+\d+\)\s*$/, '')
    .replace(/\s*\([A-Z]{1,5}(?:,\s*[A-Z]{1,5})*\)\s*/, ' ')
    .trim();
}

function buildTopLeverage(funds: import('@/lib/types').FundListItem[]): MoverItem[] {
  return [...funds]
    .filter((f) => f.leverageRatio != null && f.leverageRatio > 0)
    .sort((a, b) => (b.leverageRatio ?? 0) - (a.leverageRatio ?? 0))
    .slice(0, 8)
    .map((f) => ({ name: shortName(f), cik: f.cik, value: f.leverageRatio! }));
}

function buildLargestNavMoves(funds: import('@/lib/types').FundListItem[]): MoverItem[] {
  return [...funds]
    .filter((f) => f.quarterlyReturn != null)
    .sort((a, b) => Math.abs(b.quarterlyReturn ?? 0) - Math.abs(a.quarterlyReturn ?? 0))
    .slice(0, 8)
    .map((f) => ({ name: shortName(f), cik: f.cik, value: f.quarterlyReturn! }));
}

function buildTopYield(funds: import('@/lib/types').FundListItem[]): MoverItem[] {
  return [...funds]
    .filter((f) => f.distributionRate != null && f.distributionRate > 0)
    .sort((a, b) => (b.distributionRate ?? 0) - (a.distributionRate ?? 0))
    .slice(0, 8)
    .map((f) => ({ name: shortName(f), cik: f.cik, value: f.distributionRate! }));
}

/** Convert "2025-12-31" to "2025q4" */
function dateToQuarter(dateStr: string): string {
  const parts = dateStr.split('-');
  if (parts.length < 2) return dateStr;
  const year = parts[0];
  const month = parseInt(parts[1], 10);
  const q = Math.ceil(month / 3);
  return `${year}q${q}`;
}
