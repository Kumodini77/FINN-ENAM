# FINN Implementation Roadmap (post-submission)

Written: 2026-11-15, the ENAM submission deadline. This roadmap sequences
the gaps identified in `FINN_PRODUCT_GAP_ANALYSIS.md` for work *after*
today, in priority order. Nothing here was attempted today beyond what
`FINN_PRODUCT_GAP_ANALYSIS.md` records as actually done — this is a plan,
not a second set of done-claims.

## Today's actual delivered change (for reference)
- `frontend/components/EventsFeed.tsx`: Home page events now render under
  three priority sections ("Needs your attention" / "Worth a look" /
  "Other updates") instead of one flat list, using the `priority` field the
  backend already returns. Frontend-only. Verified: `tsc --noEmit` clean,
  live dev-server render returns 200 with no error boundary.

## P0 — next (small, safe, high-leverage)
1. **Extend priority-sectioning to `DigestFeed`'s "by announcement" view.**
   Same pattern as today's `EventsFeed` fix, same low risk. ~30 min.
2. **Coverage/confidence indicator per event card.** When
   `financial_changes` contains `not_comparable_reason` entries, surface a
   compact "partial data" tag rather than just the existing small-print
   `missing_information` line — makes the *honest* partial-coverage cases
   from gap analysis §1.2 visible to the user as a feature, not a silent
   gap. Frontend-only, uses existing fields.
3. **Quantify §1.2's coverage claim**: a one-off script (not a new feature)
   counting, across the 13 ingested documents, how many produce all 4 of
   Revenue/EBITDA/PBT/PAT vs. partial vs. none — turns "needs validation"
   into a real number for the demo script / submission checklist.

## P1 — real features, need a full build+test cycle (not same-day safe)
1. **Guidance-vs-actual comparison** (gap §2.4). Needs: a new extraction
   concept (forward-looking statement detection in concall transcripts),
   a data model linking a guidance statement to the later actual, and the
   stronger-model synthesis step CLAUDE.md rule 6 reserves for exactly this
   case. Estimate: multi-day.
2. **Dedicated Pull research views** (gap §2.3) — e.g. explicit "Financial
   snapshot" / "Bull vs Bear" screens on top of the existing
   `ResearchAskForm` engine, rather than building new retrieval logic.
   Lower risk than it sounds because the evidence engine underneath already
   exists; the work is UI + prompt templates per view. Estimate: 1-2 days
   per view.
3. **Management-change bio enrichment** (gap §1.4) — the one place
   CLAUDE.md explicitly allows outside sources. New: an outside-source
   fetch step gated to only the `management_change` category, kept fully
   separate from the Pull evidence pipeline so it can never leak into
   primary-source-only answers.

## P2 — infrastructure, explicitly scheduler/automation (excluded today)
1. Scheduled recurring Push briefings (weekly/monthly), the idea validated
   by AlphaSense/Quartr in the benchmark doc. Needs real job
   scheduling/retry/locking infra — explicitly excluded from today's "safe
   polish" scope by the user's decision, and risky to half-build same-day
   per CLAUDE.md rule 8.
2. Alternate delivery channels (WhatsApp/email), per the Tijori comparison.
   New third-party integration, new credentials/config — not attempted
   without a deliberate scope decision first.
3. Live NSE/BSE announcement scraping to replace manual import. Already
   investigated and found blocked (`docs/filing-access-spike.md`) — any
   future attempt needs a different approach (e.g. a licensed data vendor),
   not a workaround of the block.

## Explicitly not planned
- Replicating any competitor's UI or query language verbatim.
- Any change to the frozen 20-company portfolio / 5 ad-hoc set, document
  IDs, or chunk data — those remain locked per the standing instruction
  from Phase 11C, independent of this roadmap.
