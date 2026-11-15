/**
 * Single source of truth for signed-percentage movement colour/labelling.
 * Never derive direction from a company's business "status" (events,
 * announcements) — only from the actual numeric percentage, and missing
 * data is always neutral, never positive.
 */
export type MovementTone = "positive" | "negative" | "neutral";

export function movementTone(pct: number | null | undefined): MovementTone {
  if (pct === null || pct === undefined) return "neutral";
  if (pct > 0) return "positive";
  if (pct < 0) return "negative";
  return "neutral";
}

export const MOVEMENT_TEXT_CLASS: Record<MovementTone, string> = {
  positive: "text-[var(--color-positive)]",
  negative: "text-[var(--color-negative)]",
  neutral: "text-[var(--color-ink-faint)]",
};

export const MOVEMENT_DOT_CLASS: Record<MovementTone, string> = {
  positive: "bg-[var(--color-positive)]",
  negative: "bg-[var(--color-negative)]",
  neutral: "bg-[var(--color-ink-faint)]",
};
