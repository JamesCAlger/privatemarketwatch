import fs from 'fs';
import path from 'path';
import type {
  IndexReturnsData,
  IndexSummary,
  TopConstituentsData,
  SectorBreakdownData,
  VehicleContributionData,
  PortfolioCharacteristics,
  ConcentrationData,
  ConcentrationCurveData,
  Metadata,
  FundListItem,
  FundSummary,
  FundDetail,
} from './types';

const DATA_DIR = path.join(process.cwd(), 'public', 'data');

function readJson<T>(filename: string): T {
  const filePath = path.join(DATA_DIR, filename);
  const raw = fs.readFileSync(filePath, 'utf-8');
  return JSON.parse(raw) as T;
}

export function getIndexReturns(): IndexReturnsData {
  return readJson<IndexReturnsData>('index_returns.json');
}

export function getIndexSummary(): IndexSummary[] {
  return readJson<IndexSummary[]>('index_summary.json');
}

export function getTopConstituents(): TopConstituentsData {
  return readJson<TopConstituentsData>('top_constituents.json');
}

export function getSectorBreakdown(): SectorBreakdownData {
  return readJson<SectorBreakdownData>('sector_breakdown.json');
}

export function getVehicleContribution(): VehicleContributionData {
  return readJson<VehicleContributionData>('vehicle_contribution.json');
}

export function getPortfolioCharacteristics(): PortfolioCharacteristics {
  return readJson<PortfolioCharacteristics>('portfolio_characteristics.json');
}

export function getManagerConcentration(): ConcentrationData {
  return readJson<ConcentrationData>('manager_concentration.json');
}

export function getVehicleConcentration(): ConcentrationData {
  return readJson<ConcentrationData>('vehicle_concentration.json');
}

export function getInvesteeConcentration(): ConcentrationData {
  return readJson<ConcentrationData>('investee_concentration.json');
}

export function getPositionConcentration(): ConcentrationData {
  return readJson<ConcentrationData>('position_concentration.json');
}

export function getConcentrationCurve(): ConcentrationCurveData {
  return readJson<ConcentrationCurveData>('concentration_curve.json');
}

export function getMetadata(): Metadata {
  return readJson<Metadata>('metadata.json');
}

export function getFundList(): FundListItem[] {
  const filePath = path.join(DATA_DIR, 'fund_list.json');
  if (!fs.existsSync(filePath)) return [];
  return readJson<FundListItem[]>('fund_list.json');
}

export function getFundSummary(): FundSummary {
  const filePath = path.join(DATA_DIR, 'fund_summary.json');
  if (!fs.existsSync(filePath)) {
    return {
      totalFunds: 0, bdcCount: 0, intervalFundCount: 0, tenderOfferCount: 0,
      totalAum: null, avgLeverageRatio: null, avgExpenseRatioPct: null,
      fundsWithReturns: 0, fundsWithDistributions: 0, totalQuarters: 0,
    };
  }
  return readJson<FundSummary>('fund_summary.json');
}

export function getFundDetail(cik: string): FundDetail | null {
  const filePath = path.join(DATA_DIR, 'fund_details', `${cik}.json`);
  if (!fs.existsSync(filePath)) return null;
  const raw = fs.readFileSync(filePath, 'utf-8');
  return JSON.parse(raw) as FundDetail;
}

export function getFundDetailCiks(): string[] {
  const dir = path.join(DATA_DIR, 'fund_details');
  if (!fs.existsSync(dir)) return [];
  return fs.readdirSync(dir)
    .filter((f) => f.endsWith('.json'))
    .map((f) => f.replace('.json', ''));
}

/** Merge concentration rows across indices, re-ranking top 10 + Other. */
export function combineConcentration(
  data: ConcentrationData,
  indices: string[],
): import('./types').ConcentrationRow[] {
  // Aggregate by name across requested indices
  const byName = new Map<string, { totalFv: number; positionCount: number; fundCount: number }>();
  for (const idx of indices) {
    for (const row of data[idx] ?? []) {
      const existing = byName.get(row.name);
      if (existing) {
        existing.totalFv += row.totalFv;
        existing.positionCount += row.positionCount;
        existing.fundCount = Math.max(existing.fundCount, row.fundCount ?? 0);
      } else {
        byName.set(row.name, {
          totalFv: row.totalFv,
          positionCount: row.positionCount,
          fundCount: row.fundCount ?? 0,
        });
      }
    }
  }

  // Pull out any pre-existing "Other" bucket from source data so it doesn't
  // compete for a top-10 slot — it will be merged into the final "Other".
  const otherEntry = byName.get('Other');
  byName.delete('Other');

  const sorted = [...byName.entries()]
    .sort((a, b) => b[1].totalFv - a[1].totalFv);

  const totalFv = sorted.reduce((s, [, v]) => s + v.totalFv, 0)
    + (otherEntry?.totalFv ?? 0);
  const top10 = sorted.slice(0, 10);
  const rest = sorted.slice(10);

  const rows: import('./types').ConcentrationRow[] = top10.map(([name, v]) => ({
    name,
    totalFv: v.totalFv,
    pctOfIndex: totalFv > 0 ? v.totalFv / totalFv : 0,
    positionCount: v.positionCount,
    fundCount: v.fundCount,
  }));

  // Combine leftover named entries + the pre-existing "Other" bucket
  let otherFv = rest.reduce((s, [, v]) => s + v.totalFv, 0);
  let otherPos = rest.reduce((s, [, v]) => s + v.positionCount, 0);
  if (otherEntry) {
    otherFv += otherEntry.totalFv;
    otherPos += otherEntry.positionCount;
  }
  if (otherFv > 0) {
    rows.push({
      name: 'Other',
      totalFv: otherFv,
      pctOfIndex: totalFv > 0 ? otherFv / totalFv : 0,
      positionCount: otherPos,
    });
  }

  return rows;
}
