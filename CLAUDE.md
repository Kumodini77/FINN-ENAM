# FINN — Project Instructions

FINN is a mobile-first financial investment agent built for the ENAM AI Engineer Build Challenge (deadline 15 Nov 2026). It has two modes: **Push** (proactive alerts/digest) and **Pull** (on-demand company research).

Source-of-truth documents — read these before making architectural or scope decisions:
- `docs/requirements.md` — what ENAM explicitly requires vs. what's an example vs. what's optional vs. our own decisions.
- `docs/architecture.md` — system design, data flow, risks.
- `docs/database-schema.md` — table design.
- `docs/implementation-roadmap.md` — phased build order and cut-line if time runs short.

## Non-negotiable constraints (do not violate these while implementing)

1. **Primary-source-only on Pull.** Any research/analysis output (business snapshot, financial snapshot, trajectory, balance sheet, cash quality, narrative-vs-numbers, guidance, bull/bear) must be grounded ONLY in retrieved chunks from annual reports / concall transcripts / filings. Never let the LLM answer from its own pretraining knowledge of the company, and never incorporate news, broker notes, or research reports into Pull answers. This restriction does NOT apply to Push-side enrichment (e.g. a management-change bio) — that's explicitly allowed to use outside sources.
2. **The research engine must generalize to any NSE ticker**, not just the chosen portfolio/ad-hoc demo set. Never hard-code ticker-specific logic in the extraction or RAG pipeline. ENAM may test against a company we didn't pick.
3. **Illustrative examples are not hard requirements.** The 17 announcement categories, the 8 Pull output types, and specific UI ideas (e.g. "pull a LinkedIn bio") in the brief are offered as guidance/menu items ("use it, adapt it, or ignore it" / "treat as a menu"). Don't treat every example as mandatory to implement — check `docs/requirements.md` for the REQ/EX/OPT distinction before assuming something is required.
4. **Two explicit hard requirements buried inside the examples** (these ARE required, not optional, despite being phrased via examples):
   - Quarterly results push must surface Revenue, EBITDA, PBT, PAT, both QoQ and YoY.
   - Alert thresholds (volume multiple, price move %) must be user-configurable, not hard-coded.
5. **User-configurable digest window**, defaulting to 24 hours — don't hard-code the window to 24h only.
6. **Cost-efficiency is graded.** Use a cheap/fast model for classification and bulk extraction; reserve the stronger model for Pull synthesis (especially guidance-vs-actual reasoning). Don't default every call to the most expensive model available.
7. **Don't over-engineer the data plumbing.** Price/volume, filings, and fundamentals ingestion are explicitly called "plumbing, not the point" — keep these simple and move effort into the Push/Pull product experience, which is what's graded.
8. **Thin-but-working beats broad-but-broken.** If a feature can't be made to work reliably before the deadline, cut it (see roadmap's cut-line) rather than shipping something broken. A demo that doesn't run is the worst outcome per the brief.
9. **Mobile-first, always.** Every frontend decision should be evaluated at phone width first.
10. **"No AI slop."** Outputs must be concise, prioritized/filtered (not just aggregated), and visually considered — not a wall of LLM-generated text. This is an explicit grading criterion, not a nice-to-have.

## Before writing frontend/backend code

Per the current phase of work: **do not start building, and do not install packages,** until the architecture in `docs/architecture.md` has been explicitly reviewed and approved. If resuming this project later and that approval hasn't happened yet, stop and ask before proceeding to implementation.

## When extending scope

If a new feature idea comes up that isn't in `docs/requirements.md`, either (a) confirm it serves an existing REQ, or (b) flag it clearly as a proposed addition and get confirmation before building it — don't silently expand scope beyond what ENAM asked for.
