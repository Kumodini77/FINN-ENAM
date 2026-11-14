"use client";

import { useState } from "react";
import { ApiError, importAnnouncementsBatch, type AnnouncementImportBatchResult } from "@/lib/api";
import { PageHeader } from "@/components/PageHeader";

const PLACEHOLDER = `[
  {
    "ticker": "RELIANCE",
    "title": "Exact filing title, copied from the exchange/screener listing",
    "filed_at": "2026-11-13T16:30:00+05:30",
    "original_source_url": "https://www.bseindia.com/... (the real filing page)",
    "document_url": null,
    "category": null,
    "source": "manual_seed",
    "verification_status": "unverified"
  }
]`;

export default function AdminImportPage() {
  const [text, setText] = useState("");
  const [result, setResult] = useState<AnnouncementImportBatchResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit() {
    setError(null);
    setResult(null);
    let parsed: unknown;
    try {
      parsed = JSON.parse(text);
    } catch {
      setError("That's not valid JSON. Check for a trailing comma or missing bracket.");
      return;
    }
    if (!Array.isArray(parsed)) {
      setError("Expected a JSON list of filing objects, e.g. [ { ... } ].");
      return;
    }
    setSubmitting(true);
    try {
      const res = await importAnnouncementsBatch(parsed as never);
      setResult(res);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Import failed.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div>
      <PageHeader
        title="Import filings"
        subtitle="Manual filing ingestion — see docs/filing-access-spike.md for why this exists instead of a live NSE/BSE feed."
      />
      <div className="space-y-4 p-4 md:p-8">
        <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-4 text-[13px] leading-relaxed text-[var(--color-ink-muted)]">
          Paste a JSON list of real filings you&apos;ve verified yourself against the actual source. Each item needs at
          least <code className="text-[var(--color-ink)]">ticker</code>, <code className="text-[var(--color-ink)]">title</code>,{" "}
          <code className="text-[var(--color-ink)]">filed_at</code>, and{" "}
          <code className="text-[var(--color-ink)]">original_source_url</code>. Category is auto-classified if omitted.
          Duplicate (ticker + source URL) entries are skipped, not re-imported. A CLI equivalent lives at{" "}
          <code className="text-[var(--color-ink)]">backend/scripts/import_announcements.py</code>.
        </div>

        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder={PLACEHOLDER}
          rows={14}
          className="w-full rounded-xl border border-[var(--color-border-strong)] bg-[var(--color-surface)] p-3 font-mono text-[12px] text-[var(--color-ink)] placeholder:text-[var(--color-ink-faint)]"
        />

        <button
          onClick={handleSubmit}
          disabled={submitting || !text.trim()}
          className="rounded-lg bg-[var(--color-accent)] px-4 py-2 text-[13px] font-medium text-white hover:opacity-90 disabled:opacity-60"
        >
          {submitting ? "Importing…" : "Import"}
        </button>

        {error && (
          <div className="rounded-xl border border-[var(--color-negative)]/30 bg-[var(--color-negative)]/5 p-4 text-sm text-[var(--color-negative)]">
            {error}
          </div>
        )}

        {result && (
          <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-4 text-sm">
            <p className="font-medium text-[var(--color-ink)]">
              Created {result.created_count} · Duplicates {result.duplicate_count} · Errors {result.error_count}
            </p>
            {result.errors.length > 0 && (
              <ul className="mt-2 list-disc pl-5 text-[var(--color-negative)]">
                {result.errors.map((e, i) => (
                  <li key={i}>{e}</li>
                ))}
              </ul>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
