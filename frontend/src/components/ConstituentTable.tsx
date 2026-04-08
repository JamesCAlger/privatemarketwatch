'use client';

import DataTable, { type Column } from './DataTable';
import { formatDollarFull, returnSign } from '@/lib/format';
import type { TopConstituent } from '@/lib/types';

const CATEGORY_LABELS: Record<string, string> = {
  EQUITY_COMMON: 'Common',
  EQUITY_PREFERRED: 'Preferred',
};

function makeColumns(indexKey: string): Column<TopConstituent>[] {
  const base: Column<TopConstituent>[] = [
    {
      key: 'issuerName',
      header: 'Issuer',
      format: (v) => String(v ?? '--'),
    },
  ];

  if (indexKey === 'DIRECT_LENDING') {
    base.push({
      key: 'rateType',
      header: 'Rate Type',
      format: (v) => String(v ?? '--'),
    });
  } else {
    base.push({
      key: 'assetCategory',
      header: 'Category',
      format: (v) => {
        const s = String(v ?? '--');
        return CATEGORY_LABELS[s] ?? s;
      },
    });
  }

  base.push(
    {
      key: 'fairValue',
      header: 'Fair Value',
      align: 'right',
      format: (v) => formatDollarFull(v as number),
    },
    {
      key: 'vehicleName',
      header: 'Vehicle',
      format: (v) => String(v ?? '--'),
    },
    {
      key: 'totalReturn',
      header: 'Return',
      align: 'right',
      format: (v) => returnSign(v as number),
    },
  );

  return base;
}

export default function ConstituentTable({
  data,
  indexKey = '',
}: {
  data: TopConstituent[];
  indexKey?: string;
}) {
  const columns = makeColumns(indexKey);
  return <DataTable columns={columns} data={data} sortable />;
}
