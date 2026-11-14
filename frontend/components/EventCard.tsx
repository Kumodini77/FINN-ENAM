import Link from "next/link";
import type { EventItem, FinancialChange } from "@/types/api";
import { CategoryBadge, PriorityBadge } from "./Badges";

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });
}

const DIRECTION_STYLES: Record<string, string> = {
  positive: "text-[var(--color-positive)]",
  negative: "text-[var(--color-negative)]",
  not_available: "text-[var(--color-ink-faint)]",
  not_comparable: "text-[var(--color-ink-faint)]",
};

function ChangeRow({ change }: { change: FinancialChange }) {
  const pct = change.yoy_pct ?? change.qoq_pct;
  const basisLabel = change.yoy_pct != null ? "YoY" : change.qoq_pct != null ? "QoQ" : null;
  return (
    <div className="flex items-center justify-between border-b border-[var(--color-border)] py-1.5 text-[13px] last:border-0">
      <span className="text-[var(--color-ink-muted)]">{change.label}</span>
      <div className="flex items-center gap-2 tabular">
        <span className="text-[var(--color-ink)]">
          {change.latest_value != null ? `${change.latest_value} ${change.unit}` : "Not available"}
        </span>
        {pct != null && basisLabel ? (
          <span className={`font-medium ${DIRECTION_STYLES[change.direction]}`}>
            {pct > 0 ? "+" : ""}
            {pct.toFixed(1)}% {basisLabel}
          </span>
        ) : (
          <span className="text-[11px] text-[var(--color-ink-faint)]">not comparable yet</span>
        )}
      </div>
    </div>
  );
}

export function EventCard({ event }: { event: EventItem }) {
  const researchHref = `/research?ticker=${encodeURIComponent(event.research_link.ticker)}&question=${encodeURIComponent(
    event.research_link.suggested_question
  )}`;

  return (
    <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-4">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[13px] font-semibold text-[var(--color-ink)]">{event.company_ticker}</span>
        <PriorityBadge priority={event.priority} />
        <CategoryBadge category={event.event_category} />
        {event.reporting_period && (
          <span className="text-[11px] text-[var(--color-ink-faint)]">{event.reporting_period}</span>
        )}
        <span className="text-[11px] text-[var(--color-ink-faint)]">{formatDate(event.event_date)}</span>
      </div>

      <p className="mt-2 text-[13px] leading-snug text-[var(--color-ink-muted)]">
        <span className="font-medium text-[var(--color-accent)]">Why it matters: </span>
        {event.why_it_matters}
      </p>

      {event.financial_changes.length > 0 && (
        <div className="mt-3 rounded-lg bg-[var(--color-canvas)] px-3 py-1">
          {event.financial_changes.map((c) => (
            <ChangeRow key={c.metric} change={c} />
          ))}
        </div>
      )}

      {event.basis_mismatch_warnings.length > 0 && (
        <p className="mt-2 text-[11px] text-amber-700">⚠ {event.basis_mismatch_warnings.join("; ")}</p>
      )}
      {event.missing_information.length > 0 && (
        <p className="mt-2 text-[11px] text-[var(--color-ink-faint)]">{event.missing_information.join(" ")}</p>
      )}

      <details className="mt-3">
        <summary className="cursor-pointer text-[12px] font-medium text-[var(--color-ink-muted)]">
          {event.source_documents.length} source document{event.source_documents.length === 1 ? "" : "s"}
        </summary>
        <div className="mt-2 space-y-1.5">
          {event.source_documents.map((doc) => (
            <div key={doc.announcement_id} className="flex items-center justify-between text-[12px]">
              <span className="truncate pr-2 text-[var(--color-ink-muted)]">{doc.title}</span>
              <a
                href={doc.document_url ?? doc.original_source_url}
                target="_blank"
                rel="noreferrer"
                className="shrink-0 font-medium text-[var(--color-accent)] hover:underline"
              >
                View ↗
              </a>
            </div>
          ))}
        </div>
      </details>

      <Link
        href={researchHref}
        className="mt-3 inline-flex items-center gap-1 rounded-lg bg-[var(--color-accent-soft)] px-3 py-1.5 text-[12px] font-medium text-[var(--color-accent)] hover:opacity-80"
      >
        Research this event →
      </Link>
    </div>
  );
}
