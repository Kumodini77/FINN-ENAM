"use client";

import { useEffect, useMemo, useState } from "react";
import type { DailyBar } from "@/types/api";

// Minimum real closed bars required before drawing a trend line at all — a
// 2-3 point "trend" is too noisy to color meaningfully, so below this we
// show "Not enough history" instead of a misleading line (per the explicit
// instruction: never color a multi-week chart off a single day's move, and
// never render a line when there's insufficient real history).
const MIN_BARS = 5;
const ANIMATION_MS = 900;

function usePrefersReducedMotion(): boolean {
  const [reduced, setReduced] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    // Deferred to a microtask — same pattern as ThemeToggle/ResearchAskForm's
    // initial-state effects: calling setState synchronously in an effect
    // body risks cascading renders.
    queueMicrotask(() => setReduced(mq.matches));
    const listener = () => setReduced(mq.matches);
    mq.addEventListener("change", listener);
    return () => mq.removeEventListener("change", listener);
  }, []);
  return reduced;
}

export function Sparkline({ bars, width = 96, height = 32 }: { bars: DailyBar[]; width?: number; height?: number }) {
  const [animated, setAnimated] = useState(false);
  const reducedMotion = usePrefersReducedMotion();
  const datasetKey = bars.map((b) => `${b.trade_date}:${b.close}`).join(",");

  // Plays the draw-on-load animation exactly once per dataset (the
  // dependency is the dataset's own content, not just component mount) —
  // never re-animates on an ordinary re-render with the same bars. This
  // effect only toggles which portion of the REAL, already-computed line is
  // visible; it never changes the displayed price or percentage.
  useEffect(() => {
    queueMicrotask(() => setAnimated(false));
    const raf = requestAnimationFrame(() => setAnimated(true));
    return () => cancelAnimationFrame(raf);
  }, [datasetKey]);

  const geometry = useMemo(() => {
    if (bars.length < MIN_BARS) return null;
    const closes = bars.map((b) => b.close);
    const min = Math.min(...closes);
    const max = Math.max(...closes);
    const range = max - min || 1;
    const isPositive = closes[closes.length - 1] >= closes[0];

    const points = closes.map((c, i) => {
      const x = (i / (closes.length - 1)) * width;
      const y = height - ((c - min) / range) * (height - 4) - 2;
      return [x, y] as const;
    });

    let length = 0;
    for (let i = 1; i < points.length; i++) {
      length += Math.hypot(points[i][0] - points[i - 1][0], points[i][1] - points[i - 1][1]);
    }

    const linePath = points.map(([x, y], i) => `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
    const fillPath = `${linePath} L${width},${height} L0,${height} Z`;
    const [lastX, lastY] = points[points.length - 1];
    return { linePath, fillPath, length, lastX, lastY, isPositive };
  }, [bars, width, height]);

  if (!geometry) {
    return (
      <div
        style={{ width, height }}
        className="flex items-center justify-center text-[10px] text-[var(--color-ink-faint)]"
      >
        Not enough history
      </div>
    );
  }

  const color = geometry.isPositive ? "var(--color-positive)" : "var(--color-negative)";
  const drawn = reducedMotion || animated;
  const dashStyle = reducedMotion
    ? undefined
    : {
        strokeDasharray: geometry.length,
        strokeDashoffset: animated ? 0 : geometry.length,
        transition: `stroke-dashoffset ${ANIMATION_MS}ms cubic-bezier(0.16, 1, 0.3, 1)`,
      };

  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} className="overflow-visible">
      <path d={geometry.fillPath} fill={color} opacity={drawn ? 0.08 : 0} stroke="none" style={{ transition: `opacity ${ANIMATION_MS}ms ease-out` }} />
      <path d={geometry.linePath} fill="none" stroke={color} strokeWidth={1.6} strokeLinecap="round" strokeLinejoin="round" style={dashStyle} />
      {drawn && <circle cx={geometry.lastX} cy={geometry.lastY} r={2} fill={color} />}
    </svg>
  );
}
