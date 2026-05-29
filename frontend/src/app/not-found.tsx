import Link from 'next/link';

export default function NotFound() {
  return (
    <div className="mx-auto max-w-6xl px-4 sm:px-6 py-24 text-center">
      <h1 className="font-display text-4xl font-bold text-ink mb-4">404</h1>
      <p className="text-ink3 mb-8">Page not found.</p>
      <Link
        href="/"
        className="inline-block px-4 py-2 border border-accent text-accent hover:bg-accent hover:text-navy transition-colors text-sm tracking-[0.04em]"
      >
        Back to Home
      </Link>
    </div>
  );
}
