export const SITE_NAME = 'Private Market Watch';
export const SITE_DESCRIPTION =
  'Data and indices for the evergreen fund universe -- BDCs, interval funds, and tender offer funds -- the registered vehicles bringing private markets to wealth management.';

export interface IndexMeta {
  key: string;
  name: string;
  shortName: string;
  slug: string;
  color: string;       // hex
  tailwindColor: string;
  description: string;
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
      'The largest publicly available benchmark of middle-market direct loans.',
  },
  {
    key: 'PREFERRED_EQUITY',
    name: 'Preferred Equity Total Return Index',
    shortName: 'Preferred Equity',
    slug: 'preferred-equity',
    color: '#E76F51',
    tailwindColor: 'text-orange-500',
    description:
      'Preferred equity positions in private companies with stated dividend rates, held by registered closed-end vehicles.',
  },
  {
    key: 'COMMON_EQUITY',
    name: 'Common Equity Price Return Index',
    shortName: 'Common Equity',
    slug: 'common-equity',
    color: '#0F1B2D',
    tailwindColor: 'text-blue-500',
    description:
      'Direct common equity co-investments and minority stakes in private companies, held by registered closed-end vehicles.',
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
