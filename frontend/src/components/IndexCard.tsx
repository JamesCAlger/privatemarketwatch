import Link from 'next/link';
import { formatLevel, formatQuarter, returnSign, returnColor } from '@/lib/format';

interface IndexCardProps {
  name: string;
  slug: string;
  level: number | null;
  trailing12m: number | null;
  color: string;
  asOfQuarter: string | null;
}

export default function IndexCard({
  name,
  slug,
  level,
  trailing12m,
  color,
  asOfQuarter,
}: IndexCardProps) {
  return (
    <Link
      href={`/indices/${slug}`}
      className="block bg-white rounded-lg p-5 shadow-sm hover:shadow-md transition-all"
    >
      <div className="flex items-center gap-2 mb-3">
        <span
          className="w-2.5 h-2.5 rounded-full shrink-0"
          style={{ backgroundColor: color }}
        />
        <h3 className="font-semibold text-navy text-lg">{name}</h3>
      </div>
      <div className="flex items-baseline justify-between">
        <div>
          <p className="text-xs text-muted mb-0.5">
            {asOfQuarter ? `As of ${formatQuarter(asOfQuarter)}` : ''}
          </p>
          <p className="text-2xl font-bold text-navy tabular-nums">
            {formatLevel(level)}
          </p>
        </div>
        <div className="text-right">
          <p className="text-xs text-muted mb-0.5">1 YR Return</p>
          <p className={`text-2xl font-bold tabular-nums ${returnColor(trailing12m)}`}>
            {returnSign(trailing12m)}
          </p>
        </div>
      </div>
    </Link>
  );
}
