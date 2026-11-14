"use client";

import { useEffect, useState } from "react";
import { ApiError, askResearch } from "@/lib/api";
import type { HybridEvidenceChunk, ResearchAskResponse } from "@/types/api";

// A small fixed menu, not a free-form agent (see backend app.services.research_prompts,
// which this mirrors by hand - a static 6-item list isn't worth a network round trip).
const REUSABLE_PROMPTS: { label: string; question: string; needsSupportingDocuments?: boolean }[] = [
  { label: "Latest quarterly results", question: "Summarize the latest reported revenue, profitability and key financial metrics." },
  { label: "Compare with previous periods", question: "Compare the latest reported revenue, profitability and key financial metrics with the previous quarter and the corresponding quarter last year." },
  { label: "Cash-flow quality", question: "What does the available disclosure show about operating cash flow relative to reported profit?" },
  { label: "Recent material announcement", question: "Explain the company's most recent material announcement and its disclosed implications." },
  { label: "Risks or unusual movements", question: "What risks or unusual financial movements are disclosed in the available documents?" },
  { label: "Management guidance", question: "What guidance or forward-looking outlook has management disclosed, and how does it compare with actual results?", needsSupportingDocuments: true },
];

const CHUNK_TYPE_LABEL: Record<string, string> = {
  prose: "Prose",
  table_row_group: "Structured table",
  table_unparsed: "Unparsed table (needs review)",
};

function EvidenceCard({ chunk }: { chunk: HybridEvidenceChunk }) {
  const unreliable = chunk.chunk_type === "table_unparsed" || chunk.needs_manual_review;
  return (
    <div
      className={`rounded-xl border p-4 ${
        unreliable ? "border-amber-400/40 bg-amber-500/5" : "border-[var(--color-border)] bg-[var(--color-surface)]"
      }`}
    >
      <div className="flex flex-wrap items-center gap-2 text-[11px] font-medium">
        <span className="rounded-full bg-[var(--color-accent-soft)] px-2 py-0.5 text-[var(--color-accent)]">
          {CHUNK_TYPE_LABEL[chunk.chunk_type] ?? chunk.chunk_type}
        </span>
        {unreliable && (
          <span className="rounded-full bg-amber-500/15 px-2 py-0.5 text-amber-700">Needs manual review — not verified</span>
        )}
        {chunk.page_reference != null && (
          <span className="text-[var(--color-ink-faint)]">page {chunk.page_reference}</span>
        )}
        {chunk.reporting_period && <span className="text-[var(--color-ink-faint)]">{chunk.reporting_period}</span>}
      </div>
      <p className="mt-2 whitespace-pre-wrap text-[13px] leading-relaxed text-[var(--color-ink)]">{chunk.chunk_text}</p>
      {chunk.original_source_url && (
        <a
          href={chunk.original_source_url}
          target="_blank"
          rel="noreferrer"
          className="mt-2 inline-block text-[12px] font-medium text-[var(--color-accent)] hover:underline"
        >
          View source document →
        </a>
      )}
    </div>
  );
}

function ResultView({ result }: { result: ResearchAskResponse }) {
  return (
    <div className="mt-4 space-y-4">
      <p className="text-[11px] italic text-[var(--color-ink-faint)]">{result.generation_note}</p>

      {result.answer_type === "numeric_fact" && result.numeric_answer && (
        <div className="rounded-xl border border-[var(--color-accent)]/30 bg-[var(--color-accent-soft)] p-4">
          <div className="text-[11px] font-medium uppercase tracking-wide text-[var(--color-accent)]">Reported figure</div>
          <div className="mt-1 text-[24px] font-semibold text-[var(--color-ink)]">{result.numeric_answer.value}</div>
          <div className="mt-1 text-[13px] text-[var(--color-ink-muted)]">
            {result.numeric_answer.metric_label}
            {result.numeric_answer.period_label ? ` — ${result.numeric_answer.period_label}` : ""}
            {result.numeric_answer.page_reference != null ? ` — page ${result.numeric_answer.page_reference}` : ""}
          </div>
          {result.numeric_answer.original_source_url && (
            <a
              href={result.numeric_answer.original_source_url}
              target="_blank"
              rel="noreferrer"
              className="mt-2 inline-block text-[12px] font-medium text-[var(--color-accent)] hover:underline"
            >
              View source document →
            </a>
          )}
        </div>
      )}

      {result.answer_type === "insufficient_evidence" && (
        <div className="rounded-xl border border-dashed border-[var(--color-border-strong)] bg-[var(--color-surface)] p-4">
          <div className="text-[13px] font-semibold text-[var(--color-ink)]">Insufficient evidence</div>
          <p className="mt-1 text-[13px] text-[var(--color-ink-muted)]">{result.insufficient_evidence_reason}</p>
        </div>
      )}

      {result.evidence.length > 0 && (
        <div>
          <h3 className="mb-2 text-[13px] font-semibold uppercase tracking-wide text-[var(--color-ink-faint)]">
            {result.answer_type === "evidence_digest" ? "Relevant evidence" : "Supporting evidence"}
          </h3>
          <div className="space-y-3">
            {result.evidence.map((chunk) => (
              <EvidenceCard key={chunk.chunk_id} chunk={chunk} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

export function ResearchAskForm({
  initialTicker,
  initialQuestion,
}: {
  initialTicker?: string;
  initialQuestion?: string;
}) {
  const [ticker, setTicker] = useState(initialTicker?.toUpperCase() || "HDFCBANK");
  const [question, setQuestion] = useState(initialQuestion || "");
  const [status, setStatus] = useState<"idle" | "loading" | "error">("idle");
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<ResearchAskResponse | null>(null);

  async function runAsk(askTicker: string, askQuestion: string) {
    if (!askTicker.trim() || askQuestion.trim().length < 3) return;
    setStatus("loading");
    setError(null);
    try {
      const res = await askResearch(askTicker.trim().toUpperCase(), askQuestion.trim());
      setResult(res);
      setStatus("idle");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Something went wrong asking FINN.");
      setResult(null);
      setStatus("error");
    }
  }

  // Arrived here from an event card (Push → Pull) with both fields already
  // filled in — ask automatically rather than requiring a redundant click.
  useEffect(() => {
    if (initialTicker && initialQuestion) {
      // Deferred to a microtask: calling a setState-triggering function
      // synchronously in an effect body risks cascading renders.
      queueMicrotask(() => runAsk(initialTicker, initialQuestion));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    await runAsk(ticker, question);
  }

  return (
    <div>
      <div className="mb-3 flex flex-wrap gap-1.5">
        {REUSABLE_PROMPTS.map((p) => (
          <button
            key={p.label}
            type="button"
            onClick={() => {
              setQuestion(p.question);
              runAsk(ticker, p.question);
            }}
            title={p.needsSupportingDocuments ? "Requires a supporting document (e.g. a transcript) — may return insufficient evidence if none exists yet" : undefined}
            className="rounded-full border border-[var(--color-border)] px-2.5 py-1 text-[11px] font-medium text-[var(--color-ink-faint)] hover:border-[var(--color-accent)] hover:text-[var(--color-accent)]"
          >
            {p.label}
            {p.needsSupportingDocuments && " *"}
          </button>
        ))}
      </div>

      <form onSubmit={handleSubmit} className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-4">
        <div className="flex flex-col gap-3 sm:flex-row">
          <input
            value={ticker}
            onChange={(e) => setTicker(e.target.value)}
            placeholder="Ticker (e.g. HDFCBANK)"
            className="w-full rounded-lg border border-[var(--color-border-strong)] bg-[var(--color-canvas)] px-3 py-2 text-sm text-[var(--color-ink)] sm:w-40"
          />
          <input
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder="Ask about this company's own filings, e.g. What was the net interest income in Q1 FY27?"
            className="w-full flex-1 rounded-lg border border-[var(--color-border-strong)] bg-[var(--color-canvas)] px-3 py-2 text-sm text-[var(--color-ink)]"
          />
        </div>
        <button
          type="submit"
          disabled={status === "loading"}
          className="mt-3 rounded-lg bg-[var(--color-accent)] px-4 py-2 text-[13px] font-medium text-white hover:opacity-90 disabled:opacity-60"
        >
          {status === "loading" ? "Searching primary sources…" : "Ask"}
        </button>
      </form>

      {error && (
        <div className="mt-4 rounded-xl border border-[var(--color-negative)]/30 bg-[var(--color-negative)]/5 p-4 text-sm text-[var(--color-negative)]">
          {error}
        </div>
      )}

      {result && <ResultView result={result} />}
    </div>
  );
}
