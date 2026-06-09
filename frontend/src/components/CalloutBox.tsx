import type { ReactNode } from 'react';

const VARIANT_STYLES = {
  design: {
    border: 'border-accent',
    bg: 'bg-accent/5',
    text: 'text-navy/80',
  },
  'edge-case': {
    border: 'border-ink',
    bg: 'bg-surface/50',
    text: 'text-navy/80',
  },
  limitation: {
    border: 'border-amber-400',
    bg: 'bg-amber-50',
    text: 'text-navy/80',
  },
};

interface CalloutBoxProps {
  variant: 'design' | 'edge-case' | 'limitation';
  title?: string;
  children: ReactNode;
}

export default function CalloutBox({ variant, title, children }: CalloutBoxProps) {
  const styles = VARIANT_STYLES[variant];

  return (
    <div
      className={`border-l-[3px] ${styles.border} ${styles.bg} px-4 py-3 my-4 text-sm ${styles.text}`}
    >
      {title && (
        <p className="font-semibold text-navy mb-1">{title}</p>
      )}
      {children}
    </div>
  );
}
