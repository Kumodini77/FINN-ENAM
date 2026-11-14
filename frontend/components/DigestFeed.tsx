"use client";

import { useEffect, useMemo, useState } from "react";
import { ApiError, fetchDigest } from "@/lib/api";
import { ALL_ANNOUNCEMENT_CATEGORIES, type AnnouncementCategory, type DigestResponse } from "@/types/api";
import { AnnouncementCard } from "./AnnouncementCard";
import { categoryLabel } from "./Badges";
import { EmptyState } from "./EmptyState";

const WINDOW_OPTIONS = [
  { label: "24h", hours: 24 },
  { label: "7 days", hours: 24 * 7 },
  { label: "30 days", hours: 24 * 30 },
] as const;

export function DigestFeed() {
  const [windowHours, setWindowHours] = useState<number>(24);
  const [selectedCategories, setSelectedCategories] = useState<Set<AnnouncementCategory>>(new Set());
  const [showRoutine, setShowRoutine] = useState(false);
  const [digest, setDigest] = useState<DigestResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // "start loading" is set by the triggering event handlers (window/category
    // buttons below, plus the initial useState(true)), not here — setting state
    // synchronously in an effect body risks cascading renders.
    let cancelled = false;
    fetchDigest({ windowHours, categories: Array.from(selectedCategories) })
      .then((d) => {
        if (!cancelled) {
          setDigest(d);
          setError(null);
        }
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof ApiError ? e.message : "Failed to load digest.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [windowHours, selectedCategories]);

  const { visible, collapsed } = useMemo(() => {
    const items = digest?.items ?? [];
    return {
      visible: items.filter((i) => !i.collapsed),
      collapsed: items.filter((i) => i.collapsed),
    };
  }, [digest]);

  function toggleCategory(cat: AnnouncementCategory) {
    setLoading(true);
    setSelectedCategories((prev) => {
      const next = new Set(prev);
      if (next.has(cat)) next.delete(cat);
      else next.add(cat);
      return next;
    });
  }

  function selectWindow(hours: number) {
    setLoading(true);
    setWindowHours(hours);
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        {WINDOW_OPTIONS.map((opt) => (
          <button
            key={opt.hours}
            onClick={() => selectWindow(opt.hours)}
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

      <div className="flex flex-wrap gap-1.5">
        {ALL_ANNOUNCEMENT_CATEGORIES.map((cat) => (
          <button
            key={cat}
            onClick={() => toggleCategory(cat)}
            className={`rounded-full border px-2.5 py-1 text-[11px] font-medium transition-colors ${
              selectedCategories.has(cat)
                ? "border-[var(--color-accent)] bg-[var(--color-accent-soft)] text-[var(--color-accent)]"
                : "border-[var(--color-border)] text-[var(--color-ink-faint)] hover:text-[var(--color-ink-muted)]"
            }`}
          >
            {categoryLabel(cat)}
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

      {!loading && !error && digest && digest.total_count === 0 && (
        <EmptyState
          status="No filings in this window"
          title="Nothing to show yet"
          description="No announcements have been imported for your portfolio in this window. FINN doesn't scrape NSE/BSE live (see docs/filing-access-spike.md) — filings are added via the manual import tool until a licensed data feed is in place."
        />
      )}

      {!loading && !error && visible.length > 0 && (
        <div className="space-y-2">
          {visible.map((item) => (
            <AnnouncementCard key={item.id} item={item} />
          ))}
        </div>
      )}

      {!loading && !error && collapsed.length > 0 && (
        <div>
          <button
            onClick={() => setShowRoutine((v) => !v)}
            className="w-full rounded-xl border border-dashed border-[var(--color-border-strong)] px-4 py-2.5 text-[13px] font-medium text-[var(--color-ink-muted)] hover:bg-[var(--color-canvas)]"
          >
            {showRoutine ? "Hide" : "Show"} {collapsed.length} routine filing{collapsed.length === 1 ? "" : "s"}
          </button>
          {showRoutine && (
            <div className="mt-2 space-y-2">
              {collapsed.map((item) => (
                <AnnouncementCard key={item.id} item={item} />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
