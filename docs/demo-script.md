# FINN — Demo Walkthrough (≈4-5 minutes)

This script uses only real local demo data reproducible from this repository —
no fabricated values, no live Supabase integration claimed. Run the backend and
frontend locally first (see root `README.md` → Setup).

## Before you start: seed the demo data (one-time, local only)

The data store ships empty by design. Seed two related Push disclosures and run
one real Pull ingestion:

```bash
# 1. Two related disclosures for the same quarter (Push will group these into one event)
curl -X POST http://127.0.0.1:8000/api/announcements/import -H "Content-Type: application/json" -d '{
  "ticker": "HDFCBANK",
  "title": "Unaudited Financial Results for the quarter ended June 30, 2026",
  "filed_at": "'"$(date -u +%Y-%m-%dT%H:%M:%SZ)"'",
  "original_source_url": "https://example.invalid/hdfcbank-q1fy27-results.pdf"
}'

curl -X POST http://127.0.0.1:8000/api/announcements/import -H "Content-Type: application/json" -d '{
  "ticker": "HDFCBANK",
  "title": "Transcript of earnings call for Q1 FY27",
  "filed_at": "'"$(date -u +%Y-%m-%dT%H:%M:%SZ)"'",
  "original_source_url": "https://example.invalid/hdfcbank-q1fy27-transcript.pdf"
}'

# 2. Two quarters of financial_metrics, so "What changed?" has real numbers to compare
curl -X POST http://127.0.0.1:8000/api/financials/import -H "Content-Type: application/json" -d '{
  "ticker": "HDFCBANK", "period": "Q1FY27", "basis": "standalone",
  "revenue": 531.7, "pat": 181.6, "currency": "INR", "unit": "bn"
}'
curl -X POST http://127.0.0.1:8000/api/financials/import -H "Content-Type: application/json" -d '{
  "ticker": "HDFCBANK", "period": "Q4FY26", "basis": "standalone",
  "revenue": 462.8, "pat": 192.2, "currency": "INR", "unit": "bn"
}'

# 3. Real local document ingestion (genuine HDFC Q1 FY27 earnings presentation) for Pull
cd backend
.venv/bin/python scripts/ingest_document.py \
  --pdf ../scripts/spikes/fundamentals_access_spike/documents/hdfcbank_earnings_presentation.pdf \
  --ticker HDFCBANK --doc-type investor_presentation --reporting-period Q1FY27 \
  --source-url "https://www.hdfc.bank.in/content/dam/hdfcbankpws/in/en/pdf/about-us/financial-results/2026-2027/quarter-1/q1fy27-earnings-presentation.pdf"
```

## Walkthrough

1. **Open FINN** at `http://localhost:3000`. Point out the mobile-first layout
   (resize the window, or open on a phone) — this is the same app, not a
   separate mobile build.
2. **Portfolio** (`/portfolio`) — the tracked watchlist; point out it's a fixed
   seed list, not a live exchange feed (stated honestly in the empty states).
3. **Daily Intelligence** (`/`) — the Push feed, defaulted to the "By event" view.
4. **Point at the grouped HDFCBANK card** — two source disclosures (results +
   transcript) collapsed into **one** event, not two duplicate high-priority
   alerts. Expand "2 source documents" to show both are preserved individually
   with their own links.
5. **Read the "Why it matters" line aloud** — it names the real computed
   numbers (e.g. "Revenue grew 14.9% QoQ; Profit after tax declined 5.5% QoQ")
   and the financial-change rows below it, each showing the actual reported
   figure, not just a percentage.
6. **Click "Research this event"** — this is the Push → Pull connection; the
   Research page opens pre-filled with the ticker and a question suited to the
   event type, and asks automatically.
7. **Show the returned evidence** — point out the `generation_note` stating no
   LLM answer-generation is configured; this is retrieval, stated as such.
8. **Switch to a direct Pull question**: type "What was HDFC Bank's net
   interest income in Q1 FY27?" and click Ask. Point out:
   - The exact reported figure (335.3) in a highlighted "Reported figure" card.
   - Its citation: metric, period, **page 4**, and a clickable source-document link.
   - The supporting-evidence card below showing the real extracted table text.
9. **Explain the reliability flags** — any evidence card badged "Structured
   table" vs. "Prose" vs. "Needs manual review"; this is the
   `chunk_type`/`needs_manual_review` distinction, never silently hidden.
10. **Demonstrate insufficient evidence** — ask something not in this one
    document, e.g. "What was HDFC Bank's total shareholders equity as per the
    audited balance sheet?" and show the honest `insufficient_evidence`
    response rather than a fabricated number.
11. **Close by stating plainly what FINN does not yet claim**:
    - No LLM generates prose analysis — every answer is retrieval or exact
      extraction, cited.
    - Only this one document has been validated end-to-end; the pipeline is
      built to generalize to any ticker, but that's a design claim, not yet a
      tested one beyond HDFC.
    - No live NSE/BSE feed — filings are imported manually, by design, because
      direct automated access to NSE/BSE was confirmed blocked.
    - No guidance-vs-actual or narrative tracking yet — this document has no
      forward-looking transcript content to track.

## What NOT to do during the demo

- Don't claim this is reading live Supabase — this walkthrough uses local
  JSON-fallback data you just seeded.
- Don't click "Save configuration" on the Alerts page expecting it to persist
  anywhere but your local instance.
- Don't ask a question implying a second company's data should leak in — company
  isolation is a feature to demonstrate, not something to accidentally disprove
  with a malformed example.
