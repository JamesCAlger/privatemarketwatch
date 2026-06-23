import { MetadataRoute } from 'next';
import { INDICES } from '@/lib/constants';
import { getFundDetailCiks } from '@/lib/data';

export default function sitemap(): MetadataRoute.Sitemap {
  const base = 'https://www.metrislens.com';

  const fundCiks = getFundDetailCiks();

  return [
    { url: base, lastModified: new Date(), changeFrequency: 'monthly', priority: 1 },
    ...INDICES.map((idx) => ({
      url: `${base}/indices/${idx.slug}`,
      lastModified: new Date(),
      changeFrequency: 'monthly' as const,
      priority: 0.9,
    })),
    ...fundCiks.map((cik) => ({
      url: `${base}/funds/${cik}`,
      lastModified: new Date(),
      changeFrequency: 'monthly' as const,
      priority: 0.6,
    })),
    { url: `${base}/methodology`, lastModified: new Date(), changeFrequency: 'monthly', priority: 0.7 },
    { url: `${base}/about`, lastModified: new Date(), changeFrequency: 'yearly', priority: 0.5 },
    { url: `${base}/privacy`, lastModified: new Date(), changeFrequency: 'yearly', priority: 0.3 },
    { url: `${base}/terms`, lastModified: new Date(), changeFrequency: 'yearly', priority: 0.3 },
  ];
}
