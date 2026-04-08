import StatValue from './StatValue';

interface Stat {
  label: string;
  value: string;
  delta?: number | null;
}

interface StatPanelProps {
  stats: Stat[];
}

export default function StatPanel({ stats }: StatPanelProps) {
  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-6 gap-4 bg-white rounded-lg p-5 shadow-sm">
      {stats.map((s) => (
        <StatValue key={s.label} label={s.label} value={s.value} delta={s.delta} />
      ))}
    </div>
  );
}
