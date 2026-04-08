/** Shape of index_returns.json — keyed by index classification */
export interface IndexReturnRow {
  quarter: string;
  fvReturn: number | null;
  eqReturn: number | null;
  costReturn: number | null;
  constituents: number | null;
  totalBeginFv: number | null;
  totalEndFv: number | null;
  levelFv: number | null;
  levelEqual: number | null;
  levelCost: number | null;
}
export type IndexReturnsData = Record<string, IndexReturnRow[]>;

/** Shape of index_summary.json — array of per-index summaries */
export interface IndexSummary {
  index: string;
  level: number | null;
  levelEqual: number | null;
  qoqReturn: number | null;
  trailing12m: number | null;
  ytd: number | null;
  annualized: number | null;
  constituents: number | null;
  totalFv: number | null;
  latestQuarter: string;
  sparkline: number[];
}

/** Shape of top_constituents.json — keyed by index classification */
export interface TopConstituent {
  issuerName: string;
  assetCategory: string;
  fairValue: number | null;
  cost: number | null;
  unrealizedGlPct: number | null;
  vehicleName: string;
  totalReturn: number | null;
  rateType: string | null;
}
export type TopConstituentsData = Record<string, TopConstituent[]>;

/** Shape of sector_breakdown.json — keyed by index classification */
export interface SectorRow {
  assetCategory: string;
  positionCount: number;
  totalFv: number;
  pctOfIndex: number;
}
export type SectorBreakdownData = Record<string, SectorRow[]>;

/** Shape of vehicle_contribution.json — keyed by index classification */
export interface VehicleRow {
  cik: string | number;
  entityName: string;
  vehicleType: string;
  positionCount: number;
  totalFv: number;
  pctOfIndex: number;
}
export type VehicleContributionData = Record<string, VehicleRow[]>;

/** Shape of portfolio_characteristics.json */
export interface PortfolioCharacteristics {
  asOf: string;
  positionCount: number;
  totalFv: number;
  wac: number | null;
  was: number | null;
  wam: number | null;
  wacCoverage?: number | null;
  wasCoverage?: number | null;
  wamCoverage?: number | null;
  lienSplit: {
    firstLien: number;
    secondLien: number;
    unsecured: number;
  };
  rateTypeSplit: {
    floating: number;
    fixed: number;
  };
}

/** Shape of metadata.json */
export interface Metadata {
  asOfQuarter: string | null;
  asOfDate: string | null;
  totalAum: number;
  vehicleCount: number;
  bdcCount: number;
  intervalFundCount: number;
  tenderOfferCount: number;
  holdingsCount: number;
  cikCount: number;
  dataVintage: string;
}
