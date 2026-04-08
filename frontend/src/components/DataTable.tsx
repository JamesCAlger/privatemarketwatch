'use client';

import { useState, useMemo } from 'react';

export interface Column<T> {
  key: keyof T & string;
  header: string;
  align?: 'left' | 'right';
  format?: (value: any) => string;  // eslint-disable-line
}

interface DataTableProps<T> {
  columns: Column<T>[];
  data: T[];
  sortable?: boolean;
}

export default function DataTable<T extends Record<string, any>>({  // eslint-disable-line
  columns,
  data,
  sortable = false,
}: DataTableProps<T>) {
  const [sortKey, setSortKey] = useState<string | null>(null);
  const [sortAsc, setSortAsc] = useState(true);

  const sorted = useMemo(() => {
    if (!sortable || !sortKey) return data;
    return [...data].sort((a, b) => {
      const av = a[sortKey];
      const bv = b[sortKey];
      if (av == null && bv == null) return 0;
      if (av == null) return 1;
      if (bv == null) return -1;
      const cmp = typeof av === 'number' && typeof bv === 'number'
        ? av - bv
        : String(av).localeCompare(String(bv));
      return sortAsc ? cmp : -cmp;
    });
  }, [data, sortKey, sortAsc, sortable]);

  const handleSort = (key: string) => {
    if (!sortable) return;
    if (sortKey === key) {
      setSortAsc(!sortAsc);
    } else {
      setSortKey(key);
      setSortAsc(true);
    }
  };

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-surface-muted">
            {columns.map((col) => (
              <th
                key={col.key}
                className={`py-2 px-3 font-medium text-muted text-xs uppercase tracking-wider ${
                  col.align === 'right' ? 'text-right' : 'text-left'
                } ${sortable ? 'cursor-pointer select-none hover:text-navy' : ''}`}
                onClick={() => handleSort(col.key)}
              >
                {col.header}
                {sortable && sortKey === col.key && (
                  <span className="ml-1">{sortAsc ? '\u2191' : '\u2193'}</span>
                )}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.map((row, i) => (
            <tr
              key={i}
              className="border-b border-surface last:border-0 hover:bg-surface transition-colors"
            >
              {columns.map((col) => (
                <td
                  key={col.key}
                  className={`py-2 px-3 tabular-nums ${
                    col.align === 'right' ? 'text-right' : 'text-left'
                  }`}
                >
                  {col.format
                    ? col.format(row[col.key])
                    : String(row[col.key] ?? '--')}
                </td>
              ))}
            </tr>
          ))}
          {sorted.length === 0 && (
            <tr>
              <td
                colSpan={columns.length}
                className="py-8 text-center text-muted"
              >
                No data available
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
