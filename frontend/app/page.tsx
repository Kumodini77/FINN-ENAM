"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { EventsFeed } from "@/components/EventsFeed";
import { PageHeader } from "@/components/PageHeader";

export default function DailyIntelligencePage() {
  const [search, setSearch] = useState("");
  const router = useRouter();

  function goToResearch(e: React.FormEvent) {
    e.preventDefault();
    if (!search.trim()) return;
    router.push(`/research?ticker=${encodeURIComponent(search.trim().toUpperCase())}`);
  }

  return (
    <div>
      <PageHeader title="Today's briefing" />
      <div className="p-4 md:p-8">
        <form onSubmit={goToResearch} className="mb-4">
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search a company or ask FINN anything…"
            aria-label="Search a company or ask FINN"
            className="w-full rounded-lg border border-[var(--color-border-strong)] bg-[var(--color-surface)] px-3.5 py-2.5 text-sm text-[var(--color-ink)] placeholder:text-[var(--color-ink-faint)] focus:border-[var(--color-focus)] focus:outline-none"
          />
        </form>

        <EventsFeed />
      </div>
    </div>
  );
}
