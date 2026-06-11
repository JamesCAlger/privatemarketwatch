'use client';

import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Cell,
  AreaChart,
  Area,
  ComposedChart,
  Line,
} from 'recharts';
import type { DataQuality, ReconciliationHistogram, LlmFundValidation } from '@/lib/types';
import { formatDollar, formatNumber, formatQuarter } from '@/lib/format';

const TEAL = '#2A9D8F';
const NAVY = '#0F1B2D';
const ORANGE = '#E76F51';
const MUTED = '#94A3B8';

/* ---------- matplotlib-inspired palette ---------- */
const MPL_BLUE = '#4C72B0';
const MPL_EDGE = '#2b4570';
const MPL_LINE = '#1a1a1a';
const MPL_GRID = '#cccccc';
const MPL_TICK = '#555555';

/* ---------- Shared widgets ---------- */

function StatCard({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="bg-white p-5 shadow-card">
      <p className="text-xs text-muted uppercase tracking-wider mb-1.5">{label}</p>
      <p className="text-2xl font-bold text-navy tabular-nums">{value}</p>
      {sub && <p className="text-xs text-muted mt-1">{sub}</p>}
    </div>
  );
}

function SectionHeading({ children }: { children: React.ReactNode }) {
  return (
    <h2 className="text-lg font-semibold text-navy mb-5 flex items-center gap-3">
      <span className="w-1 h-5 bg-teal" />
      {children}
    </h2>
  );
}

/* ---------- Matplotlib-style histogram ---------- */

function AngledTick(props: { x?: number; y?: number; payload?: { value: string } }) {
  const { x = 0, y = 0, payload } = props;
  return (
    <g transform={`translate(${x},${y})`}>
      <text x={0} y={0} dy={10} textAnchor="end" fill={MPL_TICK} fontSize={7} transform="rotate(-45)">
        {payload?.value}
      </text>
    </g>
  );
}

function MplHistogram({ data }: { data: ReconciliationHistogram }) {
  return (
    <div
      className="bg-white border border-[#cccccc] p-2.5"
      style={{ fontFamily: "'DejaVu Sans', 'Liberation Sans', Arial, sans-serif" }}
    >
      {/* Header */}
      <div className="mb-1.5">
        <div className="text-[11px] font-bold text-[#333] leading-tight">{data.title}</div>
        <div className="text-[9px] text-[#777] leading-snug mt-0.5">{data.subtitle}</div>
        <div className="text-[9px] text-[#999] mt-0.5" style={{ fontFamily: 'monospace' }}>
          n={formatNumber(data.n)}&nbsp;&nbsp;median={data.median?.toFixed(3) ?? 'N/A'}
        </div>
      </div>

      {/* Chart */}
      <ResponsiveContainer width="100%" height={180}>
        <ComposedChart
          data={data.histogram}
          barCategoryGap={0}
          margin={{ top: 8, right: 8, bottom: 40, left: 28 }}
        >
          <CartesianGrid stroke={MPL_GRID} strokeWidth={0.5} vertical={false} />
          <XAxis
            dataKey="bucket"
            tick={<AngledTick />}
            axisLine={{ stroke: '#333', strokeWidth: 0.8 }}
            tickLine={{ stroke: '#333' }}
            height={45}
          />
          <YAxis
            tick={{ fontSize: 8, fill: MPL_TICK }}
            axisLine={{ stroke: '#333', strokeWidth: 0.8 }}
            tickLine={{ stroke: '#333' }}
            width={28}
            allowDecimals={false}
          />
          <Tooltip
            contentStyle={{
              fontSize: 10,
              fontFamily: 'monospace',
              background: '#ffffee',
              border: '1px solid #999',
              borderRadius: 0,
              padding: '3px 6px',
              boxShadow: 'none',
            }}
            formatter={(v: number) => [v, 'count']}
          />
          <Bar
            dataKey="count"
            fill={MPL_BLUE}
            stroke={MPL_EDGE}
            strokeWidth={0.5}
            isAnimationActive={false}
          />
          <Line
            type="monotone"
            dataKey="count"
            stroke={MPL_LINE}
            strokeWidth={1.2}
            dot={false}
            isAnimationActive={false}
          />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

/* ---------- Main dashboard ---------- */

export default function DataQualityDashboard({ data }: { data: DataQuality }) {
  const ps = data.pipelineSummary;
  const gav = data.gavReconciliation;
  const llmVal = data.llmFundValidation;

  const quarterlyData = (data.holdingsByQuarter ?? []).map((q) => ({
    quarter: q.quarter,
    label: formatQuarter(q.quarter),
    bdc: q.bdc,
    nport: q.nport,
    totalFv: q.totalFv,
    cikCount: q.cikCount,
  }));

  return (
    <div className="px-4 md:px-[120px] py-10">
      {/* ---- Summary stat cards ---- */}
      {ps && (
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4 mb-10 -mt-2">
          <StatCard
            label="Total Holdings"
            value={formatNumber(ps.totalHoldings)}
            sub={`${formatNumber(ps.bdcRows)} BDC + ${formatNumber(ps.nportRows)} N-PORT`}
          />
          <StatCard label="Reporting Entities" value={formatNumber(ps.totalCiks)} />
          <StatCard
            label="Unclassified"
            value={`${((ps.unclassifiedPct ?? 0) * 100).toFixed(1)}%`}
            sub="of all holdings"
          />
          {gav && (
            <>
              <StatCard
                label="GAV Median"
                value={`${gav.median?.toFixed(3)}x`}
                sub={`${formatNumber(gav.totalCikQuarters)} CIK-quarters`}
              />
              <StatCard
                label="GAV 0.95-1.05x"
                value={`${gav.within95_105Pct}%`}
                sub={`0.8-1.2x: ${gav.within80_120Pct}%`}
              />
            </>
          )}
          {llmVal && (
            <StatCard
              label="LLM Fund Accuracy"
              value={`${(llmVal.overallAccuracy * 100).toFixed(1)}%`}
              sub={`${formatNumber(llmVal.totalSamples)} fund names tested`}
            />
          )}
        </div>
      )}

      {/* ---- Reconciliation Distributions (4 per row) ---- */}
      {data.reconciliationHistograms && data.reconciliationHistograms.length > 0 && (
        <section className="mb-10">
          <SectionHeading>Reconciliation Distributions</SectionHeading>
          <div className="grid grid-cols-2 xl:grid-cols-4 gap-3">
            {data.reconciliationHistograms.map((h) => (
              <MplHistogram key={h.id} data={h} />
            ))}
          </div>
        </section>
      )}

      {/* ---- Field Fill Rates ---- */}
      {data.fieldFillRates && (
        <section className="bg-white p-6 shadow-card mb-10">
          <SectionHeading>Field Fill Rates</SectionHeading>
          <p className="text-xs text-muted mb-4">
            Percentage of unified holdings rows with non-null, non-zero values for each field.
          </p>
          <ResponsiveContainer width="100%" height={260}>
            <BarChart
              data={data.fieldFillRates}
              layout="vertical"
              margin={{ top: 5, right: 30, bottom: 5, left: 80 }}
            >
              <CartesianGrid strokeDasharray="3 3" stroke="#E2E8F0" horizontal={false} />
              <XAxis
                type="number"
                domain={[0, 1]}
                tickFormatter={(v: number) => `${(v * 100).toFixed(0)}%`}
                tick={{ fontSize: 11, fill: MUTED }}
                axisLine={{ stroke: '#E2E8F0' }}
              />
              <YAxis
                dataKey="field"
                type="category"
                tick={{ fontSize: 11, fill: NAVY }}
                axisLine={{ stroke: '#E2E8F0' }}
                width={75}
              />
              <Tooltip
                contentStyle={{ fontSize: 12, borderRadius: 4, border: '1px solid #E2E8F0' }}
                formatter={(v: number) => [`${(v * 100).toFixed(1)}%`, 'Fill Rate']}
              />
              <Bar dataKey="fillPct" radius={[0, 3, 3, 0]}>
                {data.fieldFillRates.map((entry) => (
                  <Cell
                    key={entry.field}
                    fill={entry.fillPct >= 0.8 ? TEAL : entry.fillPct >= 0.4 ? ORANGE : '#E63946'}
                  />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </section>
      )}

      {/* ---- Holdings by Quarter ---- */}
      {quarterlyData.length > 0 && (
        <section className="bg-white p-6 shadow-card mb-10">
          <SectionHeading>Holdings by Quarter</SectionHeading>
          <p className="text-xs text-muted mb-4">
            Position count by source (BDC XBRL vs N-PORT), per calendar quarter.
          </p>
          <ResponsiveContainer width="100%" height={300}>
            <AreaChart data={quarterlyData} margin={{ top: 5, right: 20, bottom: 5, left: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#E2E8F0" />
              <XAxis
                dataKey="label"
                tick={{ fontSize: 10, fill: MUTED }}
                interval={Math.max(0, Math.floor(quarterlyData.length / 10) - 1)}
                axisLine={{ stroke: '#E2E8F0' }}
              />
              <YAxis
                tick={{ fontSize: 11, fill: MUTED }}
                tickFormatter={(v: number) => v >= 1000 ? `${(v / 1000).toFixed(0)}K` : String(v)}
                axisLine={{ stroke: '#E2E8F0' }}
              />
              <Tooltip
                contentStyle={{ fontSize: 12, borderRadius: 4, border: '1px solid #E2E8F0' }}
                formatter={(v: number, name: string) => [
                  formatNumber(v),
                  name === 'bdc' ? 'BDC' : 'N-PORT',
                ]}
                labelFormatter={(label: string) => label}
              />
              <Area type="monotone" dataKey="bdc" stackId="1" fill={TEAL} stroke={TEAL} fillOpacity={0.7} name="bdc" />
              <Area type="monotone" dataKey="nport" stackId="1" fill={ORANGE} stroke={ORANGE} fillOpacity={0.5} name="nport" />
            </AreaChart>
          </ResponsiveContainer>
          <div className="flex justify-center gap-6 mt-3">
            <LegendItem color={TEAL} label="BDC (10-K/10-Q XBRL)" />
            <LegendItem color={ORANGE} label="N-PORT" />
          </div>
        </section>
      )}

      {/* ---- Classification + Rules ---- */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-8 mb-10">
        {data.classificationBreakdown && data.classificationBreakdown.length > 0 && (
          <section className="bg-white p-6 shadow-card">
            <SectionHeading>Classification Breakdown</SectionHeading>
            <p className="text-xs text-muted mb-4">
              Index classification distribution for the latest full quarter by fair value.
            </p>
            <div className="space-y-2">
              {data.classificationBreakdown.map((row) => (
                <ClassificationBar key={row.classification} row={row} />
              ))}
            </div>
          </section>
        )}
        {data.classificationRules && (
          <section className="bg-white p-6 shadow-card">
            <SectionHeading>Classification Rule Accuracy</SectionHeading>
            <p className="text-xs text-muted mb-4">
              Cross-reference validation rules. Disagreement rate vs expected classification.
            </p>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-surface-muted text-left">
                    <th className="py-2 pr-3 text-xs text-muted font-medium">Rule</th>
                    <th className="py-2 pr-3 text-xs text-muted font-medium">Condition</th>
                    <th className="py-2 pr-3 text-xs text-muted font-medium text-right">Rows</th>
                    <th className="py-2 pr-3 text-xs text-muted font-medium text-right">Disagree</th>
                    <th className="py-2 text-xs text-muted font-medium text-right">Rate</th>
                  </tr>
                </thead>
                <tbody>
                  {data.classificationRules.map((r) => (
                    <tr key={r.rule} className="border-b border-surface-muted/50">
                      <td className="py-2 pr-3 font-mono text-xs text-navy">{r.rule.split(':')[0]}</td>
                      <td className="py-2 pr-3 text-xs text-navy/70 max-w-[200px] truncate">{r.description}</td>
                      <td className="py-2 pr-3 text-xs text-right tabular-nums">{formatNumber(r.totalRows)}</td>
                      <td className="py-2 pr-3 text-xs text-right tabular-nums">{formatNumber(r.disagreements)}</td>
                      <td className={`py-2 text-xs text-right tabular-nums font-semibold ${
                        r.pct === 0 ? 'text-teal' : r.pct < 1 ? 'text-navy' : 'text-red'
                      }`}>
                        {r.pct.toFixed(2)}%
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        )}
      </div>

      {/* ---- Third-party validation ---- */}
      {data.thirdPartyValidation && data.thirdPartyValidation.length > 0 && (
        <section className="mb-10">
          <SectionHeading>Third-Party Universe Validation</SectionHeading>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            {data.thirdPartyValidation.map((tp) => (
              <div key={tp.source} className="bg-white p-5 shadow-card">
                <p className="text-xs text-muted uppercase tracking-wider mb-2">
                  {tp.source.replace(/_/g, ' ')}
                </p>
                <div className="flex items-baseline gap-3">
                  <span className={`text-2xl font-bold tabular-nums ${
                    tp.matchPct >= 95 ? 'text-teal' : tp.matchPct >= 80 ? 'text-navy' : 'text-red'
                  }`}>
                    {tp.matchPct.toFixed(0)}%
                  </span>
                  <span className="text-xs text-muted">
                    {tp.total - tp.missed}/{tp.total} matched
                  </span>
                </div>
                <div className="mt-2 h-1.5 bg-surface rounded-full overflow-hidden">
                  <div
                    className="h-full rounded-full"
                    style={{
                      width: `${tp.matchPct}%`,
                      backgroundColor: tp.matchPct >= 95 ? TEAL : ORANGE,
                    }}
                  />
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* ---- LLM Fund Classification Validation ---- */}
      {llmVal && <LlmFundValidationSection data={llmVal} />}
    </div>
  );
}

/* ---------- Sub-components ---------- */

function ClassificationBar({ row }: { row: { classification: string; fv: number; fvPct: number; rows: number } }) {
  const pct = row.fvPct * 100;
  const label = row.classification.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
  return (
    <div className="flex items-center gap-3">
      <div className="w-36 text-xs text-navy truncate shrink-0">{label}</div>
      <div className="flex-1 h-5 bg-surface rounded-sm overflow-hidden relative">
        <div className="h-full rounded-sm" style={{ width: `${Math.max(pct, 0.5)}%`, backgroundColor: TEAL, opacity: 0.8 }} />
      </div>
      <div className="w-16 text-xs text-right tabular-nums text-navy/70 shrink-0">
        {pct >= 1 ? `${pct.toFixed(1)}%` : `${pct.toFixed(2)}%`}
      </div>
      <div className="w-16 text-xs text-right tabular-nums text-muted shrink-0">{formatDollar(row.fv)}</div>
    </div>
  );
}

function LegendItem({ color, label }: { color: string; label: string }) {
  return (
    <div className="flex items-center gap-2 text-xs text-muted">
      <span className="w-3 h-3 rounded-sm shrink-0" style={{ backgroundColor: color }} />
      {label}
    </div>
  );
}

/* ---------- LLM Fund Validation ---------- */

function heatmapColor(value: number, maxVal: number, isDiagonal: boolean): string {
  if (value === 0) return '#f8fafc';
  const intensity = Math.min(value / Math.max(maxVal, 1), 1);
  if (isDiagonal) {
    // Teal gradient for correct predictions
    const r = Math.round(42 + (248 - 42) * (1 - intensity));
    const g = Math.round(157 + (250 - 157) * (1 - intensity));
    const b = Math.round(143 + (252 - 143) * (1 - intensity));
    return `rgb(${r}, ${g}, ${b})`;
  }
  // Orange gradient for errors
  const r = Math.round(231 + (248 - 231) * (1 - intensity));
  const g = Math.round(111 + (250 - 111) * (1 - intensity));
  const b = Math.round(81 + (252 - 81) * (1 - intensity));
  return `rgb(${r}, ${g}, ${b})`;
}

function metricColor(value: number): string {
  if (value >= 0.9) return TEAL;
  if (value >= 0.7) return NAVY;
  return '#E63946';
}

function LlmFundValidationSection({ data }: { data: LlmFundValidation }) {
  const matrix = data.confusionMatrix;
  const labels = data.labels;
  const maxVal = Math.max(...matrix.flat());

  return (
    <section className="mb-10">
      <SectionHeading>LLM Fund Classification Validation</SectionHeading>
      <p className="text-xs text-muted mb-5">
        Blind validation: GPT-4o-mini classifies already-labeled fund names, predictions compared against ground truth.
        Overall accuracy: <span className="font-semibold">{(data.overallAccuracy * 100).toFixed(1)}%</span> across {formatNumber(data.totalSamples)} fund names.
      </p>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
        {/* Left: Confusion Matrix */}
        <div className="bg-white p-6 shadow-card">
          <h3 className="text-sm font-semibold text-navy mb-4">Confusion Matrix</h3>
          <p className="text-xs text-muted mb-3">
            Rows = actual, columns = predicted.
            <span className="inline-block w-3 h-3 rounded-sm ml-2 mr-1 align-middle" style={{ backgroundColor: TEAL }} />
            Correct
            <span className="inline-block w-3 h-3 rounded-sm ml-2 mr-1 align-middle" style={{ backgroundColor: ORANGE }} />
            Errors
          </p>
          <div className="overflow-x-auto">
            <table className="text-xs border-collapse">
              <thead>
                <tr>
                  <th className="p-1.5 text-right text-muted font-normal w-20" />
                  {labels.map((l) => (
                    <th key={l} className="p-1.5 text-center text-muted font-medium w-16 whitespace-nowrap">
                      {l}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {matrix.map((row, ri) => (
                  <tr key={labels[ri]}>
                    <td className="p-1.5 text-right text-navy font-medium whitespace-nowrap pr-2">
                      {labels[ri]}
                    </td>
                    {row.map((val, ci) => (
                      <td
                        key={ci}
                        className="p-1.5 text-center tabular-nums border border-white/60"
                        style={{
                          backgroundColor: heatmapColor(val, maxVal, ri === ci),
                          color: val > maxVal * 0.6 ? '#fff' : NAVY,
                          fontWeight: ri === ci ? 600 : 400,
                          minWidth: 42,
                        }}
                      >
                        {val}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* Right: Per-class metrics */}
        <div className="bg-white p-6 shadow-card">
          <h3 className="text-sm font-semibold text-navy mb-4">Per-Class Metrics</h3>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-surface-muted text-left">
                  <th className="py-2 pr-3 text-xs text-muted font-medium">Class</th>
                  <th className="py-2 pr-3 text-xs text-muted font-medium text-right">Precision</th>
                  <th className="py-2 pr-3 text-xs text-muted font-medium text-right">Recall</th>
                  <th className="py-2 pr-3 text-xs text-muted font-medium text-right">F1</th>
                  <th className="py-2 text-xs text-muted font-medium text-right">Support</th>
                </tr>
              </thead>
              <tbody>
                {data.perClassMetrics.map((m) => (
                  <tr key={m.label} className="border-b border-surface-muted/50">
                    <td className="py-2.5 pr-3 text-xs text-navy font-medium">{m.label}</td>
                    <td className="py-2.5 pr-3 text-xs text-right tabular-nums font-semibold"
                        style={{ color: metricColor(m.precision) }}>
                      {(m.precision * 100).toFixed(1)}%
                    </td>
                    <td className="py-2.5 pr-3 text-xs text-right tabular-nums font-semibold"
                        style={{ color: metricColor(m.recall) }}>
                      {(m.recall * 100).toFixed(1)}%
                    </td>
                    <td className="py-2.5 pr-3 text-xs text-right tabular-nums font-semibold"
                        style={{ color: metricColor(m.f1) }}>
                      {(m.f1 * 100).toFixed(1)}%
                    </td>
                    <td className="py-2.5 text-xs text-right tabular-nums text-muted">
                      {formatNumber(m.support)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </section>
  );
}
