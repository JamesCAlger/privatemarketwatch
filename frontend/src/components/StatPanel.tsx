import StatValue from './StatValue';

interface Stat {
  label: string;
  value: string;
  delta?: number | null;
}

interface StatPanelProps {
  stats: Stat[];
  accentColor?: string;
}

export default function StatPanel({ stats, accentColor }: StatPanelProps) {
  if (stats.length === 0) return null;

  // First stat gets featured treatment (large + isolated)
  const featured = stats[0];
  const secondary = stats.slice(1);

  return (
    <div className="bg-white rounded-lg shadow-card overflow-hidden">
      <div className="flex flex-col md:flex-row md:items-center">
        {/* Featured stat */}
        <div className="flex items-center gap-4 p-6 md:pr-8 md:border-r border-b md:border-b-0 border-surface-muted">
          {accentColor && (
            <div className="hidden md:block w-1 h-12 rounded-full" style={{ backgroundColor: accentColor }} />
          )}
          <StatValue label={featured.label} value={featured.value} delta={featured.delta} size="lg" />
        </div>

        {/* Secondary stats grid */}
        <div className="flex-1 grid grid-cols-2 sm:grid-cols-3 md:grid-cols-5 gap-4 p-5">
          {secondary.map((s) => (
            <StatValue key={s.label} label={s.label} value={s.value} delta={s.delta} />
          ))}
        </div>
      </div>
    </div>
  );
}
