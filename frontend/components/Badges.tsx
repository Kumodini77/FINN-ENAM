import type { AnnouncementCategory, PriorityLevel } from "@/types/api";

const PRIORITY_STYLES: Record<PriorityLevel, string> = {
  high: "bg-[var(--color-negative)]/10 text-[var(--color-negative)]",
  medium: "bg-amber-500/10 text-amber-700",
  low: "bg-[var(--color-border)] text-[var(--color-ink-muted)]",
};

export function PriorityBadge({ priority }: { priority: PriorityLevel }) {
  return (
    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide ${PRIORITY_STYLES[priority]}`}>
      {priority}
    </span>
  );
}

const CATEGORY_LABELS: Record<AnnouncementCategory, string> = {
  results: "Results",
  "M&A": "M&A",
  fund_raise: "Fund Raise",
  management_change: "Management Change",
  litigation: "Litigation",
  insider_trading: "Insider Trading",
  earnings_call: "Earnings Call",
  investor_meetings: "Investor Meeting",
  credit_rating: "Credit Rating",
  dividend: "Dividend",
  bonus_split: "Bonus / Split",
  capex: "Capex",
  press_release: "Press Release",
  postal_ballot: "Postal Ballot",
  agm_egm: "AGM / EGM",
  pledging: "Pledging",
  unclassified: "Unclassified",
};

export function categoryLabel(category: AnnouncementCategory): string {
  return CATEGORY_LABELS[category] ?? category;
}

export function CategoryBadge({ category }: { category: AnnouncementCategory }) {
  return (
    <span className="inline-flex items-center rounded-full bg-[var(--color-accent-soft)] px-2 py-0.5 text-[11px] font-medium text-[var(--color-accent)]">
      {categoryLabel(category)}
    </span>
  );
}
