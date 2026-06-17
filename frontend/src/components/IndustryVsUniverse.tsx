import type { GicsSectorRow } from '@/lib/types';

interface IndustryVsUniverseProps {
  fundSectors: { sector: string; pct: number }[];
  universe: GicsSectorRow[];
}

export default function IndustryVsUniverse({ fundSectors, universe }: IndustryVsUniverseProps) {
  const rows = (fundSectors ?? []).filter((s) => s.pct > 0).sort((a, b) => b.pct - a.pct);
  if (rows.length === 0) return null;

  const uMap = new Map(universe.map((u) => [u.sector, u.pctOfTotal]));
  const max = Math.max(...rows.map((r) => Math.max(r.pct, uMap.get(r.sector) ?? 0)), 0.01);

  return (
    <div>
      <div className="space-y-3">
        {rows.map((r) => {
          const u = uMap.get(r.sector) ?? 0;
          const diff = r.pct - u;
          return (
            <div key={r.sector}>
              <div className="flex justify-between items-baseline text-xs mb-1">
                <span className="text-ink2">{r.sector}</span>
                <span className="font-mono tabular-nums text-ink font-medium">
                  {(r.pct * 100).toFixed(1)}%
                  {u > 0 && (
                    <span className={`ml-2 text-[10px] font-normal ${diff >= 0 ? 'text-accent' : 'text-ink3'}`}>
                      {diff >= 0 ? '+' : ''}{(diff * 100).toFixed(1)} vs univ
                    </span>
                  )}
                </span>
              </div>
              <div className="relative h-2.5 bg-rule2">
                <div
                  className="absolute left-0 top-0 bottom-0 bg-navy"
                  style={{ width: `${(r.pct / max) * 100}%` }}
                />
                {u > 0 && (
                  <div
                    className="absolute top-[-2px] bottom-[-2px] w-[2px] bg-ink3"
                    style={{ left: `${(u / max) * 100}%` }}
                    title={`Universe ${(u * 100).toFixed(1)}%`}
                  />
                )}
              </div>
            </div>
          );
        })}
      </div>
      <div className="border-t border-rule2 pt-3 mt-4 text-[11px] text-ink3">
        Bar is this fund&apos;s share of holdings; the tick marks the universe share. GICS sectors.
      </div>
    </div>
  );
}
