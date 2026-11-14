"use client";

import { useEffect, useState } from "react";
import { ApiError, fetchAlerts } from "@/lib/api";
import type { Alert } from "@/types/api";
import { EmptyState } from "./EmptyState";

const TRIGGER_LABELS: Record<Alert["trigger_type"], string> = {
  volume_spike: "Volume spike",
  price_move: "Price move",
  material_announcement: "Material filing",
};

function formatTime(iso: string): string {
  return new Date(iso).toLocaleString("en-IN", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "Asia/Kolkata",
  });
}

export function AlertsList() {
  const [alerts, setAlerts] = useState<Alert[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchAlerts()
      .then(setAlerts)
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

  return (
    <div className="space-y-2">
      {alerts.map((alert) => (
        <div key={alert.id} className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-4">
          <div className="flex items-center justify-between">
            <span className="text-[13px] font-semibold text-[var(--color-ink)]">{alert.company_ticker}</span>
            <span className="inline-flex items-center rounded-full bg-[var(--color-accent-soft)] px-2 py-0.5 text-[11px] font-medium text-[var(--color-accent)]">
              {TRIGGER_LABELS[alert.trigger_type]}
            </span>
          </div>
          <p className="mt-1.5 text-[13px] text-[var(--color-ink-muted)]">
            {alert.trigger_type === "material_announcement"
              ? String(alert.payload.title ?? "")
              : alert.trigger_type === "volume_spike"
                ? `Volume ${Number(alert.payload.volume_multiple ?? 0).toFixed(2)}× average`
                : `Price moved ${Number(alert.payload.daily_change_pct ?? 0).toFixed(2)}%`}
          </p>
          <p className="mt-2 text-[12px] text-[var(--color-ink-faint)]">{formatTime(alert.triggered_at)} IST</p>
        </div>
      ))}
    </div>
  );
}
