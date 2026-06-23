import type { Metadata } from 'next';
import { IBM_Plex_Serif, IBM_Plex_Sans, IBM_Plex_Mono } from 'next/font/google';
import Header from '@/components/Header';
import Footer from '@/components/Footer';
import { getIndexSummary, getFundList } from '@/lib/data';
import './globals.css';

const plexSerif = IBM_Plex_Serif({
  subsets: ['latin'],
  weight: ['400', '500', '600', '700'],
  display: 'swap',
  variable: '--font-display',
});

const plexSans = IBM_Plex_Sans({
  subsets: ['latin'],
  weight: ['400', '500', '600', '700'],
  display: 'swap',
  variable: '--font-body',
});

const plexMono = IBM_Plex_Mono({
  subsets: ['latin'],
  weight: ['400', '500', '600'],
  display: 'swap',
  variable: '--font-mono',
});

export const metadata: Metadata = {
  title: {
    default: 'Metris Lens',
    template: '%s | Metris Lens',
  },
  description:
    'The data platform for private markets. Fund data, portfolio analytics, and position-level indices for private credit and equity -- built from mandatory SEC filings.',
  metadataBase: new URL('https://www.metrislens.com'),
  openGraph: {
    title: 'Metris Lens',
    description:
      'Fund data, portfolio analytics, and indices for private credit and equity markets from SEC filings.',
    url: 'https://www.metrislens.com',
    siteName: 'Metris Lens',
    type: 'website',
  },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const indexSummaries = getIndexSummary();
  const fundList = getFundList();
  const fundCount = fundList.length;
  const fundSearchItems = fundList.map((f) => ({
    cik: f.cik,
    name: f.name,
    ticker: f.ticker,
    adviser: f.adviser,
  }));
  return (
    <html lang="en" className={`${plexSerif.variable} ${plexSans.variable} ${plexMono.variable} bg-bg`}>
      <body className="font-body min-h-screen flex flex-col bg-bg text-ink">
        <Header indexSummaries={indexSummaries} fundCount={fundCount} fundSearchItems={fundSearchItems} />
        <main className="flex-1">{children}</main>
        <Footer />
      </body>
    </html>
  );
}
