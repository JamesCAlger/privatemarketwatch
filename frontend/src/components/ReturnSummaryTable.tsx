import { returnColor } from '@/lib/format';

export interface ReturnRow {
  label: string;
  net: number | null;
  gross: number | null;
}

interface ReturnSummaryTableProps {
  rows: ReturnRow[];
  showGross?: boolean;
}

function fmtRet(v: number | null): string {
  if (v == null) return '--';
  const pct = (v * 100).toFixed(1);
  return v >= 0 ? `+${pct}%` : `${pct}%`;
}

function fmtDrag(gross: number | null, net: number | null): string {
  if (gross == null || net == null) return '--';
  const diff = (gross - net) * 100;
  const pp = Math.abs(diff).toFixed(1);
  return `\u2212${pp} pp`;
}

export default function ReturnSummaryTable({ rows, showGross = true }: ReturnSummaryTableProps) {
  return (
    <div>
      <div className="eyebrow text-ink2 mb-3.5">Total return summary</div>
      {/* Header row */}
      {showGross ? (
        <div className="grid grid-cols-[1.4fr_1fr_1fr_0.9fr] gap-x-2 pb-2 border-b border-rule text-[10px] uppercase tracking-[0.12em] text-ink3">
          <span />
          <span className="text-right">Net</span>
          <span className="text-right">Gross</span>
          <span className="text-right">Fee drag</span>
        </div>
      ) : (
        <div className="grid grid-cols-[1.4fr_1fr] gap-x-2 pb-2 border-b border-rule text-[10px] uppercase tracking-[0.12em] text-ink3">
          <span />
          <span className="text-right">Return</span>
        </div>
      )}
      {rows.map((r) => (
        showGross ? (
          <div
            key={r.label}
            className="grid grid-cols-[1.4fr_1fr_1fr_0.9fr] gap-x-2 items-baseline py-3 border-b border-rule2"
          >
            <span className="text-xs text-ink2">{r.label}</span>
            <span className={`font-mono text-[19px] font-semibold text-right tabular-nums ${returnColor(r.net)}`}>
              {fmtRet(r.net)}
            </span>
            <span className="font-mono text-[13px] text-ink3 text-right tabular-nums">
              {fmtRet(r.gross)}
            </span>
            <span className="font-mono text-xs text-ink3 text-right tabular-nums">
              {fmtDrag(r.gross, r.net)}
            </span>
          </div>
        ) : (
          <div
            key={r.label}
            className="grid grid-cols-[1.4fr_1fr] gap-x-2 items-baseline py-3 border-b border-rule2"
          >
            <span className="text-xs text-ink2">{r.label}</span>
            <span className={`font-mono text-[19px] font-semibold text-right tabular-nums ${returnColor(r.net)}`}>
              {fmtRet(r.net)}
            </span>
          </div>
        )
      ))}
    </div>
  );
}
