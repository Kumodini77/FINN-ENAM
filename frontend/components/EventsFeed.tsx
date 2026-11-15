"use client";

import { useEffect, useState } from "react";
import { ApiError, fetchEvents, fetchMarketPulse } from "@/lib/api";
import { formatPrice } from "@/lib/format";
import type { EventItem, EventsResponse, MarketPulseResponse, PulseItem } from "@/types/api";
import { DateRangeFilter, type DateRangeSelection } from "./DateRangeFilter";
import { EventCard } from "./EventCard";
import { EmptyState } from "./EmptyState";

function hasPositiveChange(event: EventItem): boolean {
  return event.financial_changes.some((c) => c.direction === "positive");
}
function hasNegativeChange(event: EventItem): boolean {
  return event.financial_changes.some((c) => c.direction === "negative");
}

function PulseCard({ item }: { item: PulseItem }) {
  const isUp = item.direction === "positive";
  return (
    <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-3">
      <div className="flex items-center justify-between gap-2">
        <span className="text-[13px] font-semibold text-[var(--color-ink)]">{item.ticker}</span>
        <span className="rounded-full bg-[var(--color-canvas)] px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-[var(--color-ink-faint)]">
          EOD
        </span>
      </div>
      <p className="tabular mt-1 text-[13px] font-medium text-[var(--color-ink)]">{formatPrice(item.latest_close)}</p>
      <p className={`mt-0.5 text-[12px] font-medium ${isUp ? "text-[var(--color-positive)]" : "text-[var(--color-negative)]"}`}>{item.note}</p>
      <p className="mt-1 text-[10px] text-[var(--color-ink-faint)]">as of {item.observation_date}</p>
    </div>
  );
}

function Section({
  label,
  hint,
  tone,
  count,
  children,
  collapsedByDefault,
}: {
  label: string;
  hint: string;
  tone: "negative" | "positive" | "teal" | "muted";
  count: number;
  children: React.ReactNode;
  collapsedByDefault?: boolean;
}) {
  if (count === 0) return null;
  const dot = {
    negative: "bg-[var(--color-negative)]",
    positive: "bg-[var(--color-positive)]",
    teal: "bg-[var(--color-teal)]",
    muted: "bg-[var(--color-ink-faint)]",
  }[tone];

  const heading = (
    <div className="mb-2 flex items-baseline gap-2">
      <span className={`inline-block h-1.5 w-1.5 rounded-full ${dot}`} />
      <h2 className="text-[13px] font-semibold text-[var(--color-ink)]">
        {label} ({count})
      </h2>
      <span className="text-[11px] text-[var(--color-ink-faint)]">{hint}</span>
    </div>
  );

  if (collapsedByDefault) {
    return (
      <details className="group">
        <summary className="cursor-pointer list-none">{heading}</summary>
        {children}
      </details>
    );
  }
  return (
    <section>
      {heading}
      {children}
    </section>
  );
}

export function EventsFeed() {
  const [range, setRange] = useState<DateRangeSelection>({ mode: "window", windowHours: 24 });
  const [events, setEvents] = useState<EventsResponse | null>(null);
  const [fallbackEvents, setFallbackEvents] = useState<EventsResponse | null>(null);
  const [pulse, setPulse] = useState<MarketPulseResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    const params = range.mode === "window" ? { windowHours: range.windowHours } : { start: range.start, end: range.end };
    Promise.all([fetchEvents(params), fetchMarketPulse().catch(() => null)])
      .then(async ([d, pulseRes]) => {
        if (cancelled) return;
        setEvents(d);
        setPulse(pulseRes);
        setError(null);
        // Intelligent empty-window fallback: a 24h window with nothing in it
        // does not mean nothing is happening — show the last 7 days as a
        // clearly separate, clearly labelled section rather than silently
        // widening the primary filter.
        if (d.events.length === 0 && range.mode === "window" && range.windowHours === 24) {
          try {
            const wider = await fetchEvents({ windowHours: 24 * 7 });
            if (!cancelled) setFallbackEvents(wider);
          } catch {
            // Fallback is best-effort — the primary empty state still renders correctly without it.
          }
        } else {
          setFallbackEvents(null);
        }
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof ApiError ? e.message : "Failed to load events.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [range]);

  function selectRange(selection: DateRangeSelection) {
    setLoading(true);
    setRange(selection);
  }

  const activeEvents = events?.events ?? [];
  const needsAttention = activeEvents.filter((e) => e.priority === "high");
  const highIds = new Set(needsAttention.map((e) => `${e.company_ticker}-${e.event_date}`));
  const positive = activeEvents.filter((e) => !highIds.has(`${e.company_ticker}-${e.event_date}`) && hasPositiveChange(e));
  const positiveIds = new Set(positive.map((e) => `${e.company_ticker}-${e.event_date}`));
  const fundamental = activeEvents.filter(
    (e) => !highIds.has(`${e.company_ticker}-${e.event_date}`) && !positiveIds.has(`${e.company_ticker}-${e.event_date}`) && hasNegativeChange(e)
  );
  const fundamentalIds = new Set(fundamental.map((e) => `${e.company_ticker}-${e.event_date}`));
  const shown = new Set([...highIds, ...positiveIds, ...fundamentalIds]);
  const companyActivity = activeEvents.filter((e) => !shown.has(`${e.company_ticker}-${e.event_date}`) && e.priority !== "low");
  const activityIds = new Set(companyActivity.map((e) => `${e.company_ticker}-${e.event_date}`));
  const other = activeEvents.filter((e) => !shown.has(`${e.company_ticker}-${e.event_date}`) && !activityIds.has(`${e.company_ticker}-${e.event_date}`));

  const totalShown = needsAttention.length + positive.length + companyActivity.length + fundamental.length + other.length + (pulse?.items.length ?? 0);

  return (
    <div className="space-y-4">
      <DateRangeFilter value={range} onChange={selectRange} />

      {error && (
        <div className="rounded-xl border border-[var(--color-negative)]/30 bg-[var(--color-negative)]/5 p-4 text-sm text-[var(--color-negative)]">
          {error}
        </div>
      )}

      {loading && !error && (
        <div className="space-y-2">
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="h-24 animate-pulse rounded-xl bg-[var(--color-border)]/50" />
          ))}
        </div>
      )}

      {!loading && !error && events && (
        <>
          {totalShown === 0 && !fallbackEvents && (
            <EmptyState
              status="All quiet"
              title="No new major updates in this window"
              description="FINN did not find any material developments, unusual EOD moves, or validated fundamental changes for your portfolio in this window."
            />
          )}

          <div className="space-y-6">
            <Section label="Needs your attention" hint="Material developments" tone="negative" count={needsAttention.length}>
              <div className="space-y-2">
                {needsAttention.map((e, i) => (
                  <EventCard key={`na-${i}`} event={e} />
                ))}
              </div>
            </Section>

            <Section label="Positive developments" hint="Evidence-backed improvements" tone="positive" count={positive.length}>
              <div className="space-y-2">
                {positive.map((e, i) => (
                  <EventCard key={`pos-${i}`} event={e} />
                ))}
              </div>
            </Section>

            <Section label="Company activity" hint="Chronological — announcements, results, board actions" tone="teal" count={companyActivity.length}>
              <div className="space-y-2">
                {companyActivity.map((e, i) => (
                  <EventCard key={`act-${i}`} event={e} />
                ))}
              </div>
            </Section>

            {pulse && pulse.items.length > 0 && (
              <section>
                <div className="mb-2 flex items-baseline gap-2">
                  <span className="inline-block h-1.5 w-1.5 rounded-full bg-[var(--color-teal)]" />
                  <h2 className="text-[13px] font-semibold text-[var(--color-ink)]">Market pulse ({pulse.items.length})</h2>
                  <span className="text-[11px] text-[var(--color-ink-faint)]">Unusual EOD moves — editorial thresholds, not your alert settings</span>
                </div>
                <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                  {pulse.items.map((item) => (
                    <PulseCard key={item.ticker} item={item} />
                  ))}
                </div>
              </section>
            )}

            <Section label="Fundamental watch" hint="Validated financial changes worth investigating" tone="negative" count={fundamental.length}>
              <div className="space-y-2">
                {fundamental.map((e, i) => (
                  <EventCard key={`fund-${i}`} event={e} />
                ))}
              </div>
            </Section>
            {fundamental.length === 0 && companyActivity.length + positive.length + needsAttention.length > 0 && (
              <p className="text-[12px] text-[var(--color-ink-faint)]">
                Fundamental watch: no validated financial-metric changes to show yet — financial data hasn&apos;t been imported for your portfolio companies.
              </p>
            )}

            <Section label="Other updates" hint="Routine filings" tone="muted" count={other.length} collapsedByDefault>
              <div className="mt-2 space-y-2">
                {other.map((e, i) => (
                  <EventCard key={`other-${i}`} event={e} />
                ))}
              </div>
            </Section>
          </div>

          {fallbackEvents && fallbackEvents.events.length > 0 && (
            <div className="border-t border-[var(--color-border)] pt-4">
              <div className="mb-2 flex items-baseline gap-2">
                <h2 className="text-[13px] font-semibold text-[var(--color-ink)]">Latest available portfolio activity</h2>
                <span className="text-[11px] text-[var(--color-ink-faint)]">
                  No new updates in the last 24 hours — showing the last 7 days instead
                </span>
              </div>
              <div className="space-y-2">
                {fallbackEvents.events.slice(0, 10).map((e, i) => (
                  <EventCard key={`fallback-${i}`} event={e} />
                ))}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
