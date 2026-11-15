"use client";

import { useState } from "react";

const WINDOW_OPTIONS = [
  { label: "24h", hours: 24 },
  { label: "7 days", hours: 24 * 7 },
  { label: "30 days", hours: 24 * 30 },
] as const;

export type DateRangeSelection =
  | { mode: "window"; windowHours: number }
  | { mode: "custom"; start: string; end: string }; // ISO instants, UTC day boundaries

interface DateRangeFilterProps {
  value: DateRangeSelection;
  onChange: (selection: DateRangeSelection) => void;
}

/** Shared by DigestFeed and EventsFeed - both views filter the same underlying
 * announcement data by the same window/custom-range semantics the backend's
 * resolve_window() already implements (GET /api/digest and /api/events both
 * accept window_hours OR start+end). Custom-range dates are sent as UTC day
 * boundaries (00:00:00.000Z / 23:59:59.999Z) - explicit rather than ambiguous,
 * since an HTML date input has no timezone of its own. */
export function DateRangeFilter({ value, onChange }: DateRangeFilterProps) {
  const [showCustom, setShowCustom] = useState(value.mode === "custom");
  const [startDate, setStartDate] = useState(value.mode === "custom" ? value.start.slice(0, 10) : "");
  const [endDate, setEndDate] = useState(value.mode === "custom" ? value.end.slice(0, 10) : "");
  const [validationError, setValidationError] = useState<string | null>(null);

  function selectWindow(hours: number) {
    setShowCustom(false);
    setValidationError(null);
    onChange({ mode: "window", windowHours: hours });
  }

  function applyCustomRange() {
    if (!startDate || !endDate) {
      setValidationError("Pick both a start and an end date.");
      return;
    }
    if (startDate > endDate) {
      setValidationError("Start date can't be after the end date.");
      return;
    }
    setValidationError(null);
    onChange({
      mode: "custom",
      start: `${startDate}T00:00:00.000Z`,
      end: `${endDate}T23:59:59.999Z`,
    });
  }

  function clearCustomRange() {
    setStartDate("");
    setEndDate("");
    setValidationError(null);
    setShowCustom(false);
    onChange({ mode: "window", windowHours: 24 });
  }

  const isWindowActive = (hours: number) => value.mode === "window" && value.windowHours === hours;

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        {WINDOW_OPTIONS.map((opt) => (
          <button
            key={opt.hours}
            onClick={() => selectWindow(opt.hours)}
            className={`rounded-full px-3 py-1.5 text-[13px] font-medium transition-colors ${
              isWindowActive(opt.hours)
                ? "bg-[var(--color-accent)] text-white"
                : "border border-[var(--color-border)] bg-[var(--color-surface)] text-[var(--color-ink-muted)] hover:bg-[var(--color-canvas)]"
            }`}
          >
            {opt.label}
          </button>
        ))}
        <button
          onClick={() => setShowCustom((v) => !v)}
          className={`rounded-full px-3 py-1.5 text-[13px] font-medium transition-colors ${
            value.mode === "custom"
              ? "bg-[var(--color-accent)] text-white"
              : "border border-[var(--color-border)] bg-[var(--color-surface)] text-[var(--color-ink-muted)] hover:bg-[var(--color-canvas)]"
          }`}
        >
          Custom
        </button>
      </div>

      {showCustom && (
        <div className="flex flex-wrap items-end gap-2 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-3">
          <label className="flex flex-col gap-1">
            <span className="text-[11px] font-medium text-[var(--color-ink-faint)]">Start date</span>
            <input
              type="date"
              value={startDate}
              max={endDate || undefined}
              onChange={(e) => setStartDate(e.target.value)}
              className="rounded-lg border border-[var(--color-border-strong)] bg-[var(--color-canvas)] px-2.5 py-1.5 text-sm text-[var(--color-ink)]"
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-[11px] font-medium text-[var(--color-ink-faint)]">End date</span>
            <input
              type="date"
              value={endDate}
              min={startDate || undefined}
              onChange={(e) => setEndDate(e.target.value)}
              className="rounded-lg border border-[var(--color-border-strong)] bg-[var(--color-canvas)] px-2.5 py-1.5 text-sm text-[var(--color-ink)]"
            />
          </label>
          <button
            onClick={applyCustomRange}
            className="rounded-lg bg-[var(--color-accent)] px-3 py-1.5 text-[13px] font-medium text-white hover:opacity-90"
          >
            Apply
          </button>
          {value.mode === "custom" && (
            <button
              onClick={clearCustomRange}
              className="rounded-lg border border-[var(--color-border)] px-3 py-1.5 text-[13px] font-medium text-[var(--color-ink-muted)] hover:bg-[var(--color-canvas)]"
            >
              Clear
            </button>
          )}
          <span className="basis-full text-[11px] text-[var(--color-ink-faint)]">Dates are treated as full UTC days.</span>
        </div>
      )}

      {validationError && <p className="text-[12px] text-[var(--color-negative)]">{validationError}</p>}
    </div>
  );
}
