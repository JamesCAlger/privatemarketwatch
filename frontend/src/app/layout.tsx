import type { Metadata } from 'next';
import { Libre_Franklin } from 'next/font/google';
import Header from '@/components/Header';
import Footer from '@/components/Footer';
import './globals.css';

const libre = Libre_Franklin({ subsets: ['latin'], display: 'swap' });

export const metadata: Metadata = {
  title: {
    default: 'Private Market Watch',
    template: '%s | Private Market Watch',
  },
  description:
    'Independent, rules-based benchmarks for private credit and equity markets -- built from mandatory SEC filings across 587 registered funds.',
  metadataBase: new URL('https://privatemarketwatch.com'),
  openGraph: {
    title: 'Private Market Watch',
    description:
      'Independent benchmarks tracking private credit and equity performance from SEC filings.',
    url: 'https://privatemarketwatch.com',
    siteName: 'Private Market Watch',
    type: 'website',
  },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className={`${libre.className} min-h-screen flex flex-col bg-page`}>
        <Header />
        <main className="flex-1">{children}</main>
        <Footer />
      </body>
    </html>
  );
}
