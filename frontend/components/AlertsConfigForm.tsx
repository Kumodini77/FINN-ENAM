"use client";

import { useEffect, useState } from "react";
import { ApiError, fetchAlertsConfig, saveAlertsConfig } from "@/lib/api";
import { ALL_ANNOUNCEMENT_CATEGORIES, type AlertsConfig, type AnnouncementCategory } from "@/types/api";
import { categoryLabel } from "./Badges";

export function AlertsConfigForm() {
  const [config, setConfig] = useState<AlertsConfig | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saveStatus, setSaveStatus] = useState<"idle" | "saving" | "saved" | "error">("idle");

  useEffect(() => {
    fetchAlertsConfig()
      .then(setConfig)
      .catch((e) => setError(e instanceof ApiError ? e.message : "Failed to load alert settings."));
  }, []);

  function toggleCategory(cat: AnnouncementCategory) {
    if (!config) return;
    const has = config.alert_categories.includes(cat);
    setConfig({
      ...config,
      alert_categories: has ? config.alert_categories.filter((c) => c !== cat) : [...config.alert_categories, cat],
    });
  }

  async function handleSave() {
    if (!config) return;
    setSaveStatus("saving");
    try {
      const saved = await saveAlertsConfig({
        volume_spike_multiple: config.volume_spike_multiple,
        price_move_pct: config.price_move_pct,
        digest_window_hours: config.digest_window_hours,
        alert_categories: config.alert_categories,
      });
      setConfig(saved);
      setSaveStatus("saved");
      setTimeout(() => setSaveStatus("idle"), 2000);
    } catch {
      setSaveStatus("error");
    }
  }

  if (error) {
    return <div className="rounded-xl border border-[var(--color-negative)]/30 bg-[var(--color-negative)]/5 p-4 text-sm text-[var(--color-negative)]">{error}</div>;
  }

  if (!config) {
    return <div className="h-48 animate-pulse rounded-xl bg-[var(--color-border)]/50" />;
  }

  const activeCategoryLabels = config.alert_categories.map(categoryLabel);

  return (
    <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-5">
      <h3 className="text-[15px] font-semibold text-[var(--color-ink)]">Watch rules</h3>

      <ul className="mt-3 space-y-1.5 text-[13px] text-[var(--color-ink)]">
        <li className="flex items-start gap-2">
          <span className="mt-0.5 inline-block h-1.5 w-1.5 shrink-0 rounded-full bg-[var(--color-positive)]" />
          Notify me when a portfolio company moves more than <strong>{config.price_move_pct}%</strong> in a day (EOD).
        </li>
        <li className="flex items-start gap-2">
          <span className="mt-0.5 inline-block h-1.5 w-1.5 shrink-0 rounded-full bg-[var(--color-positive)]" />
          Notify me when a portfolio company&apos;s volume exceeds <strong>{config.volume_spike_multiple}×</strong> its recent average (EOD).
        </li>
        <li className="flex items-start gap-2">
          <span className="mt-0.5 inline-block h-1.5 w-1.5 shrink-0 rounded-full bg-[var(--color-positive)]" />
          Notify me when a portfolio company announces{" "}
          {activeCategoryLabels.length > 0 ? activeCategoryLabels.join(", ") : "nothing (no categories selected)"}.
        </li>
      </ul>

      <h4 className="mt-5 text-[13px] font-semibold text-[var(--color-ink)]">Edit thresholds</h4>

      <div className="mt-2 grid grid-cols-1 gap-4 sm:grid-cols-2">
        <label className="block">
          <span className="text-[13px] font-medium text-[var(--color-ink)]">Volume spike multiple</span>
          <div className="mt-1 flex items-center gap-2">
            <input
              type="number"
              step="0.1"
              min="1"
              value={config.volume_spike_multiple}
              onChange={(e) => setConfig({ ...config, volume_spike_multiple: Number(e.target.value) })}
              className="w-24 rounded-lg border border-[var(--color-border-strong)] bg-[var(--color-canvas)] px-2.5 py-1.5 text-sm tabular text-[var(--color-ink)]"
            />
            <span className="text-[13px] text-[var(--color-ink-faint)]">× average volume</span>
          </div>
        </label>

        <label className="block">
          <span className="text-[13px] font-medium text-[var(--color-ink)]">Daily price move threshold</span>
          <div className="mt-1 flex items-center gap-2">
            <input
              type="number"
              step="0.5"
              min="0"
              value={config.price_move_pct}
              onChange={(e) => setConfig({ ...config, price_move_pct: Number(e.target.value) })}
              className="w-24 rounded-lg border border-[var(--color-border-strong)] bg-[var(--color-canvas)] px-2.5 py-1.5 text-sm tabular text-[var(--color-ink)]"
            />
            <span className="text-[13px] text-[var(--color-ink-faint)]">% (either direction)</span>
          </div>
        </label>
      </div>

      <div className="mt-5">
        <span className="text-[13px] font-medium text-[var(--color-ink)]">Alert me on these announcement categories</span>
        <div className="mt-2 flex flex-wrap gap-1.5">
          {ALL_ANNOUNCEMENT_CATEGORIES.map((cat) => (
            <button
              key={cat}
              onClick={() => toggleCategory(cat)}
              className={`rounded-full border px-2.5 py-1 text-[11px] font-medium transition-colors ${
                config.alert_categories.includes(cat)
                  ? "border-[var(--color-accent)] bg-[var(--color-accent-soft)] text-[var(--color-accent)]"
                  : "border-[var(--color-border)] text-[var(--color-ink-faint)] hover:text-[var(--color-ink-muted)]"
              }`}
            >
              {categoryLabel(cat)}
            </button>
          ))}
        </div>
      </div>

      <div className="mt-5 flex items-center gap-3">
        <button
          onClick={handleSave}
          disabled={saveStatus === "saving"}
          className="rounded-lg bg-[var(--color-accent)] px-4 py-2 text-[13px] font-medium text-white hover:opacity-90 disabled:opacity-60"
        >
          {saveStatus === "saving" ? "Saving…" : "Save configuration"}
        </button>
        {saveStatus === "saved" && <span className="text-[13px] text-[var(--color-positive)]">Saved</span>}
        {saveStatus === "error" && <span className="text-[13px] text-[var(--color-negative)]">Failed to save</span>}
      </div>
    </div>
  );
}
