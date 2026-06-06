export const SITE_NAME = 'Metris Lens';
export const SITE_DESCRIPTION =
  'The index platform for private credit. Fund data, portfolio analytics, and position-level indices for unlisted BDCs -- built from mandatory SEC filings.';

export interface IndexMeta {
  key: string;
  name: string;
  shortName: string;
  slug: string;
  color: string;       // hex
  tailwindColor: string;
  description: string;
  category: string;
  inceptionDate: string;
  inceptionQuarter: string;
  returnTypes: string;
  baseLevel: number;
}

export const INDICES: IndexMeta[] = [
  {
    key: 'DIRECT_LENDING',
    name: 'Private Credit Total Return Index',
    shortName: 'Private Credit',
    slug: 'private-credit',
    color: '#2A9D8F',
    tailwindColor: 'text-teal',
    description:
      'The largest publicly available benchmark of middle-market direct loans, built from holdings-level filings across unlisted BDCs.',
    category: 'METRIS LENS \u00b7 PRIVATE CREDIT BENCHMARKS',
    inceptionDate: 'January 1, 2019',
    inceptionQuarter: '2019q1',
    returnTypes: 'Gross & Net',
    baseLevel: 100,
  },
  {
    key: 'COMMON_EQUITY',
    name: 'Private Equity NAV Return Index',
    shortName: 'Private Equity',
    slug: 'private-equity',
    color: '#0F1B2D',
    tailwindColor: 'text-blue-500',
    description:
      'Direct common equity co-investments and minority stakes in private companies, held by unlisted BDCs \u2014 sponsor-backed and held to exit.',
    category: 'METRIS LENS \u00b7 PRIVATE CREDIT BENCHMARKS',
    inceptionDate: 'January 1, 2019',
    inceptionQuarter: '2019q1',
    returnTypes: 'Gross & Net',
    baseLevel: 100,
  },
];

export function getIndexBySlug(slug: string): IndexMeta | undefined {
  return INDICES.find((i) => i.slug === slug);
}

export function getIndexByKey(key: string): IndexMeta | undefined {
  return INDICES.find((i) => i.key === key);
}
