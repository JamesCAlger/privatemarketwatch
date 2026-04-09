import { MetadataRoute } from 'next';
import { INDICES } from '@/lib/constants';

export default function sitemap(): MetadataRoute.Sitemap {
  const base = 'https://privatemarketwatch.com';

  return [
    { url: base, lastModified: new Date(), changeFrequency: 'monthly', priority: 1 },
    ...INDICES.map((idx) => ({
      url: `${base}/indices/${idx.slug}`,
      lastModified: new Date(),
      changeFrequency: 'monthly' as const,
      priority: 0.9,
    })),
    { url: `${base}/methodology`, lastModified: new Date(), changeFrequency: 'monthly', priority: 0.7 },
    { url: `${base}/about`, lastModified: new Date(), changeFrequency: 'yearly', priority: 0.5 },
  ];
}
