'use client';

interface TabDef {
  id: string;
  label: string;
  count?: number;
}

interface FundTabBarProps {
  tabs: TabDef[];
  active: string;
  onChange: (id: string) => void;
}

export default function FundTabBar({ tabs, active, onChange }: FundTabBarProps) {
  return (
    <div className="border-b border-rule">
      <div className="flex gap-0 overflow-x-auto">
        {tabs.map((tab) => {
          const isActive = tab.id === active;
          return (
            <button
              key={tab.id}
              onClick={() => onChange(tab.id)}
              className={`relative px-5 py-3 text-sm font-medium transition-colors whitespace-nowrap ${
                isActive
                  ? 'text-navy'
                  : 'text-ink3 hover:text-ink2'
              }`}
            >
              {tab.label}
              {tab.count != null && (
                <span className="ml-1.5 text-[10px] text-ink3 tabular-nums">
                  ({tab.count})
                </span>
              )}
              {isActive && (
                <span className="absolute bottom-0 left-0 right-0 h-[2px] bg-accent" />
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
}
