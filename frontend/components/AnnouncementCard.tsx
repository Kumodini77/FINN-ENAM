import type { DigestItem } from "@/types/api";
import { CategoryBadge, PriorityBadge } from "./Badges";

function formatDate(iso: string): string {
  return new Date(iso).toLocaleString("en-IN", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "Asia/Kolkata",
  });
}

export function AnnouncementCard({ item }: { item: DigestItem }) {
  return (
    <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-4">
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-[13px] font-semibold text-[var(--color-ink)]">{item.company_ticker}</span>
        <PriorityBadge priority={item.priority} />
        <CategoryBadge category={item.category} />
        {item.verification_status === "unverified" && (
          <span className="text-[11px] text-[var(--color-ink-faint)]" title="Not yet cross-checked against the original filing">
            unverified
          </span>
        )}
      </div>

      {/* The filing's own words — always rendered separately from FINN's interpretation. */}
      <p className="mt-2 text-[14px] leading-snug text-[var(--color-ink)]">{item.title}</p>

      {item.why_it_matters && (
        <p className="mt-1.5 text-[13px] leading-snug text-[var(--color-ink-muted)]">
          <span className="font-medium text-[var(--color-accent)]">Why it matters: </span>
          {item.why_it_matters}
        </p>
      )}

      <div className="mt-3 flex items-center justify-between text-[12px] text-[var(--color-ink-faint)]">
        <span>
          Filed {formatDate(item.filed_at)} IST
          {item.ingested_at !== item.filed_at && <> · ingested {formatDate(item.ingested_at)}</>}
        </span>
        <a
          href={item.document_url ?? item.original_source_url}
          target="_blank"
          rel="noopener noreferrer"
          className="font-medium text-[var(--color-accent)] hover:underline"
        >
          View filing ↗
        </a>
      </div>
    </div>
  );
}
