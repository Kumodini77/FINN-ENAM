"use client";

import { useState } from "react";
import { DigestFeed } from "@/components/DigestFeed";
import { EventsFeed } from "@/components/EventsFeed";
import { PageHeader } from "@/components/PageHeader";

export default function DailyIntelligencePage() {
  const [view, setView] = useState<"events" | "announcements">("events");

  return (
    <div>
      <PageHeader
        title="Daily Intelligence"
        subtitle="Push: filings across your portfolio, filtered and prioritised so what matters surfaces first."
      />
      <div className="p-4 md:p-8">
        <div className="mb-4 inline-flex rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-0.5">
          <button
            onClick={() => setView("events")}
            className={`rounded-md px-3 py-1.5 text-[13px] font-medium transition-colors ${
              view === "events" ? "bg-[var(--color-accent)] text-white" : "text-[var(--color-ink-muted)]"
            }`}
          >
            By event
          </button>
          <button
            onClick={() => setView("announcements")}
            className={`rounded-md px-3 py-1.5 text-[13px] font-medium transition-colors ${
              view === "announcements" ? "bg-[var(--color-accent)] text-white" : "text-[var(--color-ink-muted)]"
            }`}
          >
            By announcement
          </button>
        </div>
        {view === "events" ? <EventsFeed /> : <DigestFeed />}
      </div>
    </div>
  );
}
