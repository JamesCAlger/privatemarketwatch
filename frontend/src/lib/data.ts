import fs from 'fs';
import path from 'path';
import type {
  IndexReturnsData,
  IndexSummary,
  TopConstituentsData,
  SectorBreakdownData,
  VehicleContributionData,
  PortfolioCharacteristics,
  Metadata,
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

export function getMetadata(): Metadata {
  return readJson<Metadata>('metadata.json');
}
