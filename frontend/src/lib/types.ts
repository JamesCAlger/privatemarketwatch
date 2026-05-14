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
  uniqueCompanies: number | null;
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

/** Shared shape for concentration charts (manager, vehicle, investee) */
export interface ConcentrationRow {
  name: string;
  totalFv: number;
  pctOfIndex: number;
  positionCount: number;
  fundCount?: number;
}
export type ConcentrationData = Record<string, ConcentrationRow[]>;

/** Shape of concentration_curve.json — pie-chart-ready brackets */
export interface ConcentrationBracket {
  label: string;
  fvPct: number;
  count: number;
  totalCount: number;
}
export interface ConcentrationCurveEntry {
  investee?: ConcentrationBracket[];
  position?: ConcentrationBracket[];
}
export type ConcentrationCurveData = Record<string, ConcentrationCurveEntry>;

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
  uniqueIssuers: number;
  dataVintage: string;
}

/** Fund list item from fund_list.json */
export interface FundListItem {
  cik: string;
  name: string;
  vehicleType: string;
  adviser: string | null;
  ticker: string | null;
  totalAssets: number | null;
  navPerShare: number | null;
  distributionRate: number | null;
  leverageRatio: number | null;
  quarterlyReturn: number | null;
  expenseRatioPct: number | null;
  redemptionPressure: number | null;
  totalReturnPct: number | null;
  incomeYieldPct: number | null;
  premiumDiscountPct: number | null;
  quartersOfData: number | null;
}

/** Fund summary from fund_summary.json */
export interface FundSummary {
  totalFunds: number;
  bdcCount: number;
  intervalFundCount: number;
  tenderOfferCount: number;
  totalAum: number | null;
  avgLeverageRatio: number | null;
  avgExpenseRatioPct: number | null;
  fundsWithReturns: number;
  fundsWithDistributions: number;
  totalQuarters: number;
}

/** Fund exposure breakdown */
export interface FundExposure {
  totalFv: number;
  positionCount: number;
  assetSplit: {
    debt: number | null;
    equity: number | null;
    fund: number | null;
    structured: number | null;
    cash: number | null;
    other: number | null;
  };
  assetClassSplit?: {
    privateCredit: number | null;
    privateEquity: number | null;
    realEstate: number | null;
    structuredCredit: number | null;
    hedgeFund: number | null;
    cash: number | null;
    other: number | null;
  };
  exposureTypeSplit?: {
    direct: number | null;
    fund: number | null;
    liquid: number | null;
  };
  lienSplit: {
    firstLien: number | null;
    secondLien: number | null;
    unsecured: number | null;
    coverage: number | null;
  };
  rateTypeSplit: {
    floating: number | null;
    fixed: number | null;
  };
  wac: number | null;
  wacCoverage?: number | null;
  was: number | null;
  wam?: number | null;
  wamCoverage?: number | null;
  maturityBuckets?: { label: string; pct: number }[];
  unrealizedGl?: {
    aggregatePct: number | null;
    pctUnderwater: number | null;
    coverage: number | null;
  };
  concentration?: {
    top10Pct: number | null;
  };
  pikExposure?: {
    pctOfDebtFv: number | null;
    label: string;
  };
  fvHierarchy?: {
    level1: number | null;
    level2: number | null;
    level3: number | null;
    coverage: number | null;
  } | null;
  creditFlags?: {
    pctInDefault: number | null;
    pctInArrears: number | null;
    coverage: number | null;
  } | null;
}

/** Fund top holding */
export interface FundHolding {
  issuerName: string;
  fairValue: number | null;
  pctOfPortfolio: number | null;
  assetCategory: string | null;
  interestRate: number | null;
  maturityDate: string | null;
  lienPosition: string | null;
}

/** Single quarter in fund time series */
export interface FundSeriesEntry {
  quarter: string;
  reportDate: string;
  source: string;
  total_assets?: number | null;
  net_assets?: number | null;
  nav_per_share?: number | null;
  leverage_ratio?: number | null;
  quarterly_return?: number | null;
  distribution_rate?: number | null;
  distribution_per_share?: number | null;
  expense_ratio_pct?: number | null;
  total_return_pct?: number | null;
  income_yield_pct?: number | null;
  asset_coverage_ratio?: number | null;
  unfunded_commitments?: number | null;
  redemption_pressure?: number | null;
  premium_discount_pct?: number | null;
  gross_return_pct?: number | null;
  [key: string]: string | number | null | undefined;
}

/** Data quality dashboard */
export interface GavHistogramBucket {
  bucket: string;
  count: number;
}
export interface GavReconciliation {
  histogram: GavHistogramBucket[];
  totalCikQuarters: number;
  median: number;
  within95_105Pct: number;
  within80_120Pct: number;
}
export interface ClassificationRule {
  rule: string;
  description: string;
  totalRows: number;
  disagreements: number;
  pct: number;
}
export interface FieldFillRate {
  field: string;
  fillPct: number;
}
export interface ValidationTierCount {
  tier: string;
  count: number;
}
export interface IssueSeverityCount {
  severity: string;
  count: number;
}
export interface IssueEvidenceCount {
  evidenceStrength: string;
  count: number;
}
export interface TopIssueColumn {
  column: string;
  severity: string;
  count: number;
}
export interface ColumnQualityMetric {
  column: string;
  totalRows: number;
  fillRate: number | null;
  parseRate: number | null;
  validRate: number | null;
  failCount: number;
  warnCount: number;
}
export interface QuarterHoldings {
  quarter: string;
  bdc: number;
  nport: number;
  totalFv: number;
  cikCount: number;
}
export interface ClassificationRow {
  classification: string;
  rows: number;
  fv: number;
  fvPct: number;
}
export interface ThirdPartyValidation {
  source: string;
  total: number;
  missed: number;
  matchPct: number;
}
export interface PipelineSummary {
  totalHoldings: number;
  totalCiks: number;
  earliestDate: string;
  latestDate: string;
  bdcRows: number;
  nportRows: number;
  unclassifiedPct: number;
}
export interface ReconciliationHistogram {
  id: string;
  title: string;
  subtitle: string;
  n: number;
  median: number | null;
  centerValue: number;
  histogram: GavHistogramBucket[];
}
export interface LlmFundValidationMetric {
  label: string;
  precision: number;
  recall: number;
  f1: number;
  support: number;
}
export interface LlmFundValidation {
  overallAccuracy: number;
  totalSamples: number;
  labels: string[];
  confusionMatrix: number[][];
  perClassMetrics: LlmFundValidationMetric[];
}
export interface DataQuality {
  gavReconciliation?: GavReconciliation;
  classificationRules?: ClassificationRule[];
  fieldFillRates?: FieldFillRate[];
  holdingsByQuarter?: QuarterHoldings[];
  classificationBreakdown?: ClassificationRow[];
  pipelineSummary?: PipelineSummary;
  validationTierCounts?: ValidationTierCount[];
  issueSeverityCounts?: IssueSeverityCount[];
  issueEvidenceCounts?: IssueEvidenceCount[];
  topIssueColumns?: TopIssueColumn[];
  columnQualityMetrics?: ColumnQualityMetric[];
  thirdPartyValidation?: ThirdPartyValidation[];
  reconciliationHistograms?: ReconciliationHistogram[];
  llmFundValidation?: LlmFundValidation;
}

/** Fund-level index return row from fund_index_returns.json */
export interface FundIndexReturnRow {
  quarter: string;
  return: number;
  level: number;
  fundCount: number;
  totalAum: number;
}
export type FundIndexReturnsData = Record<string, FundIndexReturnRow[]>;

/** AUM time series row from aum_time_series.json */
export interface AumTimeSeriesRow {
  quarter: string;
  bdc: number;
  intervalFund: number;
  tenderOffer: number;
  total: number;
  bdcCount: number;
  intervalCount: number;
  tenderCount: number;
}

/** GICS sector row from gics_sector_breakdown.json */
export interface GicsSectorRow {
  sector: string;
  totalFv: number;
  pctOfTotal: number;
  fundCount: number | null;
}

/** Credit risk tier values (fractions summing to 1.0) */
export interface CreditRiskTiers {
  deepDistress: number;
  nonAccrual: number;
  pikActive: number;
  healthy: number;
}

/** Credit risk row from credit_risk.json */
export interface CreditRiskRow {
  quarter: string;
  byCount: CreditRiskTiers;
  byFv: CreditRiskTiers;
  totalPositions: number;
  totalFv: number;
}

/** Histogram bucket for distribution/leverage histograms */
export interface HistogramBucket {
  bucket: string;
  bdc: number;
  nonBdc: number;
  total: number;
}

/** Histogram data from distribution_histogram.json / leverage_histogram.json */
export interface HistogramData {
  median: number;
  total: number;
  buckets: HistogramBucket[];
}

/** Full fund detail from fund_details/{cik}.json */
export interface FundDetail {
  cik: string;
  name: string;
  vehicleType: string;
  adviser: string;
  ticker: string;
  series: FundSeriesEntry[];
  exposure: FundExposure | null;
  topHoldings: FundHolding[] | null;
}
