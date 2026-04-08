/**
 * Formatting utilities for numbers, dates, and returns.
 *
 * All functions handle null/undefined gracefully, returning '--'.
 */

export function formatPercent(value: number | null | undefined, decimals = 1): string {
  if (value == null || isNaN(value)) return '--';
  return `${(value * 100).toFixed(decimals)}%`;
}

export function formatBps(value: number | null | undefined): string {
  if (value == null || isNaN(value)) return '--';
  return `${Math.round(value * 10000)} bps`;
}

export function formatDollar(value: number | null | undefined): string {
  if (value == null || isNaN(value)) return '--';
  const abs = Math.abs(value);
  const sign = value < 0 ? '-' : '';
  if (abs >= 1e12) return `${sign}$${(abs / 1e12).toFixed(1)}T`;
  if (abs >= 1e9) return `${sign}$${(abs / 1e9).toFixed(1)}B`;
  if (abs >= 1e6) return `${sign}$${(abs / 1e6).toFixed(1)}M`;
  if (abs >= 1e3) return `${sign}$${(abs / 1e3).toFixed(0)}K`;
  return `${sign}$${abs.toFixed(0)}`;
}

export function formatDollarFull(value: number | null | undefined): string {
  if (value == null || isNaN(value)) return '--';
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: 0,
  }).format(value);
}

export function formatLevel(value: number | null | undefined): string {
  if (value == null || isNaN(value)) return '--';
  return value.toFixed(2);
}

export function formatNumber(value: number | null | undefined, decimals = 0): string {
  if (value == null || isNaN(value)) return '--';
  return new Intl.NumberFormat('en-US', {
    maximumFractionDigits: decimals,
  }).format(value);
}

export function formatQuarter(q: string | null | undefined): string {
  if (!q) return '--';
  // "2025q4" -> "Q4 2025"
  const match = q.match(/^(\d{4})q(\d)$/);
  if (!match) return q;
  return `Q${match[2]} ${match[1]}`;
}

export function returnColor(value: number | null | undefined): string {
  if (value == null || isNaN(value)) return 'text-muted';
  return value >= 0 ? 'text-teal' : 'text-red';
}

export function returnSign(value: number | null | undefined, decimals = 1): string {
  if (value == null || isNaN(value)) return '--';
  const pct = (value * 100).toFixed(decimals);
  return value >= 0 ? `+${pct}%` : `${pct}%`;
}

export function formatYears(value: number | null | undefined): string {
  if (value == null || isNaN(value)) return '--';
  return `${value.toFixed(1)} yrs`;
}
