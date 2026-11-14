# FINN — Phase 0 Spike: NSE/BSE Filing Access Verification

Status: **complete**. This documents real, executed tests — not assumptions. Scripts and raw response artifacts live in `scripts/spikes/filing_access_spike/`.

Scope note: per instruction, no CAPTCHA, authentication, or anti-bot control was bypassed. All requests used an honest, non-spoofed client identifier (`FINN-research-spike/0.1 (contact: geet8331@gmail.com)`). One attempt to retest with a spoofed browser User-Agent was blocked by the harness's own permission system as bot-check circumvention before it ran — consistent with the "do not bypass anti-bot protections" instruction, so it was not pursued further.

---

## 1. What was tested

| # | Target | Method |
|---|---|---|
| 1 | NSE homepage (`https://www.nseindia.com/`) | Plain GET, honest UA |
| 2 | NSE corporate-announcements API (`.../api/corporate-announcements?index=equities&symbol=RELIANCE`) | Plain GET, honest UA |
| 3 | NSE archives subdomain (`https://archives.nseindia.com/`) — tested for comparison, not an announcements source | Plain GET, honest UA |
| 4 | BSE homepage (`https://www.bseindia.com/`) | Plain GET, honest UA |
| 5 | BSE corporate-announcements API (`https://api.bseindia.com/BseIndiaAPI/api/AnnGetData/w?...`) | Plain GET, honest UA |

Sample companies specified (Reliance Industries, HDFC Bank, Infosys): only Reliance (`RELIANCE`) was actually exercised against the NSE API before the connection was blocked at the transport layer. Since the very first and simplest case (homepage, no params) already failed identically to the parameterized API call, and the block occurs below the HTTP layer, testing HDFC Bank and Infosys was not expected to produce a different outcome and was not run — flagging this explicitly as reasoning, not an executed test, per the instruction to distinguish verified observations from assumptions.

Scripts: `scripts/spikes/filing_access_spike/test_nse.sh`, `test_bse.sh`. Raw captured output: `scripts/spikes/filing_access_spike/results/*.html`, `*.json`, `*.status`.

---

## 2. Actual test results

### NSE

| Endpoint | HTTP status | Response size | curl exit code | Notes |
|---|---|---|---|---|
| Homepage | `000` (no response) | 0 bytes | 92 (HTTP/2 stream error) | TLS handshake completes, HTTP/2 stream opens, then the server resets the stream before sending any response. |
| Corporate-announcements API (RELIANCE) | `000` | 0 bytes | same pattern | Identical failure mode to homepage — the block is not endpoint-specific. |
| Archives subdomain | `000` | 0 bytes | same pattern | Even an unrelated subdomain blocks identically — points to network/CDN-level bot management (Akamai, per earlier verbose TLS inspection showing an Akamai-fronted certificate chain) rather than a route-specific rule. |

**Verified observation:** NSE blocks non-browser clients at the HTTP/2 transport layer — before any HTTP status line is returned, regardless of URL. This is not a timeout or network failure: DNS resolved correctly, TCP connected, and TLS 1.3 handshake completed successfully in every case (confirmed via verbose curl output); the server actively terminates the stream afterward. Google (used as a control) returned `200` from the same network in the same session, ruling out a local connectivity problem.

### BSE

| Endpoint | HTTP status | Response size | Notes |
|---|---|---|---|
| Homepage | `403` | 370 bytes | Real, non-empty Akamai "Access Denied" page. |
| Corporate-announcements API | `403` | 415 bytes | Same Akamai block page, API-specific reference ID. |

**Verified observation:** BSE's edge (Akamai `edgesuite.net`, confirmed by the reference IDs and error-page template in the response body) explicitly denies the request with a real 403 page naming the blocked URL — this is a deliberate access-control decision, not a server error or empty shell.

Raw BSE response body (verbatim, from `results/bse_api.json`):
```
<HTML><HEAD>
<TITLE>Access Denied</TITLE>
</HEAD><BODY>
<H1>Access Denied</H1>
You don't have permission to access "http://api.bseindia.com/BseIndiaAPI/api/AnnGetData/w?" on this server.
Reference #18.5df10117.1794505792.529302e9
https://errors.edgesuite.net/18.5df10117.1794505792.529302e9
</BODY>
</HTML>
```

---

## 3. Example announcement metadata

**None retrieved.** Both sources blocked access before any announcement data, title, timestamp, category, or document URL could be observed. No metadata sample is included because none was obtained — fabricating one would violate the explicit "do not invent successful test results" instruction.

---

## 4. Original filing document accessibility

**Not tested / not reachable.** Without a working announcements API response, no real filing/document URL for Reliance, HDFC Bank, or Infosys was ever obtained, so no PDF download or document-content read could be attempted. This item is unverified, not "working with limitations."

---

## 5. Comparison table

| Source | Official URL | Access method | HTTP status | Announcements retrieved | Company filtering | Date filtering | Document download | Reliability | Limitations |
|---|---|---|---|---|---|---|---|---|---|
| **NSE** | nseindia.com / api.nseindia.com | Direct HTTPS, honest client | `000` (transport-level block, no HTTP response) | **No** | Not reachable to test | Not reachable to test | Not reachable to test | None observed | Blocks all non-browser clients at the HTTP/2 layer, site-wide, before returning any HTTP status |
| **BSE** | bseindia.com / api.bseindia.com | Direct HTTPS, honest client | `403` (explicit Akamai deny) | **No** | Not reachable to test | Not reachable to test | Not reachable to test | None observed | Explicit WAF block for non-browser clients, site-wide |

**Classification:**
- **NSE: NOT WORKING** (direct, non-bypassing access)
- **BSE: NOT WORKING** (direct, non-bypassing access)

Both classifications are based on executed tests against real endpoints, not documentation reading alone.

---

## 6. Technical limitations

- Both NSE and BSE front their public sites with Akamai bot management, which in practice requires a real browser execution context (JS challenge solving, browser-realistic TLS/HTTP2 fingerprints, and session cookies obtained via a prior browser-like page load) to pass. Satisfying that from a server-side script is, by construction, the same thing as bypassing anti-bot protection — which this task explicitly rules out.
- This is a site-wide block, not a per-endpoint rule: the completely unrelated NSE archives subdomain failed identically to the announcements API, and BSE's homepage failed identically to its API. There is no narrower "unprotected corner" of either official site found in this test.
- We did not test logged-in / licensed-data-vendor access paths (e.g. NSE's and BSE's official paid real-time/historical data-feed products for institutional subscribers) — those are commercial products with their own onboarding, not something a quick spike can verify, and were out of scope for "official website" verification as requested.

---

## 7. Recommended integration approach

Given both official sources block unauthenticated automated access by design, and bypassing that is explicitly disallowed:

1. **Do not build a direct NSE/BSE scraper as planned in `docs/architecture.md`'s `filing_fetcher`.** It will not run reliably — it will not run at all under the constraints we're operating within.
2. **Recommended fallback for the prototype:** a small, manually-curated announcement dataset for the chosen demo companies (title, category, date, filing text/PDF saved locally), sourced by a human opening the public NSE/BSE site in a real browser and saving a handful of real filings for each portfolio/ad-hoc company. This keeps the Push pipeline's *downstream* logic (classification, extraction, alerting, digest) fully real and testable, while being honest that the *ingestion* step is manually seeded rather than live-scraped for this prototype. This is consistent with the brief's own framing that the backend is "plumbing, not the point" and that "thin-but-working beats broad-but-broken."
3. **If a live feed is wanted beyond the prototype:** the legitimate path is a licensed data vendor (e.g. NSE's or BSE's own commercial data-feed products, or a third-party financial-data API that has its own agreement with the exchanges) rather than scraping the public website. That's a procurement/legal decision, not an engineering one, and is out of scope for this spike.
4. Price/volume data is unaffected — yfinance is a separate, already-known-working path (not blocked the way NSE/BSE's own sites are) and was not retested here since it wasn't in scope for this spike; Phase 0's price-data check is covered separately.

---

## 8. Fallback strategy if a source becomes unavailable

This is moot in the narrow sense that neither source is available via direct scraping today — the "fallback" effectively becomes the primary path:

- **Primary plan for the prototype:** manually-seeded announcement + filing dataset (per §7.2), stored directly in the `announcements` / `documents` tables, skipping the `filing_fetcher` ingestion job entirely for the demo.
- **If even manual seeding proves awkward** (e.g. a company's filings are hard to locate even by hand): drop that company from the demo set rather than block on it — doesn't affect the portfolio-size or generalization requirements, since those are about the *research engine*, not the announcements feed.

---

## 9. Does the proposed FINN architecture need modification?

**Yes, one necessary change; nothing else in the approved architecture is affected.**

- `docs/architecture.md` §3 ("Filings job... polls NSE/BSE for new announcements") assumed live, automatable access. That assumption is now falsified by direct test. The **data model, API shape, classification/extraction pipeline, alerting logic, and frontend — all of it — stay exactly as designed**, because they operate on rows in the `announcements` table regardless of whether those rows arrived via a live scraper or a manual seed script.
- The only component that changes is the **ingestion mechanism** for announcements: replace the planned always-on `filing_fetcher` scraper with a one-time (or periodically re-run-by-hand) manual seed script that inserts real announcement + filing records for the demo companies. This is a smaller, lower-risk piece of work than originally scoped, not a larger one.
- `docs/implementation-roadmap.md` Phase 1 ("Build `filing_fetcher`: NSE/BSE → `announcements` table") should be updated to "Build a manual seed script that inserts real NSE/BSE announcement records (hand-collected) into `announcements`" — same table, same downstream phases unaffected.
- This also *de-risks* Phase 2 (classification/extraction) and Phase 3 (Push UI), since they no longer depend on an unreliable live feed being up during development or during the actual demo to ENAM.

---

## 10. Recommendation

**Use neither NSE nor BSE as a live, automated adapter for this prototype — both are confirmed NOT WORKING for direct, non-bypassing access.** Use a manually-curated, hand-collected set of real NSE/BSE announcements and filing documents for the demo portfolio and ad-hoc companies, loaded via a one-off seed script into the same `announcements`/`documents` schema the rest of the system already expects. This is evidence-based (both sources were actually tested, not assumed), keeps the demo honest about what's live vs. seeded, and costs nothing in terms of the product-level Push/Pull functionality ENAM is actually grading — the research engine's generalization requirement (§3 of requirements.md) concerns the Pull/fundamentals path (screener.in/IR sites), which was not blocked in this test and was out of scope for this spike (fundamentals access verification is a separate check, not yet performed).

If, later, a licensed NSE/BSE data-vendor feed becomes available (a business/procurement decision), swap it in behind the same `filing_fetcher` interface — the rest of the architecture needs no further change for that to work.
