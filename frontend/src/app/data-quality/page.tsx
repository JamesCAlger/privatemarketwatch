import { Metadata } from 'next';
import { getDataQuality } from '@/lib/data';
import DataQualityDashboard from './DataQualityDashboard';

export const metadata: Metadata = {
  title: 'Data Quality',
  description: 'Pipeline data quality metrics and validation dashboard.',
};

export default function DataQualityPage() {
  const data = getDataQuality();

  return (
    <div>
      {/* Hero banner */}
      <div className="hero-gradient hero-pattern">
        <div className="mx-auto max-w-6xl px-4 sm:px-6 py-12 md:py-16">
          <h1 className="text-display-sm md:text-display-lg text-white mb-3">
            Data Quality
          </h1>
          <p className="text-white/60 max-w-2xl text-lg">
            Pipeline validation metrics, field coverage, and reconciliation diagnostics.
          </p>
        </div>
      </div>

      <DataQualityDashboard data={data} />
    </div>
  );
}
