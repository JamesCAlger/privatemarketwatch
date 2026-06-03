export const SITE_NAME = 'Metris Lens';
export const SITE_DESCRIPTION =
  'The data platform for private markets. Fund data, portfolio analytics, and position-level indices for private credit and equity -- built from mandatory SEC filings.';

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
    name: 'Direct Lending Total Return Index',
    shortName: 'Direct Lending',
    slug: 'direct-lending',
    color: '#2A9D8F',
    tailwindColor: 'text-teal',
    description:
      'The largest publicly available benchmark of middle-market direct loans, built from holdings-level filings across registered closed-end vehicles.',
    category: 'PMW INDEX \u00b7 PRIVATE CREDIT BENCHMARKS',
    inceptionDate: 'January 1, 2019',
    inceptionQuarter: '2019q1',
    returnTypes: 'Gross & Net',
    baseLevel: 100,
  },
  {
    key: 'PREFERRED_EQUITY',
    name: 'Preferred Equity Total Return Index',
    shortName: 'Preferred Equity',
    slug: 'preferred-equity',
    color: '#E76F51',
    tailwindColor: 'text-orange-500',
    description:
      'Preferred equity positions in private companies \u2014 stated dividend rates, redemption optionality, and a seniority structure that sits between debt and common stock.',
    category: 'PMW INDEX \u00b7 PRIVATE CREDIT BENCHMARKS',
    inceptionDate: 'January 1, 2019',
    inceptionQuarter: '2019q1',
    returnTypes: 'Gross & Net',
    baseLevel: 100,
  },
  {
    key: 'COMMON_EQUITY',
    name: 'Common Equity Price Return Index',
    shortName: 'Common Equity',
    slug: 'common-equity',
    color: '#0F1B2D',
    tailwindColor: 'text-blue-500',
    description:
      'Direct common equity co-investments and minority stakes in private companies, held by registered closed-end vehicles \u2014 sponsor-backed and held to exit.',
    category: 'PMW INDEX \u00b7 PRIVATE CREDIT BENCHMARKS',
    inceptionDate: 'January 1, 2019',
    inceptionQuarter: '2019q1',
    returnTypes: 'Gross & Net',
    baseLevel: 100,
  },
  // Private Credit Fund and Private Equity Fund indices hidden for now
  // (fund-of-fund allocations include leverage effects)
];

export function getIndexBySlug(slug: string): IndexMeta | undefined {
  return INDICES.find((i) => i.slug === slug);
}

export function getIndexByKey(key: string): IndexMeta | undefined {
  return INDICES.find((i) => i.key === key);
}
