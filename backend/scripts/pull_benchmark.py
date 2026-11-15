#!/usr/bin/env python3
"""Phase 6 Section D - repeatable Pull benchmark against the live, running
backend. Not a pytest suite (that would need mocked evidence); this hits the
real /api/research/ask endpoint over real Supabase-backed retrieval, so it can
be re-run after any extraction change to see the actual effect on real
documents. Prints a markdown table; does not assert/fail - this is a report,
not a gate."""

import json
import sys
import urllib.parse
import urllib.request

BASE = "http://localhost:8000/api/research/ask"

CASES = [
    # (ticker, question, note)
    ("HDFCBANK", "What was HDFC Bank's net interest income in Q1 FY27?", "ground truth 335.3, page 4"),
    ("HDFCBANK", "What was HDFC Bank's gross NPA in Q1 FY27?", "chart-derived, expect evidence_digest"),
    ("HDFCBANK", "What was HDFC Bank's total debt in Q1 FY27?", "unsupported metric"),
    ("SUNPHARMA", "What was Sun Pharma's sales in Q2 FY27?", "ground truth 1,61,000"),
    ("SUNPHARMA", "What was Sun Pharma's PAT in Q2 FY27?", "expect ambiguous_metric Reported/Adjusted"),
    ("SUNPHARMA", "What was Sun Pharma's reported PAT in Q2 FY27?", "ground truth 19,885"),
    ("SUNPHARMA", "What was Sun Pharma's sales in Q3 FY99?", "unavailable period"),
    ("SBIN", "What was SBI's operating income in Q2 FY27?", "complex merged header"),
    ("ICICIBANK", "What was ICICI Bank's profit after tax in Q2 FY27?", "multi-line label table"),
    ("RELIANCE", "What was Reliance's EBITDA margin in Q2 FY27?", "KPI table"),
    ("RELIANCE", "What was Reliance's EBITDA in Q2 FY27?", "expect ambiguous_metric (2 EBITDA-adjacent rows)"),
    ("WIPRO", "What was Wipro's IT Services Revenue in Q2 FY27?", "ground truth 246,670 (apostrophe-period fix)"),
    ("M&M", "What was Mahindra's tractor revenue in Q2 FY27?", "segment table"),
    ("ITC", "What was ITC's net profit in Q2 FY27?", "no table_row_group chunks"),
    ("TATASTEEL", "What were Tata Steel's employee benefits expenses in Q2 FY27?", "multi-line label table"),
    ("LT", "What was L&T's revenue from operations in Q2 FY27?", "merged comparison header"),
    ("TRENT", "What was Trent's revenue in Q2 FY27?", "no table_row_group chunks"),
    ("LICI", "What was LIC's renewal premium in Q2 FY27?", "multi-column premium table"),
    ("ADANIPORTS", "What was Adani Ports' total revenue in Q2 FY27?", "segment table"),
    ("HDFCBANK", "What was Reliance's sales in Q2 FY27?", "cross-company isolation check (wrong ticker)"),
]


def ask(ticker: str, question: str) -> dict:
    q = urllib.parse.urlencode({"ticker": ticker, "question": question})
    with urllib.request.urlopen(f"{BASE}?{q}") as r:
        return json.load(r)


def main() -> None:
    print("| Ticker | Question | Answer type | Value | Period | Page | Unit | Note |")
    print("|---|---|---|---|---|---|---|---|")
    results = []
    for ticker, question, note in CASES:
        try:
            r = ask(ticker, question)
        except Exception as e:
            print(f"| {ticker} | {question} | ERROR | - | - | - | - | {e} |")
            continue
        na = r.get("numeric_answer")
        answer_type = r.get("answer_type")
        value = na["value"] if na else (f"ambiguous: {r.get('metric_alternatives')}" if r.get("metric_alternatives") else "-")
        period = na["period_label"] if na else "-"
        page = na["page_reference"] if na else "-"
        unit = na["unit_scale"] if na else "-"
        evidence_tickers = {e["company_ticker"] for e in r.get("evidence", [])}
        isolation_note = ""
        if evidence_tickers and evidence_tickers != {ticker.strip().upper()} and ticker.strip().upper() in evidence_tickers | {ticker.strip().upper()}:
            pass
        print(f"| {ticker} | {question} | {answer_type} | {value} | {period} | {page} | {unit} | {note} |")
        results.append((ticker, question, answer_type, evidence_tickers))

    print()
    print("Cross-company isolation check (every evidence set should equal exactly {ticker}):")
    for ticker, question, answer_type, evidence_tickers in results:
        if evidence_tickers and evidence_tickers != {ticker.strip().upper()}:
            print(f"  LEAK CANDIDATE: {ticker} | {question} -> evidence tickers {evidence_tickers}")
    print("  (no output above this line means no leaks detected)")


if __name__ == "__main__":
    main()
