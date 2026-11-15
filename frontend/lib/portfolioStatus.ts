import type { EventItem, PriceQuote } from "@/types/api";

export type PortfolioStatus = "needs_attention" | "positive" | "stable" | "limited_data";

export interface StatusResult {
  status: PortfolioStatus;
  reason: string;
}

/**
 * Deterministic, explainable status — never derived from price movement
 * alone (a stock rising 5% is not necessarily a good business) and never a
 * fabricated "AI score". Built only from two real, already-computed
 * backend signals:
 *   - whether EOD price data is actually available for this ticker
 *   - the most recent/most severe Push EVENT for this ticker, whose
 *     priority and financial_changes[].direction are themselves computed
 *     deterministically by the existing backend (app.services.priority /
 *     app.services.event_intelligence) — this never invents a second,
 *     independent scoring system.
 *
 * Priority order, most to least severe:
 *   1. limited_data   — no EOD quote at all (can't assess anything).
 *   2. needs_attention — a HIGH priority event in the lookback window.
 *   3. positive        — a real financial_change with direction="positive"
 *                        and no high-priority event.
 *   4. stable          — everything else (price data present, nothing
 *                        notable detected).
 */
export function computeStatus(quote: PriceQuote | undefined, latestEvent: EventItem | undefined): StatusResult {
  if (!quote || !quote.data_available) {
    return { status: "limited_data", reason: "No EOD price data is currently available for this company." };
  }

  if (latestEvent?.priority === "high") {
    return {
      status: "needs_attention",
      reason: `High-priority development: ${latestEvent.why_it_matters}`,
    };
  }

  const positiveChange = latestEvent?.financial_changes.find((c) => c.direction === "positive");
  if (positiveChange) {
    return {
      status: "positive",
      reason: `${positiveChange.label} improved (${positiveChange.yoy_pct != null ? `${positiveChange.yoy_pct > 0 ? "+" : ""}${positiveChange.yoy_pct.toFixed(1)}% YoY` : "recent change"}).`,
    };
  }

  if (latestEvent) {
    return { status: "stable", reason: "A recent update was found, but it showed no major positive or negative financial change." };
  }

  return { status: "stable", reason: "No major recent developments detected; EOD price data is current." };
}

export const STATUS_LABEL: Record<PortfolioStatus, string> = {
  needs_attention: "Needs attention",
  positive: "Positive momentum",
  stable: "Stable",
  limited_data: "Limited data",
};

export const STATUS_ORDER: PortfolioStatus[] = ["needs_attention", "positive", "stable", "limited_data"];
