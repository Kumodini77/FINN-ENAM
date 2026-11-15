"use client";

import { useEffect, useState } from "react";
import { ApiError, askResearch } from "@/lib/api";
import type { HybridEvidenceChunk, ResearchAskResponse } from "@/types/api";

// A small fixed menu, not a free-form agent (see backend app.services.research_prompts,
// which this mirrors by hand - a static list isn't worth a network round trip).
const REUSABLE_PROMPTS: { label: string; question: string; needsSupportingDocuments?: boolean }[] = [
  { label: "Summarise the latest results", question: "Summarize the latest reported revenue, profitability and key financial metrics." },
  { label: "Is revenue growth improving?", question: "Compare the latest reported revenue with the previous quarter and the corresponding quarter last year." },
  { label: "Why did margins change?", question: "What does the available disclosure show about changes in operating margin?" },
  { label: "Is profit converting into cash?", question: "What does the available disclosure show about operating cash flow relative to reported profit?" },
  { label: "What are the biggest risks?", question: "What risks or unusual financial movements are disclosed in the available documents?" },
  { label: "Has management delivered on its promises?", question: "What guidance or forward-looking outlook has management disclosed, and how does it compare with actual results?", needsSupportingDocuments: true },
  { label: "Compare the last four quarters", question: "Compare the latest reported revenue, profitability and key financial metrics across the last four quarters." },
];

// Contextual "what to check next" suggestions — deterministic, keyword-based,
// never a model call. Each is just another question this same form can run.
const FOLLOW_UP_RULES: { keywords: string[]; suggestions: string[] }[] = [
  {
    keywords: ["revenue", "sales", "growth", "results"],
    suggestions: ["Why did margins change?", "Is profit converting into cash?", "What guidance has management given on this?"],
  },
  {
    keywords: ["margin", "profit", "ebitda", "pat"],
    suggestions: ["Is profit converting into cash?", "Compare the last four quarters.", "What are the biggest risks?"],
  },
  {
    keywords: ["cash", "debt", "borrowing"],
    suggestions: ["What are the biggest risks?", "Compare the last four quarters.", "Why did margins change?"],
  },
  {
    keywords: ["guidance", "promise", "outlook", "forecast"],
    suggestions: ["Summarize the latest reported revenue, profitability and key financial metrics.", "What are the biggest risks?"],
  },
];
const DEFAULT_FOLLOW_UPS = ["Compare the last four quarters.", "What are the biggest risks?", "Is profit converting into cash?"];

function followUpsFor(question: string): string[] {
  const lower = question.toLowerCase();
  for (const rule of FOLLOW_UP_RULES) {
    if (rule.keywords.some((k) => lower.includes(k))) return rule.suggestions;
  }
  return DEFAULT_FOLLOW_UPS;
}

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
        unreliable ? "border-[var(--color-warning)]/40 bg-[var(--color-warning-soft)]" : "border-[var(--color-border)] bg-[var(--color-surface)]"
      }`}
    >
      <div className="flex flex-wrap items-center gap-2 text-[11px] font-medium">
        <span className="rounded-full bg-[var(--color-accent-soft)] px-2 py-0.5 text-[var(--color-accent)]">
          {CHUNK_TYPE_LABEL[chunk.chunk_type] ?? chunk.chunk_type}
        </span>
        {unreliable && (
          <span className="rounded-full bg-[var(--color-warning-soft)] px-2 py-0.5 text-[var(--color-warning)]">Needs manual review — not verified</span>
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

const VIEW_CONFIG: Record<string, { label: string; tone: string; dot: string }> = {
  numeric_fact: { label: "Reported figure found", tone: "text-[var(--color-teal)]", dot: "bg-[var(--color-teal)]" },
  evidence_digest: { label: "Evidence found", tone: "text-[var(--color-teal)]", dot: "bg-[var(--color-teal)]" },
  ambiguous_metric: { label: "Needs clarification", tone: "text-[var(--color-warning)]", dot: "bg-[var(--color-warning)]" },
  insufficient_evidence: { label: "Insufficient evidence", tone: "text-[var(--color-ink-faint)]", dot: "bg-[var(--color-ink-faint)]" },
};

function FinnsView({ result, onAsk }: { result: ResearchAskResponse; onAsk: (q: string) => void }) {
  const config = VIEW_CONFIG[result.answer_type] ?? VIEW_CONFIG.evidence_digest;

  let body: React.ReactNode;
  if (result.answer_type === "numeric_fact" && result.numeric_answer) {
    body = (
      <>
        <p className="text-[13px] leading-relaxed text-[var(--color-ink-muted)]">
          FINN found one specific, cited figure that directly answers this question — see “Reported facts” below. This is a
          single reported number, not a trend judgement; ask a follow-up to compare it with another period.
        </p>
      </>
    );
  } else if (result.answer_type === "evidence_digest") {
    body = (
      <p className="text-[13px] leading-relaxed text-[var(--color-ink-muted)]">
        FINN found {result.evidence.length} relevant passage{result.evidence.length === 1 ? "" : "s"} from this company&apos;s own
        filings. No single reported number matched this question exactly — read the evidence below for the full context.
      </p>
    );
  } else if (result.answer_type === "ambiguous_metric") {
    body = (
      <>
        <p className="text-[13px] leading-relaxed text-[var(--color-ink-muted)]">
          More than one reported line item matches this question&apos;s wording, and FINN will not guess which one you meant:
        </p>
        <ul className="mt-2 flex flex-wrap gap-1.5">
          {(result.metric_alternatives ?? []).map((m) => (
            <li key={m} className="rounded-full bg-[var(--color-warning-soft)] px-2.5 py-1 text-[12px] font-medium text-[var(--color-warning)]">
              {m}
            </li>
          ))}
        </ul>
      </>
    );
  } else {
    body = <p className="text-[13px] leading-relaxed text-[var(--color-ink-muted)]">{result.insufficient_evidence_reason}</p>;
  }

  const followUps = result.answer_type === "insufficient_evidence" ? [] : followUpsFor(result.question);

  return (
    <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-4">
      <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-wide text-[var(--color-ink-faint)]">
        <span className={`inline-block h-2 w-2 rounded-full ${config.dot}`} />
        FINN&apos;s view
      </div>
      <div className={`mt-1 text-[15px] font-semibold ${config.tone}`}>{config.label}</div>
      <div className="mt-2">{body}</div>

      {followUps.length > 0 && (
        <div className="mt-4 border-t border-[var(--color-border)] pt-3">
          <div className="text-[11px] font-semibold uppercase tracking-wide text-[var(--color-ink-faint)]">What should I check next?</div>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {followUps.map((q) => (
              <button
                key={q}
                type="button"
                onClick={() => onAsk(q)}
                className="rounded-full border border-[var(--color-border)] px-2.5 py-1 text-[12px] font-medium text-[var(--color-accent)] hover:border-[var(--color-accent)] hover:bg-[var(--color-accent-soft)]"
              >
                {q}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function ResultView({ result, onAsk }: { result: ResearchAskResponse; onAsk: (q: string) => void }) {
  return (
    <div className="mt-4 space-y-4">
      <FinnsView result={result} onAsk={onAsk} />

      {result.answer_type === "numeric_fact" && result.numeric_answer && (
        <div>
          <h3 className="mb-2 text-[13px] font-semibold uppercase tracking-wide text-[var(--color-ink-faint)]">Reported facts</h3>
          <div className="rounded-xl border border-[var(--color-accent)]/30 bg-[var(--color-accent-soft)] p-4">
            <div className="text-[11px] font-medium uppercase tracking-wide text-[var(--color-accent)]">{result.numeric_answer.metric_label}</div>
            <div className="mt-1 text-[24px] font-semibold text-[var(--color-ink)]">{result.numeric_answer.value}</div>
            <div className="mt-1 text-[13px] text-[var(--color-ink-muted)]">
              {result.numeric_answer.period_label ? result.numeric_answer.period_label : "Period not confirmed"}
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
        </div>
      )}

      {result.evidence.length > 0 && (
        <details className="group rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)]">
          <summary className="cursor-pointer px-4 py-3 text-[13px] font-semibold text-[var(--color-ink)]">
            View supporting documents and evidence ({result.evidence.length})
          </summary>
          <div className="space-y-3 border-t border-[var(--color-border)] p-4">
            {result.evidence.map((chunk) => (
              <EvidenceCard key={chunk.chunk_id} chunk={chunk} />
            ))}
          </div>
        </details>
      )}

      <p className="flex items-center gap-1.5 text-[11px] text-[var(--color-ink-faint)]">
        <span className="inline-block h-1.5 w-1.5 rounded-full bg-[var(--color-ink-faint)]" />
        {result.generation_note}
      </p>
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
      <form onSubmit={handleSubmit} className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-4">
        <div className="flex flex-col gap-3 sm:flex-row">
          <input
            value={ticker}
            onChange={(e) => setTicker(e.target.value)}
            placeholder="Ticker or company name"
            aria-label="Company ticker or name"
            className="w-full rounded-lg border border-[var(--color-border-strong)] bg-[var(--color-canvas)] px-3 py-2 text-sm text-[var(--color-ink)] sm:w-40"
          />
          <input
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder="Search a company or ask FINN a question…"
            aria-label="Research question"
            className="w-full flex-1 rounded-lg border border-[var(--color-border-strong)] bg-[var(--color-canvas)] px-3 py-2 text-sm text-[var(--color-ink)]"
          />
        </div>
        <button
          type="submit"
          disabled={status === "loading"}
          className="mt-3 rounded-lg bg-[var(--color-accent)] px-4 py-2 text-[13px] font-medium text-white hover:opacity-90 disabled:opacity-60"
        >
          {status === "loading" ? "Searching primary sources…" : "Ask FINN"}
        </button>
      </form>

      <div className="mt-3 flex flex-wrap gap-1.5">
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
          </button>
        ))}
      </div>

      {error && (
        <div className="mt-4 rounded-xl border border-[var(--color-negative)]/30 bg-[var(--color-negative)]/5 p-4 text-sm text-[var(--color-negative)]">
          {error}
        </div>
      )}

      {result && <ResultView result={result} onAsk={(q) => runAsk(ticker, q)} />}
    </div>
  );
}
