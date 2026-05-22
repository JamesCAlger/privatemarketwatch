'use client';

import DataTable, { type Column } from './DataTable';
import { formatDollar, formatNumber, formatPercent } from '@/lib/format';
import type { VehicleRow } from '@/lib/types';
import { getFundNameParts } from '@/lib/nameFormat';

const columns: Column<VehicleRow>[] = [
  {
    key: 'entityName',
    header: 'Entity',
    format: (v) => {
      const parts = getFundNameParts(v);
      if (!parts.displayName) return '--';
      return (
        <div>
          <div>{parts.displayName}</div>
          {parts.ticker && <div className="text-xs text-muted">{parts.ticker}</div>}
        </div>
      );
    },
    sortValue: (v) => getFundNameParts(v).displayName.toLowerCase(),
  },
  {
    key: 'vehicleType',
    header: 'Type',
    format: (v) => {
      const s = String(v ?? '');
      return s.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
    },
  },
  {
    key: 'positionCount',
    header: 'Holdings',
    align: 'right',
    format: (v) => formatNumber(v as number),
  },
  {
    key: 'totalFv',
    header: 'Fair Value',
    align: 'right',
    format: (v) => formatDollar(v as number),
  },
  {
    key: 'pctOfIndex',
    header: '% of Index',
    align: 'right',
    format: (v) => formatPercent(v as number),
  },
];

export default function VehicleTable({
  data,
}: {
  data: VehicleRow[];
}) {
  return <DataTable columns={columns} data={data} sortable />;
}
