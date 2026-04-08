import { returnColor } from '@/lib/format';

interface StatValueProps {
  label: string;
  value: string;
  delta?: number | null;
  size?: 'sm' | 'lg';
}

export default function StatValue({
  label,
  value,
  delta,
  size = 'sm',
}: StatValueProps) {
  return (
    <div>
      <p className="text-xs text-muted mb-0.5">{label}</p>
      <p
        className={`font-bold text-navy tabular-nums ${
          size === 'lg' ? 'text-2xl' : 'text-lg'
        } ${delta != null ? returnColor(delta) : ''}`}
      >
        {value}
      </p>
    </div>
  );
}
