import Link from 'next/link';

interface BreadcrumbItem {
  label: string;
  href?: string;
}

export default function Breadcrumb({ items }: { items: BreadcrumbItem[] }) {
  return (
    <div className="px-4 md:px-[72px] pt-5 text-xs tracking-[0.02em] text-ink2">
      {items.map((item, i) => (
        <span key={i}>
          {i > 0 && <span className="text-ink4 mx-2">&rsaquo;</span>}
          {item.href ? (
            <Link href={item.href} className="text-ink2 hover:text-ink transition-colors">
              {item.label}
            </Link>
          ) : (
            <span className="text-ink">{item.label}</span>
          )}
        </span>
      ))}
    </div>
  );
}
