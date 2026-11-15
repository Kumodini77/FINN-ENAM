# FINN Competitive Benchmark

Written: 2026-11-15. Method: public product pages / help-center / release
notes for each product, via live web search today. Each bullet under
"Verified" is a claim from that product's own marketing or docs, not an
independent benchmark — flagged where sources disagree. "FINN takeaway" is
our own recommendation, clearly separated from the verified claim. **FINN
does not copy any of these products** — this section exists only to find
ideas worth adapting to FINN's own scope, data sources and cost
constraints, per the standing instruction not to replicate them wholesale.

---

## Screener.in
- **Verified**: ~10 years of fundamental financial history per company; a
  powerful custom-query language for cross-company screening; a combined
  announcements + filings feed, filterable, with alerts (announcements
  access may be a paid tier per third-party reviews — unconfirmed on the
  official site).
  Sources: [screener.in/features](https://screener.in/features),
  [strike.money review](https://www.strike.money/reviews/screener-in).
- **FINN takeaway**: Screener's query language is overkill for FINN's
  20-company scope and would be a large, risky build. What's worth adapting
  cheaply: a **tailored announcement feed per watchlist** — FINN already
  has this (digest/events scoped to the portfolio). Not recommending the
  query builder given today's constraints.

## Tijori Finance
- **Verified**: a personalised timeline combining exchange filings,
  market-share/business changes, and news per followed company; portfolio
  + watchlist views; "Tijori Alerts" pushes WhatsApp notifications "within
  seconds" of a filing; free tier capped at 5 alerts/1 watchlist.
  Sources: [tijorifinance.com/features](https://www.tijorifinance.com/features),
  [Tijori Alerts thread](https://tradingqna.com/t/tijori-alerts-ai-powered-whatsapp-notifications/184365).
- **FINN takeaway**: the timeline-per-company concept is close to what
  FINN's `EventsFeed` already does for the whole portfolio. WhatsApp
  delivery is a real differentiator worth a future phase — out of scope
  today (new integration, not "safe polish").

## Quartr
- **Verified**: keyword search across a 10,000+ company transcript
  database; filings search; a daily recap "delivered every morning";
  keyword alerts for named entities (e.g. competitors) that sync
  mobile/web. Sources:
  [quartr.com/use-cases/hedge-funds](https://quartr.com/use-cases/hedge-funds),
  [Quartr Pro 2024 update](https://quartr.com/newsroom/news/quartr-pro-key-updates-2024).
- **FINN takeaway**: FINN's hybrid retrieval already does keyword+vector
  search over ingested transcripts/filings — structurally similar to
  Quartr's transcript search, just at FINN's much smaller document scale.
  Quartr's "daily recap every morning" validates FINN's digest/events
  concept rather than suggesting something new to build.

## AlphaSense
- **Verified**: "Generative Search" returns cited answers with a
  speed/depth tradeoff; "Deep Research" does multi-step agentic research
  producing cited reports; scheduled/custom agents can run recurring
  (weekly/monthly) briefings; real-time alerts on market moves and
  competitor activity. Caveat: a third-party article notes AlphaSense's
  newer "SuperAnalyst" agent has no independent benchmarks published yet.
  Sources: [alpha-sense.com/platform/generative-search](https://www.alpha-sense.com/platform/generative-search/),
  [AlphaSense May 2026 release notes](https://help.alpha-sense.com/hc/en-us/articles/52207495181203-AlphaSense-Product-Updates-May-2026).
- **FINN takeaway**: AlphaSense's "cited answers" is exactly FINN's Pull
  design already (every answer traces to a chunk/document/page). The
  "scheduled recurring agent" idea maps to a potential future "weekly
  guidance-vs-actual briefing" feature — correctly identified in the gap
  analysis as P1, not attempted today given the scheduler-infrastructure
  exclusion in today's scope.

## Koyfin, TIKR, heyfinn.co
Not independently re-searched today (time-boxed); from general knowledge
Koyfin/TIKR are broad screener+chart terminals (global coverage, financial
modeling exports) and heyfinn.co markets itself as an AI research
copilot. Neither claim is verified against a fresh source today, so no
takeaway is asserted from them — flagging this explicitly rather than
presenting unverified recall as fact.

---

## Where FINN already compares well
- **Evidence-grounding discipline**: FINN's refusal to fabricate a numeric
  answer from an ambiguous multi-line header (documented in
  `test_multiline_header_patterns.py`) is a stricter correctness bar than
  any of the above products publicly claim to enforce.
- **Cost-aware model routing**: deterministic numeric extraction bypassing
  the LLM entirely is a real cost advantage none of the above describe
  doing.

## Where FINN is behind
- No scheduled/recurring Pull briefings (AlphaSense, Quartr both have
  this).
- No alternate delivery channel (WhatsApp/email) beyond the in-app feed
  (Tijori).
- No guidance-vs-actual structured comparison (closest FINN analogue:
  AlphaSense's cited Q&A, but FINN doesn't yet structure the comparison).

These three gaps are already captured with priorities in
`FINN_PRODUCT_GAP_ANALYSIS.md` §2.4 and the roadmap below — none were
rushed into today's build.
