import Link from 'next/link';

export default function NotFound() {
  return (
    <div className="px-4 md:px-[120px] py-24 text-center">
      <p className="eyebrow text-ink3 mb-4">404</p>
      <h1 className="font-display text-[42px] tracking-[-0.02em] text-ink mb-4">
        Page not found
      </h1>
      <p className="text-ink3 text-sm mb-8 max-w-md mx-auto">
        The page you&apos;re looking for doesn&apos;t exist or has been moved.
      </p>
      <div className="flex justify-center gap-3">
        <Link
          href="/"
          className="inline-block px-5 py-2.5 bg-navy text-white text-sm font-medium hover:bg-navy/90 transition-colors"
        >
          Fund universe
        </Link>
        <Link
          href="/indices/private-credit"
          className="inline-block px-5 py-2.5 border border-rule text-ink2 text-sm font-medium hover:bg-surface/50 transition-colors"
        >
          View indices
        </Link>
      </div>
    </div>
  );
}
