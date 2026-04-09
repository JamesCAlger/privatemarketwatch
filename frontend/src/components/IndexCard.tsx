import Link from 'next/link';
import { formatLevel, formatQuarter, formatNumber, returnSign, returnColor } from '@/lib/format';
import SparklineChart from './SparklineChart';

interface IndexCardProps {
  name: string;
  slug: string;
  level: number | null;
  trailing12m: number | null;
  qoqReturn?: number | null;
  constituents?: number | null;
  color: string;
  asOfQuarter: string | null;
  sparkline?: number[];
}

export default function IndexCard({
  name,
  slug,
  level,
  trailing12m,
  qoqReturn,
  constituents,
  color,
  asOfQuarter,
  sparkline,
}: IndexCardProps) {
  return (
    <Link
      href={`/indices/${slug}`}
      className="block bg-white rounded-lg shadow-card hover:shadow-card-hover transition-all overflow-hidden"
    >
      <div className="flex">
        {/* Left accent border */}
        <div className="w-1 shrink-0" style={{ backgroundColor: color }} />

        <div className="flex-1 p-5">
          {/* Header row */}
          <div className="mb-3">
            <h3 className="font-semibold text-navy text-lg">{name}</h3>
          </div>

          {/* Stats row */}
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

          {/* Bottom meta row */}
          {(qoqReturn != null || constituents != null) && (
            <div className="flex items-center gap-4 mt-3 pt-3 border-t border-surface-muted text-xs text-muted">
              {qoqReturn != null && (
                <span>
                  QoQ: <span className={`font-medium ${returnColor(qoqReturn)}`}>{returnSign(qoqReturn)}</span>
                </span>
              )}
              {constituents != null && (
                <span>{formatNumber(constituents)} holdings</span>
              )}
            </div>
          )}
        </div>
      </div>
    </Link>
  );
}
