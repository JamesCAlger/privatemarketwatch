'use client';

import { useEffect, useMemo, useState } from 'react';
import { formatDollar } from '@/lib/format';

type Observation = {
  row_id: string; entity_id: string | null; position_id: string;
  issuer_name: string; instrument_description: string; report_date: string;
  fair_value: number | null; cost: number | null; interest_rate: number | null;
  maturity_date: string | null; accession_number: string;
  maturity_precision?: string; gics_sub_industry: string | null;
  evidence?: Partial<Record<Field, Citation>>;
};
type Field = 'fair_value' | 'cost' | 'interest_rate' | 'maturity_date' | 'gics_sub_industry';
type Citation = {
  status: 'direct' | 'inferred' | 'calculated' | 'unavailable';
  reason?: string; href?: string; source_text?: string; method?: string;
  decision_id?: string; donor_row_id?: string; donor_date?: string;
  release_id?: string; row_id?: string; field?: string; input?: Citation;
  model?: string; input_text?: string; taxonomy_sha256?: string;
  accession_number?: string; source_sha256?: string;
  source_amount?: string; source_currency?: string;
  calculation?: {
    source_value?: string; tagged_currency?: string; resolved_currency?: string;
    conversion?: { quote_date?: string; quote_id?: string };
  };
};
const monetaryReasons: Record<string, string> = {
  FX_unavailable: 'A usable USD conversion is unavailable.',
  FX_stale: 'No FX quote within seven days of this reporting date is available.',
  unit_unresolved: 'The source monetary unit is unresolved.',
};
type Quarter = { quarter: string; rows: number; path: string; sha256: string };
type HistoryIndex = { release_id: string; cik: string; quarters: Quarter[] };
type History = { release_id: string; cik: string; quarter: string; rows: Observation[];
  citations?: Record<string, Partial<Record<Field, Citation>>> };

const PAGE_SIZE = 100;

export default function FundHoldingsHistory({ cik }: { cik: string }) {
  const fundCik = cik.padStart(10, '0');
  const base = `/data/holdings_history/${fundCik}`;
  const [index, setIndex] = useState<HistoryIndex | null>(null);
  const [quarter, setQuarter] = useState('');
  const [history, setHistory] = useState<History | null>(null);
  const [error, setError] = useState('');
  const [query, setQuery] = useState('');
  const [page, setPage] = useState(0);
  const [selected, setSelected] = useState<{ row: Observation; field: Field } | null>(null);

  useEffect(() => {
    const abort = new AbortController();
    setIndex(null); setHistory(null); setError(''); setQuarter('');
    fetch(`${base}/index.json`, { signal: abort.signal })
      .then(async response => {
        if (!response.ok) throw new Error('Holdings history is not available for this release.');
        const value: HistoryIndex = await response.json();
        if (abort.signal.aborted) return;
        if (value.cik !== fundCik || !Array.isArray(value.quarters)) throw new Error('Holdings history could not be verified.');
        setIndex(value); setQuarter(value.quarters.at(-1)?.quarter ?? '');
      }).catch(e => { if (e.name !== 'AbortError') setError(e.message); });
    return () => abort.abort();
  }, [base, fundCik]);

  useEffect(() => {
    if (!quarter || !index) return;
    const abort = new AbortController();
    setHistory(null); setSelected(null); setPage(0); setError('');
    fetch(`${base}/${quarter}.json`, { signal: abort.signal })
      .then(async response => {
        if (!response.ok) throw new Error('This quarter is unavailable.');
        const bytes = await response.arrayBuffer();
        const expected = index.quarters.find(q => q.quarter === quarter);
        const digest = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', bytes)))
          .map(byte => byte.toString(16).padStart(2, '0')).join('');
        if (abort.signal.aborted) return;
        if (!expected || digest !== expected.sha256) throw new Error('The quarter does not match this release.');
        const value: History = JSON.parse(new TextDecoder().decode(bytes));
        if (value.release_id !== index.release_id || value.cik !== fundCik || value.quarter !== quarter
          || !Array.isArray(value.rows) || value.rows.length !== expected.rows)
          throw new Error('The quarter does not match this release.');
        setHistory(value);
      }).catch(e => { if (e.name !== 'AbortError') setError(e.message); });
    return () => abort.abort();
  }, [base, fundCik, index, quarter]);

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return (history?.rows ?? []).filter(row => !needle
      || `${row.issuer_name} ${row.instrument_description}`.toLowerCase().includes(needle));
  }, [history, query]);
  const pages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const visible = filtered.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);
  const proposedCitation = selected ? selected.row.evidence?.[selected.field]
    ?? history?.citations?.[selected.row.row_id]?.[selected.field] : undefined;
  const citation = proposedCitation?.release_id === history?.release_id
    && proposedCitation?.row_id === selected?.row.row_id && proposedCitation?.field === selected?.field
    ? proposedCitation : undefined;
  const sourcePath = new RegExp(`^${base}/sources/[0-9-]+-[a-f0-9]{16}\\.html#evidence-[a-f0-9]{24}$`);
  const sourceHref = (item: Citation | undefined, accession?: string) => item?.href
    && sourcePath.test(item.href) && item.accession_number === accession
    && /^[0-9-]+$/.test(accession ?? '') && /^[a-f0-9]{64}$/.test(item.source_sha256 ?? '')
    && item.href.startsWith(`${base}/sources/${accession}-${item.source_sha256?.slice(0, 16)}.html#`)
    ? item.href : undefined;
  const safeHref = sourceHref(citation, selected?.row.accession_number);
  const donor = citation?.input;
  const donorHref = donor?.status === 'direct' && donor.release_id === history?.release_id
    && donor.row_id === citation?.donor_row_id && donor.field === 'fair_value'
    ? sourceHref(donor, donor.accession_number) : undefined;

  return <section className="py-6 space-y-4" aria-label="Holdings history">
    <div className="flex flex-wrap items-end gap-4">
      <label className="text-sm">Reporting date
        <select aria-label="Reporting date" value={quarter} onChange={e => setQuarter(e.target.value)}
          className="block border border-surface rounded px-3 py-2 mt-1 bg-white">
          {index?.quarters.map(q => <option key={q.quarter} value={q.quarter}>{q.quarter} ({q.rows.toLocaleString()} positions)</option>)}
        </select>
      </label>
      <label className="text-sm flex-1 min-w-48">Company or instrument
        <input value={query} onChange={e => { setQuery(e.target.value); setPage(0); }}
          className="block w-full border border-surface rounded px-3 py-2 mt-1" type="search" />
      </label>
      {history && <a className="text-sm text-teal underline" href={`${base}/${quarter}.json`} download>Download complete quarter</a>}
    </div>
    {error && <p role="status" className="text-sm text-ink3">{error}</p>}
    {!history && !error && <p role="status" className="text-sm text-ink3">{index?.quarters.length === 0
      ? 'No holdings observations are available for this fund in this release.' : 'Loading holdings history...'}</p>}
    {history && <>
      <p className="text-sm text-ink3">{filtered.length.toLocaleString()} of {history.rows.length.toLocaleString()} disclosed positions. Select a value to inspect its evidence.</p>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-navy text-white"><tr>{['Company / instrument', 'Fair value', 'Cost', 'All-in coupon', 'Maturity', 'Industry'].map(label =>
            <th key={label} className="p-3 text-left font-medium">{label}</th>)}</tr></thead>
          <tbody>{visible.map(row => <tr key={row.row_id} className="border-b border-surface">
            <td className="p-3"><div className="font-medium">{row.issuer_name}</div><div className="text-xs text-ink3">{row.instrument_description}</div></td>
            {(['fair_value', 'cost', 'interest_rate', 'maturity_date', 'gics_sub_industry'] as Field[]).map(field => <td key={field} className="p-3 tabular-nums">
              <button className="underline decoration-dotted underline-offset-4" onClick={() => setSelected({ row, field })}
                aria-label={`Evidence for ${field.replaceAll('_', ' ')}: ${row.issuer_name}`}>
                {row[field] == null || row[field] === '' ? 'Unavailable' : field === 'gics_sub_industry' ? String(row[field])
                  : field === 'maturity_date' ? row.maturity_precision === 'month' ? String(row[field]).slice(0, 7)
                    : row.maturity_precision === 'year' ? String(row[field]).slice(0, 4) : String(row[field])
                  : field === 'interest_rate' ? `${Number(row[field]).toFixed(2)}%` : formatDollar(Number(row[field]))}
              </button>
            </td>)}
          </tr>)}</tbody>
        </table>
      </div>
      <div className="flex items-center gap-4 text-sm">
        <button disabled={page === 0} onClick={() => setPage(page - 1)} className="disabled:opacity-40">Previous</button>
        <span>Page {page + 1} of {pages}</span>
        <button disabled={page + 1 >= pages} onClick={() => setPage(page + 1)} className="disabled:opacity-40">Next</button>
      </div>
    </>}
    {selected && <aside className="border border-surface rounded p-4 space-y-2" aria-label="Field evidence">
      <div className="flex justify-between gap-4"><h3 className="font-medium">{selected.row.issuer_name}: {selected.field.replaceAll('_', ' ')}</h3>
        <button onClick={() => setSelected(null)} aria-label="Close evidence">Close</button></div>
      <p className="text-sm">{citation?.status === 'inferred' ? 'Inferred classification' : citation?.status === 'calculated'
        ? citation.method === 'report_date_reference_conversion' ? 'Calculated USD fair value'
          : citation.method === 'already_USD' ? 'Reviewed USD denomination'
          : `Calculated: ${citation.method ?? 'method unavailable'}` : citation?.status === 'direct' && safeHref
          ? 'Cached source filing' : 'Source evidence unavailable'}</p>
      {safeHref && citation?.status === 'direct' ? <a className="text-teal underline" href={safeHref} target="_blank" rel="noopener noreferrer">Open highlighted filing</a>
        : <p className="text-sm text-ink3">{(citation?.reason && (monetaryReasons[citation.reason] ?? citation.reason)) || 'No verified field locator is available for this observation in this release.'}</p>}
      {citation?.source_amount && <p className="text-sm">Source amount: {citation.source_currency} {citation.source_amount}.</p>}
      {citation?.calculation && <p className="text-sm">
        Source amount: {citation.calculation.resolved_currency} {citation.calculation.source_value}.
        {citation.calculation.conversion?.quote_date && <> ECB observation: {citation.calculation.conversion.quote_date}.</>}
      </p>}
      {citation?.donor_row_id && <p className="text-sm">Donor observation: {citation.donor_date} ({citation.donor_row_id})</p>}
      {donorHref && <a className="text-teal underline" href={donorHref} target="_blank" rel="noopener noreferrer">Open donor fair value evidence</a>}
      {citation?.status === 'inferred' && <p className="text-sm text-ink3">Input: {citation.input_text}. Model: {citation.model}. Decision: {citation.decision_id}.</p>}
      <details className="text-xs text-ink3"><summary>Observation provenance</summary>
        <dl className="break-all space-y-1 mt-2"><dt>Observation</dt><dd>{selected.row.row_id}</dd><dt>Position</dt><dd>{selected.row.position_id}</dd>
          <dt>Entity</dt><dd>{selected.row.entity_id ?? 'Unresolved'}</dd><dt>Filing</dt><dd>{selected.row.accession_number}</dd>
          <dt>Release</dt><dd>{history?.release_id}</dd></dl>
      </details>
    </aside>}
  </section>;
}
