# FINN — Requirements (from ENAM Build Challenge brief + reference doc)

Source documents:
- `ENAM_AI_Engineer_Build_Challenge_Main.pdf` (the brief)
- `ENAM_Build_Challenge_Reference.pdf` (companion glossary / announcement categories)

Legend:
- **[REQ]** — explicit, non-negotiable requirement stated in the brief.
- **[EX]** — an illustrative example ENAM gave ("we love this", "for example") — informs design, not mandatory to copy literally.
- **[OPT]** — explicitly optional / "menu, pick what you build."
- **[DECISION]** — our own proposed implementation choice, not stated by ENAM. Needs our judgment call, flagged so it's easy to revisit.

---

## 1. Deliverable & evaluation

- **[REQ]** Deliverable = a mobile-first **working prototype** + **GitHub repository** + **covering note** (email writeup).
- **[REQ]** Evaluated on: how we build, what we choose to build, creativity and judgment — explicitly **not** completeness or polish.
- **[REQ]** "Thin-but-working beats broad-but-broken." A demo that doesn't run is the worst outcome.
- **[REQ]** Build the smallest thing that proves the real thing can be built well.
- **[REQ]** Deadline: 15 November 2026.

## 2. Problem framing

- **[REQ]** The core skill being tested is **filtering**, not aggregating: surface what matters, bury/collapse the rest.
- **[REQ]** Product must become part of a daily investor's workflow — mobile-first.
- **[REQ]** Two modes: **Push** (proactive, "what changed and why you should care") and **Pull** (on-demand research/analysis).
- **[REQ]** Frontend (product, interaction model, design) is explicitly **ours to decide** — this is "the heart of the challenge" and the primary signal ENAM wants.

## 3. Companies / scope

- **[REQ]** Choose a mock **portfolio of 15–20 NSE/BSE-listed companies** — mix of sectors/sizes "for an interesting demo."
- **[REQ]** Choose **3–5 additional ad-hoc research companies** (can be outside the portfolio) to demo Pull on.
- **[REQ]** The **research engine must generalize** to any NSE ticker where data is available — not hard-wired to the demo set. ENAM may test it against a company we didn't pick.
- **[DECISION]** Specific company list (portfolio + ad-hoc set) — to be chosen later, deferred until after architecture approval; not required for this phase.

## 4. Backend data sources — **[REQ]** exactly three, described as "guided... plumbing, not the point. Don't over-engineer."

1. **Price & volume, end-of-day (EOD)**, for portfolio stocks.
   - **[EX]** Yahoo Finance / `yfinance` library suggested as the default; `.NS` (NSE) / `.BO` (BSE) ticker suffixes.
   - **[REQ]** "Anything equivalent works" — source is not mandated, EOD price+volume data is.
2. **Corporate announcements / filings** from NSE/BSE for portfolio stocks.
   - **[REQ]** Must be classified/categorized.
   - **[EX]** A classification scheme is *provided* in the reference doc (17 categories) — explicitly: "use it, adapt it, or ignore it." Not mandatory to use verbatim.
3. **Company fundamentals** — annual reports + concall (earnings-call) transcripts.
   - **[EX]** screener.in or company investor-relations sites suggested as source — again "anything equivalent" implied by the tone of the brief (not stated as literally as for price data, but consistent).

## 5. Announcement categories (reference doc, §1) — **[EX]**, offered as guidance only, 17 total

`results`, `M&A`, `fund_raise`, `management_change`, `litigation`, `insider_trading`, `earnings_call`, `investor_meetings`, `credit_rating`, `dividend`, `bonus_split`, `capex`, `press_release`, `postal_ballot`, `agm_egm`, `pledging`, `unclassified`.

(Full definitions preserved in reference doc §1; reused verbatim in our classification prompts/schema per [DECISION] below.)

- **[DECISION]** We adopt this taxonomy as our default classification schema (it's well-specified and directly usable), while keeping the door open to add/merge categories if real filings don't map cleanly.

## 6. PUSH requirements

### 6a. Windowed digest — **[REQ]**
- For a **user-selectable time window** (default: **last 24 hours**), show every corporate filing/announcement across the portfolio.
- Must be **filtered and prioritised** — important things surface first, routine stuff collapsed or hidden.

### 6b. Triggered alerts — **[REQ]**
- Alert the moment something crosses a threshold. Two example trigger types given:
  - **[EX]** A material announcement of a type the user cares about (results, M&A, management change, etc. — user-selectable types).
  - **[EX]** An unusual EOD move — e.g. volume > ~2× recent average, or price move beyond ±X% in a day.
- **[REQ]** Thresholds must be **user-configurable** — "the point is I decide what 'unusual' means and the app watches for it."

### 6c. Presentation of pushed items
- **[EX] Management change** → don't just state the fact; pull a short background/bio of the incoming person (e.g. from LinkedIn) so the user instantly knows who they are.
- **[EX] Quarterly results** → **[REQ]**-strength because it's specific: give a first-cut of headline numbers — **Revenue, EBITDA, PBT, PAT** — **QoQ and YoY**, extracted from the actual results filing.
- **[REQ]** For every *other* announcement category: ENAM leaves it to our judgment what earns attention — one-line summary next to the filing, or just correct prioritisation. This judgment itself is "the point" — explicitly evaluated.
- **[EX]** Push-side enrichment (e.g., a person's professional background) is explicitly **exempt** from the primary-source-only rule (that rule applies to Pull only) — see §8.

## 7. PULL requirements

- **[REQ]** On-demand analysis of a company, **grounded in fundamentals** (annual reports + concall transcripts).
- **[OPT]** Eight suggested output types — "treat as a menu: pick what you build and how deep." None individually mandatory; collectively meant to show range of analytical depth:
  1. Business snapshot — what the company does, segments, revenue mix.
  2. Financial snapshot — current headline numbers (revenue, margins, PAT, key ratios).
  3. Trajectory — multi-year direction: what's growing/compressing.
  4. Balance sheet — debt, leverage, working-capital cycle, funding structure.
  5. Cash quality — cash-flow trend, cash conversion (profit → cash).
  6. Narrative vs. numbers — where management's story and the actual financials agree/diverge.
  7. Guidance — what management explicitly guided on (growth, margins, capex) vs. reality.
  8. Bull vs. bear — a tight case each way.
- **[EX]** Worked example ENAM explicitly values most: take the **last four quarters**, compare **management's own prior guidance/commentary vs. what was actually delivered**. Described as "the difference between summarising management and analysing them." This is the single most strongly signalled Pull feature in the brief.
- **[REQ]** The research engine must **generalise to any NSE ticker** with available data (see §3).

## 8. Primary-source-only discipline — **[REQ]**

- Pull/analysis side must be grounded **only** in primary sources: annual reports + concall transcripts (+ filings).
- **Explicitly forbidden** for Pull: broker notes, news, research reports, and the model's own outside/parametric knowledge of the company.
- **Exception, explicitly carved out:** Push-side enrichment (e.g., incoming CFO's LinkedIn bio) is "a different thing and completely fine" — the primary-source restriction does not apply to Push enrichment.
- **[DECISION]** Any RAG/LLM answer on the Pull side must cite which primary document/section it drew from, and the system prompt must instruct the model not to fill gaps from pretraining knowledge. This is a hallucination/scope-creep risk we must actively guard against (see architecture.md risks).

## 9. Interaction model — **[REQ] to experiment, format itself is open**

- How the investor interacts is **entirely up to us** — chat, voice, copilot, dashboard, "or something we haven't thought of."
- **[REQ]** Must be mobile-first.
- **[REQ]** ENAM wants to see "a point of view about how an investor should interact with this" — not just data shown. This is itself a graded dimension.

## 10. Quality bar — **[REQ]**

- "No AI slop": core, concise, beautifully presented, interactive.
- Must save time and surface what's important; feel like a thought-through product, not a model filling a template.
- Density and design both explicitly called out as graded.

## 11. Tools, models, cost — **[REQ] + [EX]**

- **[REQ]** No restriction on which models/providers (open-source, local, or commercial) — model/tool choice itself is evaluated.
- **[REQ]** Must be "comfortably doable on free tiers" — spend is not required to compete.
- **[REQ]** Efficiency is a bonus signal: smart model routing (cheap models for bulk extraction, strong models only where reasoning demands it), caching, chunking are explicitly called out as "exactly the instincts we're looking for."
- **[DECISION]** We will design a two-tier model routing strategy: a cheap/fast model for announcement classification & bulk extraction, a stronger model only for Pull-side synthesis (guidance-vs-actual, bull/bear, etc.) and embeddings for RAG retrieval. Deferred to architecture.md.

## 12. Submission requirements — **[REQ]**

- Deployed mobile-first prototype link (Expo/TestFlight or responsive web), easy to try on a phone.
- GitHub repository.
- AI build history — coding-agent/LLM conversation exports (e.g., this Claude Code session).
- Short covering-note writeup in the submission email: what was built, key decisions/trade-offs, what was deliberately left out, where we'd take it next.
- Email to `assessment@enam.com`, subject line exactly: `"IIT Delhi – AI Engineer - 2027"`.

## 13. Explicitly NOT required (do not over-build)

- Completeness/polish is explicitly deprioritized vs. a focused, working demo.
- The backend/data plumbing is explicitly called out as "not the point" — don't over-engineer it.
- Not all 8 Pull outputs need to be built — pick a focused subset done well.
- Not all 17 announcement categories necessarily need bespoke handling — `unclassified` exists precisely to absorb routine noise.

## 14. Open decisions deferred to later (not blocking architecture approval)

- Exact portfolio company list (15–20) and ad-hoc research set (3–5).
- Exact subset of the 8 Pull outputs to implement for the MVP demo.
- Exact interaction model (chat vs. dashboard vs. hybrid) — proposed in architecture.md, pending approval.
