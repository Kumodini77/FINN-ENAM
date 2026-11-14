"use client";

import { useEffect, useState } from "react";
import { fetchAlerts, fetchCompanies, fetchDigest, fetchPortfolioQuotes } from "@/lib/api";
import { formatPct, formatPrice, formatTime, formatVolume } from "@/lib/format";
import type { Alert, Company, DigestItem, PriceQuote } from "@/types/api";

type Row = {
  company: Company;
  quote: PriceQuote | undefined;
  anomalyAlerts: Alert[];
  latestAnnouncement: DigestItem | undefined;
};

export function PortfolioTable() {
  const [rows, setRows] = useState<Row[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notes, setNotes] = useState<string>("");

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const [companiesRes, quotesRes, alerts, digest] = await Promise.all([
          fetchCompanies(true),
          fetchPortfolioQuotes(),
          fetchAlerts().catch(() => [] as Alert[]),
          fetchDigest({ windowHours: 24 * 30 }).catch(() => null),
        ]);
        if (cancelled) return;

        const quoteByTicker = new Map(quotesRes.quotes.map((q) => [q.ticker, q]));

        const alertsByTicker = new Map<string, Alert[]>();
        for (const a of alerts) {
          if (a.trigger_type === "material_announcement") continue; // shown via latestAnnouncement instead
          const list = alertsByTicker.get(a.company_ticker) ?? [];
          list.push(a);
          alertsByTicker.set(a.company_ticker, list);
        }

        const latestByTicker = new Map<string, DigestItem>();
        for (const item of digest?.items ?? []) {
          const existing = latestByTicker.get(item.company_ticker);
          if (!existing || new Date(item.filed_at) > new Date(existing.filed_at)) {
            latestByTicker.set(item.company_ticker, item);
          }
        }

        setRows(
          companiesRes.companies.map((company) => ({
            company,
            quote: quoteByTicker.get(company.ticker),
            anomalyAlerts: alertsByTicker.get(company.ticker) ?? [],
            latestAnnouncement: latestByTicker.get(company.ticker),
          }))
        );
        setNotes(quotesRes.calculation_notes);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : "Failed to load portfolio data.");
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, []);

  if (error) {
    return (
      <div className="rounded-xl border border-[var(--color-negative)]/30 bg-[var(--color-negative)]/5 p-6">
        <p className="text-sm font-medium text-[var(--color-negative)]">Could not load portfolio data</p>
        <p className="mt-1 text-sm text-[var(--color-ink-muted)]">{error}</p>
      </div>
    );
  }

  if (!rows) {
    return (
      <div className="space-y-2">
        {Array.from({ length: 8 }).map((_, i) => (
          <div key={i} className="h-16 animate-pulse rounded-xl bg-[var(--color-border)]/50" />
        ))}
      </div>
    );
  }

  return (
    <div>
      <div className="overflow-hidden rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)]">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-[var(--color-border)] text-left text-[11px] uppercase tracking-wide text-[var(--color-ink-faint)]">
              <th className="px-4 py-3 font-medium">Company</th>
              <th className="hidden px-4 py-3 font-medium sm:table-cell">Sector</th>
              <th className="px-4 py-3 text-right font-medium">Price</th>
              <th className="px-4 py-3 text-right font-medium">Change</th>
              <th className="hidden px-4 py-3 text-right font-medium md:table-cell">Volume</th>
              <th className="hidden px-4 py-3 text-right font-medium lg:table-cell">As of</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <PortfolioRow key={row.company.ticker} {...row} />
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-3 px-1 text-[12px] leading-relaxed text-[var(--color-ink-faint)]">{notes}</p>
    </div>
  );
}

function PortfolioRow({ company, quote, anomalyAlerts, latestAnnouncement }: Row) {
  if (!quote) {
    return (
      <tr className="border-b border-[var(--color-border)] last:border-0">
        <td className="px-4 py-3" colSpan={6}>
          <span className="text-[var(--color-ink-faint)]">{company.name} — no quote returned</span>
        </td>
      </tr>
    );
  }

  if (!quote.data_available) {
    return (
      <tr className="border-b border-[var(--color-border)] last:border-0">
        <td className="px-4 py-3">
          <div className="font-medium text-[var(--color-ink)]">{company.name}</div>
          <div className="text-[12px] text-[var(--color-ink-faint)]">{company.ticker}</div>
        </td>
        <td colSpan={5} className="px-4 py-3 text-[13px] text-[var(--color-ink-faint)]">
          Data unavailable — {quote.error}
        </td>
      </tr>
    );
  }

  const isUp = (quote.daily_change_pct ?? 0) >= 0;
  const isProvisional = quote.session_status === "provisional_intraday";

  return (
    <tr className="border-b border-[var(--color-border)] last:border-0 hover:bg-[var(--color-canvas)]/50 align-top">
      <td className="px-4 py-3">
        <div className="flex items-center gap-1.5">
          <span className="font-medium text-[var(--color-ink)]">{company.name}</span>
          {anomalyAlerts.length > 0 && (
            <span
              className="inline-flex h-1.5 w-1.5 rounded-full bg-[var(--color-negative)]"
              title={anomalyAlerts.map((a) => a.trigger_type).join(", ")}
            />
          )}
        </div>
        <div className="text-[12px] text-[var(--color-ink-faint)]">{company.ticker}</div>
        {latestAnnouncement && (
          <div className="mt-1 max-w-xs truncate text-[11px] text-[var(--color-ink-faint)]" title={latestAnnouncement.title}>
            Latest: {latestAnnouncement.title}
          </div>
        )}
      </td>
      <td className="hidden px-4 py-3 text-[var(--color-ink-muted)] sm:table-cell">{company.sector}</td>
      <td className="tabular px-4 py-3 text-right font-medium text-[var(--color-ink)]">
        {formatPrice(quote.latest_close)}
      </td>
      <td
        className={`tabular px-4 py-3 text-right font-medium ${
          isUp ? "text-[var(--color-positive)]" : "text-[var(--color-negative)]"
        }`}
      >
        {formatPct(quote.daily_change_pct)}
      </td>
      <td className="tabular hidden px-4 py-3 text-right text-[var(--color-ink-muted)] md:table-cell">
        {formatVolume(quote.latest_volume)}
      </td>
      <td className="hidden px-4 py-3 text-right lg:table-cell">
        <span
          className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[11px] font-medium ${
            isProvisional
              ? "bg-amber-500/10 text-amber-700"
              : "bg-[var(--color-accent-soft)] text-[var(--color-accent)]"
          }`}
          title={quote.as_of_date ?? undefined}
        >
          {isProvisional ? "Live · in session" : "EOD close"}
        </span>
        <div className="mt-1 text-[11px] text-[var(--color-ink-faint)]">
          fetched {formatTime(quote.fetched_at)} IST
        </div>
      </td>
    </tr>
  );
}
