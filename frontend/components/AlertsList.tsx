"use client";

import { useEffect, useState } from "react";
import { ApiError, fetchAlerts, fetchCompanies } from "@/lib/api";
import { categoryLabel, PriorityBadge } from "./Badges";
import type { Alert, AnnouncementCategory, Company, PriorityLevel } from "@/types/api";
import { EmptyState } from "./EmptyState";

function formatTime(iso: string): string {
  return new Date(iso).toLocaleString("en-IN", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "Asia/Kolkata",
  });
}

function num(v: unknown): number | null {
  return typeof v === "number" ? v : null;
}
function str(v: unknown): string | null {
  return typeof v === "string" ? v : null;
}

// Market alerts don't carry a backend-computed priority — derive one, deterministically,
// from how far past the configured threshold the move actually was. Never a fabricated score:
// just "did this clear 1x, or clear 2x, the threshold the user themselves set."
function marketPriority(alert: Alert): PriorityLevel {
  if (alert.trigger_type === "volume_spike") {
    const multiple = num(alert.payload.volume_multiple);
    const configured = num(alert.payload.configured_multiple);
    if (multiple != null && configured != null && configured > 0 && multiple >= configured * 2) return "high";
    return "medium";
  }
  if (alert.trigger_type === "price_move") {
    const pct = num(alert.payload.daily_change_pct);
    const threshold = num(alert.payload.configured_threshold_pct);
    if (pct != null && threshold != null && threshold > 0 && Math.abs(pct) >= threshold * 2) return "high";
    return "medium";
  }
  return "medium";
}

function whatHappened(alert: Alert): string {
  if (alert.trigger_type === "material_announcement") {
    const category = str(alert.payload.category) as AnnouncementCategory | null;
    return category ? categoryLabel(category) : "Company announcement";
  }
  if (alert.trigger_type === "volume_spike") return "Unusual trading volume";
  return "Unusual price move";
}

function AlertCard({ alert, companyName }: { alert: Alert; companyName: string | undefined }) {
  const priority = alert.trigger_type === "material_announcement" ? ((str(alert.payload.priority) as PriorityLevel) ?? "medium") : marketPriority(alert);
  const category = str(alert.payload.category) as AnnouncementCategory | null;

  return (
    <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-4">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[13px] font-semibold text-[var(--color-ink)]">{companyName ?? alert.company_ticker}</span>
        <span className="text-[11px] text-[var(--color-ink-faint)]">{alert.company_ticker}</span>
        <PriorityBadge priority={priority} />
        {alert.trigger_type !== "material_announcement" && (
          <span className="rounded-full bg-[var(--color-canvas)] px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-[var(--color-ink-faint)]">
            EOD
          </span>
        )}
      </div>

      <p className="mt-1.5 text-[13px] font-medium text-[var(--color-ink)]">{whatHappened(alert)}</p>

      {alert.trigger_type === "material_announcement" ? (
        <>
          <p className="mt-1 text-[13px] text-[var(--color-ink-muted)]">{str(alert.payload.title)}</p>
          {str(alert.payload.why_it_matters) && (
            <p className="mt-1.5 text-[13px] leading-relaxed text-[var(--color-ink-muted)]">
              <span className="font-medium text-[var(--color-accent)]">Why it matters: </span>
              {str(alert.payload.why_it_matters)}
            </p>
          )}
          <div className="mt-2 flex flex-wrap items-center gap-2 text-[11px] text-[var(--color-ink-faint)]">
            {category && <span>{categoryLabel(category)}</span>}
            {str(alert.payload.original_source_url) && (
              <a
                href={str(alert.payload.original_source_url)!}
                target="_blank"
                rel="noreferrer"
                className="font-medium text-[var(--color-accent)] hover:underline"
              >
                View source filing →
              </a>
            )}
            <a
              href={`/research?ticker=${encodeURIComponent(alert.company_ticker)}&question=${encodeURIComponent(
                `Explain this company's most recent material announcement and its disclosed implications.`
              )}`}
              className="font-medium text-[var(--color-accent)] hover:underline"
            >
              Ask FINN about this →
            </a>
          </div>
        </>
      ) : alert.trigger_type === "volume_spike" ? (
        <div className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-[12px] text-[var(--color-ink-muted)] sm:grid-cols-4">
          <TriggerStat label="Volume" value={num(alert.payload.latest_volume)?.toLocaleString("en-IN")} />
          <TriggerStat label="Avg volume" value={num(alert.payload.avg_volume)?.toLocaleString("en-IN", { maximumFractionDigits: 0 })} />
          <TriggerStat label="Multiple" value={num(alert.payload.volume_multiple) != null ? `${num(alert.payload.volume_multiple)!.toFixed(1)}×` : null} />
          <TriggerStat label="Your threshold" value={num(alert.payload.configured_multiple) != null ? `${num(alert.payload.configured_multiple)}×` : null} />
        </div>
      ) : (
        <div className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-[12px] text-[var(--color-ink-muted)] sm:grid-cols-4">
          <TriggerStat label="Previous close" value={num(alert.payload.previous_close) != null ? `₹${num(alert.payload.previous_close)}` : null} />
          <TriggerStat label="Latest close" value={num(alert.payload.latest_close) != null ? `₹${num(alert.payload.latest_close)}` : null} />
          <TriggerStat
            label="Change"
            value={num(alert.payload.daily_change_pct) != null ? `${num(alert.payload.daily_change_pct)! > 0 ? "+" : ""}${num(alert.payload.daily_change_pct)!.toFixed(2)}%` : null}
          />
          <TriggerStat label="Your threshold" value={num(alert.payload.configured_threshold_pct) != null ? `${num(alert.payload.configured_threshold_pct)}%` : null} />
        </div>
      )}

      <p className="mt-2 text-[12px] text-[var(--color-ink-faint)]">
        {alert.trigger_type === "material_announcement" ? "Filed" : "EOD data dated"} {formatTime(alert.triggered_at)} IST
      </p>
    </div>
  );
}

function TriggerStat({ label, value }: { label: string; value: string | number | null | undefined }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wide text-[var(--color-ink-faint)]">{label}</div>
      <div className="tabular font-medium text-[var(--color-ink)]">{value ?? "—"}</div>
    </div>
  );
}

export function AlertsList() {
  const [alerts, setAlerts] = useState<Alert[] | null>(null);
  const [companies, setCompanies] = useState<Company[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([fetchAlerts(), fetchCompanies(true).catch(() => ({ companies: [], count: 0 }))])
      .then(([a, c]) => {
        setAlerts(a);
        setCompanies(c.companies);
      })
      .catch((e) => setError(e instanceof ApiError ? e.message : "Failed to load alerts."));
  }, []);

  if (error) {
    return <div className="rounded-xl border border-[var(--color-negative)]/30 bg-[var(--color-negative)]/5 p-4 text-sm text-[var(--color-negative)]">{error}</div>;
  }

  if (!alerts) {
    return (
      <div className="space-y-2">
        {Array.from({ length: 2 }).map((_, i) => (
          <div key={i} className="h-16 animate-pulse rounded-xl bg-[var(--color-border)]/50" />
        ))}
      </div>
    );
  }

  if (alerts.length === 0) {
    return (
      <EmptyState
        status="No alerts triggered"
        title="Nothing has crossed your thresholds yet"
        description="Alerts are evaluated whenever portfolio prices refresh or a filing is imported — not continuously. Visit the Portfolio page or import a filing to trigger an evaluation."
      />
    );
  }

  const nameByTicker = new Map(companies.map((c) => [c.ticker, c.name]));
  const sorted = [...alerts].sort((a, b) => new Date(b.triggered_at).getTime() - new Date(a.triggered_at).getTime());
  const needsAttention = sorted.filter(
    (a) => (a.trigger_type === "material_announcement" ? str(a.payload.priority) === "high" : marketPriority(a) === "high")
  );
  const others = sorted.filter((a) => !needsAttention.includes(a));

  return (
    <div className="space-y-6">
      {needsAttention.length > 0 && (
        <section>
          <h3 className="mb-2 text-[12px] font-semibold uppercase tracking-wide text-[var(--color-negative)]">Needs attention</h3>
          <div className="space-y-2">
            {needsAttention.map((a) => (
              <AlertCard key={a.id} alert={a} companyName={nameByTicker.get(a.company_ticker)} />
            ))}
          </div>
        </section>
      )}
      {others.length > 0 && (
        <section>
          <h3 className="mb-2 text-[12px] font-semibold uppercase tracking-wide text-[var(--color-ink-faint)]">Other recent alerts</h3>
          <div className="space-y-2">
            {others.map((a) => (
              <AlertCard key={a.id} alert={a} companyName={nameByTicker.get(a.company_ticker)} />
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
