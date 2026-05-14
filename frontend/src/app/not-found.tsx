import Link from 'next/link';

export default function NotFound() {
  return (
    <div className="mx-auto max-w-6xl px-4 sm:px-6 py-24 text-center">
      <h1 className="text-4xl font-bold text-navy mb-4">404</h1>
      <p className="text-muted mb-8">Page not found.</p>
      <Link
        href="/"
        className="inline-block px-4 py-2 bg-teal text-white hover:bg-teal-light transition-colors"
      >
        Back to Home
      </Link>
    </div>
  );
}
