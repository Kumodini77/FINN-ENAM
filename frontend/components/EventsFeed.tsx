"use client";

import { useEffect, useState } from "react";
import { ApiError, fetchEvents } from "@/lib/api";
import type { EventsResponse } from "@/types/api";
import { EventCard } from "./EventCard";
import { EmptyState } from "./EmptyState";

const WINDOW_OPTIONS = [
  { label: "24h", hours: 24 },
  { label: "7 days", hours: 24 * 7 },
  { label: "30 days", hours: 24 * 30 },
] as const;

export function EventsFeed() {
  const [windowHours, setWindowHours] = useState<number>(24);
  const [events, setEvents] = useState<EventsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    fetchEvents({ windowHours })
      .then((d) => {
        if (!cancelled) {
          setEvents(d);
          setError(null);
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
  }, [windowHours]);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        {WINDOW_OPTIONS.map((opt) => (
          <button
            key={opt.hours}
            onClick={() => {
              setLoading(true);
              setWindowHours(opt.hours);
            }}
            className={`rounded-full px-3 py-1.5 text-[13px] font-medium transition-colors ${
              windowHours === opt.hours
                ? "bg-[var(--color-accent)] text-white"
                : "border border-[var(--color-border)] bg-[var(--color-surface)] text-[var(--color-ink-muted)] hover:bg-[var(--color-canvas)]"
            }`}
          >
            {opt.label}
          </button>
        ))}
      </div>

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

      {!loading && !error && events && events.events.length === 0 && (
        <EmptyState
          status="No events in this window"
          title="No material developments"
          description="Related disclosures (e.g. results + concall transcript for the same quarter) are grouped into one event here. Nothing material was found for your portfolio in this window."
        />
      )}

      {!loading && !error && events && events.events.length > 0 && (
        <>
          <p className="text-[12px] text-[var(--color-ink-faint)]">
            {events.events.length} event{events.events.length === 1 ? "" : "s"} grouped from {events.total_announcements}{" "}
            announcement{events.total_announcements === 1 ? "" : "s"}
          </p>
          <div className="space-y-2">
            {events.events.map((event, i) => (
              <EventCard key={`${event.company_ticker}-${event.event_date}-${i}`} event={event} />
            ))}
          </div>
        </>
      )}
    </div>
  );
}
