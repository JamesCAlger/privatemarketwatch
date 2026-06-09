const VEHICLE_CONFIG: Record<string, { label: string; bg: string; text: string }> = {
  bdc: { label: 'Unlisted BDC', bg: 'bg-teal/10', text: 'text-teal' },
  non_traded: { label: 'Non-Traded', bg: 'bg-navy', text: 'text-white' },
  interval_fund: { label: 'Interval', bg: 'bg-amber-50', text: 'text-amber-700' },
  tender_offer_fund: { label: 'Tender Offer', bg: 'bg-violet-50', text: 'text-violet-700' },
};

interface VehicleTypeBadgeProps {
  vehicleType: string;
  size?: 'sm' | 'md';
}

export default function VehicleTypeBadge({ vehicleType, size = 'sm' }: VehicleTypeBadgeProps) {
  const config = VEHICLE_CONFIG[vehicleType] ?? {
    label: vehicleType || 'Unknown',
    bg: 'bg-surface',
    text: 'text-muted',
  };

  const sizeClasses = size === 'md'
    ? 'text-xs px-2.5 py-1'
    : 'text-[11px] px-2 py-0.5';

  return (
    <span className={`inline-block font-medium whitespace-nowrap ${config.bg} ${config.text} ${sizeClasses}`}>
      {config.label}
    </span>
  );
}
