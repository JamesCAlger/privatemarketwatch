'use client';

import DataTable, { type Column } from './DataTable';
import { formatDollar, formatNumber, formatPercent } from '@/lib/format';
import type { VehicleRow } from '@/lib/types';

const columns: Column<VehicleRow>[] = [
  {
    key: 'entityName',
    header: 'Entity',
    format: (v) => String(v ?? '--'),
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
