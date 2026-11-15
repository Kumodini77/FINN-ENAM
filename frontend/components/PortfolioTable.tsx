"use client";

import { useEffect, useMemo, useState } from "react";
import { fetchCompanies, fetchEvents, fetchPortfolioQuotes, fetchPriceHistory } from "@/lib/api";
import { formatPct, formatPrice, formatTime, formatVolume } from "@/lib/format";
import { computeStatus, STATUS_LABEL, STATUS_ORDER, type PortfolioStatus } from "@/lib/portfolioStatus";
import { Sparkline } from "./Sparkline";
import type { Company, DailyBar, EventItem, PriceQuote } from "@/types/api";

type Row = {
  company: Company;
  quote: PriceQuote | undefined;
  history: DailyBar[];
  latestEvent: EventItem | undefined;
  status: PortfolioStatus;
  statusReason: string;
};

type Filter = "all" | "sector" | "positive" | "needs_attention" | "limited_data";

const STATUS_DOT: Record<PortfolioStatus, string> = {
  needs_attention: "bg-[var(--color-negative)]",
  positive: "bg-[var(--color-positive)]",
  stable: "bg-[var(--color-teal)]",
  limited_data: "bg-[var(--color-ink-faint)]",
};

const STATUS_TEXT: Record<PortfolioStatus, string> = {
  needs_attention: "text-[var(--color-negative)]",
  positive: "text-[var(--color-positive)]",
  stable: "text-[var(--color-teal)]",
  limited_data: "text-[var(--color-ink-faint)]",
};

function StatusDot({ status }: { status: PortfolioStatus }) {
  return <span className={`inline-block h-1.5 w-1.5 rounded-full ${STATUS_DOT[status]}`} />;
}

export function PortfolioTable() {
  const [rows, setRows] = useState<Row[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notes, setNotes] = useState<string>("");
  const [lastUpdated, setLastUpdated] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const [sectorFilter, setSectorFilter] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const [companiesRes, quotesRes, eventsRes] = await Promise.all([
          fetchCompanies(true),
          fetchPortfolioQuotes(),
          fetchEvents({ windowHours: 24 * 14 }).catch(() => null),
        ]);
        if (cancelled) return;

        const quoteByTicker = new Map(quotesRes.quotes.map((q) => [q.ticker, q]));
        const latestEventByTicker = new Map<string, EventItem>();
        for (const event of eventsRes?.events ?? []) {
          // events are returned newest-first; keep only the first (latest) per ticker.
          if (!latestEventByTicker.has(event.company_ticker)) {
            latestEventByTicker.set(event.company_ticker, event);
          }
        }

        const histories = await Promise.all(
          companiesRes.companies.map((c) =>
            fetchPriceHistory(c.ticker, 30)
              .then((h) => h.bars)
              .catch(() => [] as DailyBar[])
          )
        );

        const newRows: Row[] = companiesRes.companies.map((company, i) => {
          const quote = quoteByTicker.get(company.ticker);
          const latestEvent = latestEventByTicker.get(company.ticker);
          const { status, reason } = computeStatus(quote, latestEvent);
          return { company, quote, history: histories[i], latestEvent, status, statusReason: reason };
        });

        if (cancelled) return;
        setRows(newRows);
        setNotes(quotesRes.calculation_notes);
        setLastUpdated(new Date().toISOString());
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : "Failed to load portfolio data.");
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, []);

  const sectors = useMemo(() => {
    if (!rows) return [];
    const counts = new Map<string, number>();
    for (const r of rows) counts.set(r.company.sector, (counts.get(r.company.sector) ?? 0) + 1);
    return [...counts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
  }, [rows]);

  const summary = useMemo(() => {
    if (!rows) return null;
    return {
      total: rows.length,
      positive: rows.filter((r) => r.status === "positive").length,
      needsAttention: rows.filter((r) => r.status === "needs_attention").length,
      limitedData: rows.filter((r) => r.status === "limited_data").length,
      importantDevelopments: rows.filter((r) => r.latestEvent).length,
    };
  }, [rows]);

  const filteredRows = useMemo(() => {
    if (!rows) return [];
    const q = search.trim().toLowerCase();
    return rows.filter((r) => {
      if (q && !r.company.name.toLowerCase().includes(q) && !r.company.ticker.toLowerCase().includes(q)) return false;
      if (filter === "positive" && r.status !== "positive") return false;
      if (filter === "needs_attention" && r.status !== "needs_attention") return false;
      if (filter === "limited_data" && r.status !== "limited_data") return false;
      if (filter === "sector" && sectorFilter && r.company.sector !== sectorFilter) return false;
      return true;
    });
  }, [rows, search, filter, sectorFilter]);

  const grouped = useMemo(() => {
    const bySector = new Map<string, Row[]>();
    for (const r of filteredRows) {
      const list = bySector.get(r.company.sector) ?? [];
      list.push(r);
      bySector.set(r.company.sector, list);
    }
    for (const list of bySector.values()) {
      list.sort((a, b) => STATUS_ORDER.indexOf(a.status) - STATUS_ORDER.indexOf(b.status));
    }
    return [...bySector.entries()].sort((a, b) => b[1].length - a[1].length || a[0].localeCompare(b[0]));
  }, [filteredRows]);

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
          <div key={i} className="h-20 animate-pulse rounded-xl bg-[var(--color-border)]/50" />
        ))}
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header: count, last updated, search */}
      <div className="space-y-3">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <div>
            <h2 className="text-[17px] font-semibold text-[var(--color-ink)]">
              {summary?.total} tracked {summary?.total === 1 ? "company" : "companies"}
            </h2>
            {lastUpdated && (
              <p className="text-[12px] text-[var(--color-ink-faint)]">Updated {formatTime(lastUpdated)} IST</p>
            )}
          </div>
        </div>

        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search company or ticker…"
          aria-label="Search portfolio companies"
          className="w-full rounded-lg border border-[var(--color-border-strong)] bg-[var(--color-surface)] px-3.5 py-2.5 text-sm text-[var(--color-ink)] placeholder:text-[var(--color-ink-faint)] focus:border-[var(--color-focus)] focus:outline-none"
        />

        <div className="flex flex-wrap gap-1.5">
          {([
            ["all", "All companies"],
            ["positive", "Positive momentum"],
            ["needs_attention", "Needs attention"],
            ["limited_data", "Limited data"],
          ] as [Filter, string][]).map(([key, label]) => (
            <button
              key={key}
              type="button"
              onClick={() => setFilter(key)}
              className={`rounded-full border px-3 py-1.5 text-[12px] font-medium transition-colors ${
                filter === key
                  ? "border-[var(--color-accent)] bg-[var(--color-accent-soft)] text-[var(--color-accent)]"
                  : "border-[var(--color-border)] bg-[var(--color-surface)] text-[var(--color-ink-muted)] hover:border-[var(--color-border-strong)]"
              }`}
            >
              {label}
            </button>
          ))}
          <select
            value={filter === "sector" ? sectorFilter ?? "" : ""}
            onChange={(e) => {
              setSectorFilter(e.target.value || null);
              setFilter(e.target.value ? "sector" : "all");
            }}
            className="rounded-full border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-1.5 text-[12px] font-medium text-[var(--color-ink-muted)]"
          >
            <option value="">By sector…</option>
            {sectors.map(([sector]) => (
              <option key={sector} value={sector}>
                {sector}
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* Summary strip */}
      {summary && (
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          <SummaryTile label="Positive momentum" value={summary.positive} tone="positive" />
          <SummaryTile label="Needs attention" value={summary.needsAttention} tone="negative" />
          <SummaryTile label="Important updates" value={summary.importantDevelopments} tone="teal" />
          <SummaryTile label="Limited data" value={summary.limitedData} tone="muted" />
        </div>
      )}

      {filteredRows.length === 0 && (
        <div className="rounded-xl border border-dashed border-[var(--color-border-strong)] bg-[var(--color-surface)] p-6 text-center text-sm text-[var(--color-ink-muted)]">
          No companies match “{search}”{filter !== "all" ? " with the selected filter" : ""}.
        </div>
      )}

      {/* Sector groups */}
      {grouped.map(([sector, sectorRows]) => (
        <details key={sector} open className="group rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)]">
          <summary className="flex cursor-pointer items-center justify-between gap-2 px-4 py-3 text-[13px] font-semibold text-[var(--color-ink)]">
            <span>{sector}</span>
            <span className="rounded-full bg-[var(--color-canvas)] px-2 py-0.5 text-[11px] font-medium text-[var(--color-ink-faint)]">
              {sectorRows.length}
            </span>
          </summary>

          {/* Desktop table */}
          <div className="hidden overflow-hidden border-t border-[var(--color-border)] md:block">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-[var(--color-border)] text-left text-[11px] uppercase tracking-wide text-[var(--color-ink-faint)]">
                  <th className="px-4 py-2.5 font-medium">Company</th>
                  <th className="px-4 py-2.5 text-right font-medium">Price</th>
                  <th className="px-4 py-2.5 text-right font-medium">Change</th>
                  <th className="px-4 py-2.5 text-right font-medium">Volume</th>
                  <th className="px-4 py-2.5 font-medium">1M trend</th>
                  <th className="px-4 py-2.5 font-medium">Status</th>
                </tr>
              </thead>
              <tbody>
                {sectorRows.map((row) => (
                  <DesktopRow key={row.company.ticker} row={row} />
                ))}
              </tbody>
            </table>
          </div>

          {/* Mobile cards */}
          <div className="space-y-2 border-t border-[var(--color-border)] p-2 md:hidden">
            {sectorRows.map((row) => (
              <MobileCard key={row.company.ticker} row={row} />
            ))}
          </div>
        </details>
      ))}

      <p className="px-1 text-[12px] leading-relaxed text-[var(--color-ink-faint)]">{notes}</p>
    </div>
  );
}

function SummaryTile({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone: "positive" | "negative" | "teal" | "muted";
}) {
  const toneClass = {
    positive: "text-[var(--color-positive)]",
    negative: "text-[var(--color-negative)]",
    teal: "text-[var(--color-teal)]",
    muted: "text-[var(--color-ink-faint)]",
  }[tone];
  return (
    <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-3">
      <div className={`text-[22px] font-semibold tabular ${toneClass}`}>{value}</div>
      <div className="text-[11px] text-[var(--color-ink-faint)]">{label}</div>
    </div>
  );
}

function DesktopRow({ row }: { row: Row }) {
  const { company, quote, history, status, statusReason } = row;

  if (!quote || !quote.data_available) {
    return (
      <tr className="border-b border-[var(--color-border)] last:border-0">
        <td className="px-4 py-3">
          <div className="font-medium text-[var(--color-ink)]">{company.name}</div>
          <div className="text-[12px] text-[var(--color-ink-faint)]">{company.ticker}</div>
        </td>
        <td colSpan={5} className="px-4 py-3 text-[13px] text-[var(--color-ink-faint)]">
          Data unavailable{quote?.error ? ` — ${quote.error}` : ""}
        </td>
      </tr>
    );
  }

  const isUp = (quote.daily_change_pct ?? 0) >= 0;

  return (
    <tr className="border-b border-[var(--color-border)] last:border-0 hover:bg-[var(--color-canvas)]/50 align-middle" title={statusReason}>
      <td className="px-4 py-3">
        <div className="font-medium text-[var(--color-ink)]">{company.name}</div>
        <div className="text-[12px] text-[var(--color-ink-faint)]">{company.ticker}</div>
      </td>
      <td className="tabular px-4 py-3 text-right font-medium text-[var(--color-ink)]">{formatPrice(quote.latest_close)}</td>
      <td className={`tabular px-4 py-3 text-right font-medium ${isUp ? "text-[var(--color-positive)]" : "text-[var(--color-negative)]"}`}>
        {formatPct(quote.daily_change_pct)}
      </td>
      <td className="tabular px-4 py-3 text-right text-[var(--color-ink-muted)]">{formatVolume(quote.latest_volume)}</td>
      <td className="px-4 py-3">
        <Sparkline bars={history} />
      </td>
      <td className="px-4 py-3">
        <span className={`inline-flex items-center gap-1.5 text-[12px] font-medium ${STATUS_TEXT[status]}`}>
          <StatusDot status={status} />
          {STATUS_LABEL[status]}
        </span>
      </td>
    </tr>
  );
}

function MobileCard({ row }: { row: Row }) {
  const { company, quote, history, latestEvent, status, statusReason } = row;

  if (!quote || !quote.data_available) {
    return (
      <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-canvas)] p-3">
        <div className="font-medium text-[var(--color-ink)]">
          {company.name} <span className="text-[12px] font-normal text-[var(--color-ink-faint)]">{company.ticker}</span>
        </div>
        <p className="mt-1 text-[12px] text-[var(--color-ink-faint)]">Data unavailable{quote?.error ? ` — ${quote.error}` : ""}</p>
      </div>
    );
  }

  const isUp = (quote.daily_change_pct ?? 0) >= 0;

  return (
    <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-canvas)] p-3">
      {/* Top row */}
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="truncate font-medium text-[var(--color-ink)]">{company.name}</div>
          <div className="text-[11px] text-[var(--color-ink-faint)]">
            {company.ticker} · {company.sector}
          </div>
        </div>
        <div className="shrink-0 text-right tabular font-semibold text-[var(--color-ink)]">{formatPrice(quote.latest_close)}</div>
      </div>

      {/* Middle row */}
      <div className="mt-2 flex items-center justify-between gap-2 text-[13px]">
        <span className={`tabular font-semibold ${isUp ? "text-[var(--color-positive)]" : "text-[var(--color-negative)]"}`}>
          {formatPct(quote.daily_change_pct)}
        </span>
        <span className="text-[12px] text-[var(--color-ink-muted)]">Vol {formatVolume(quote.latest_volume)}</span>
        <span className={`inline-flex items-center gap-1 text-[11px] font-medium ${STATUS_TEXT[status]}`}>
          <StatusDot status={status} />
          {STATUS_LABEL[status]}
        </span>
      </div>

      {/* Bottom row */}
      <div className="mt-2 flex items-center justify-between gap-2 border-t border-[var(--color-border)] pt-2">
        <Sparkline bars={history} width={72} height={26} />
        <p className="min-w-0 flex-1 truncate text-right text-[11px] text-[var(--color-ink-faint)]" title={latestEvent?.why_it_matters ?? statusReason}>
          {latestEvent ? latestEvent.why_it_matters : "No recent updates"}
        </p>
      </div>
    </div>
  );
}
