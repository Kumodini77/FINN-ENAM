# FINN — Phase 0B Spike: Fundamentals & Primary Document Access Verification

Status: **complete**. All results below are from real, executed HTTP requests and real downloaded/extracted files — nothing fabricated. Scripts and raw artifacts live in `scripts/spikes/fundamentals_access_spike/`.

Scope note: all requests used an honest, non-spoofed client identifier (`FINN-research-spike/0.1 (contact: geet8331@gmail.com)`). No CAPTCHA, login, or anti-bot control was bypassed. `robots.txt` for screener.in was checked first (`results/` — fetched inline, not saved as a file) and company pages (`/company/<symbol>/consolidated/`) are not disallowed. Poppler (`pdftotext`/`pdfinfo`) was installed via Homebrew **with your explicit approval** to perform the PDF-extraction checks this phase requires; no other packages were installed.

---

## 1. Screener.in access results

| Company | URL tested | Status | Size |
|---|---|---|---|
| Reliance | `https://www.screener.in/company/RELIANCE/consolidated/` | **200** | 253,134 bytes |
| TCS | `https://www.screener.in/company/TCS/consolidated/` | **200** | 265,447 bytes |
| HDFC Bank | `https://www.screener.in/company/HDFCBANK/consolidated/` | **200** | 236,927 bytes |

For all three, the page's `id="documents"` section was present and contained real, parseable sub-sections: `documents annual-reports`, `documents concalls`, `documents credit-ratings`. Parsing these sections' `<a href>` tags produced real links — not placeholders — for every annual report year and every quarterly concall (transcript PDF, presentation PDF, and recording link, where available), for all three companies.

**Important finding:** screener.in does not host the documents itself — it's an index that links out to the original filer's own hosting (BSE's document servers, NSE's archive servers, or the company's own investor-relations domain, e.g. `tcs.com`, `hdfc.bank.in`). So "does screener.in work" and "can the linked document actually be downloaded" are two separate questions — see §2/§5.

Rate limits/restrictions: none encountered in this test (3 companies, ~6 requests total, 3-second spacing). `robots.txt` explicitly disallows only parameterized/search/paginated URLs, not company pages — our usage was compliant.

**Classification: screener.in itself — WORKING** (as an index/link-discovery layer).

---

## 2. Investor Relations website access results

| Company | Domain tested | Status |
|---|---|---|
| Reliance | `ril.com` (homepage) | **200** |
| Reliance | `ril.com` investor-relations page | 301 (redirect; not followed further in this pass) |
| TCS | `tcs.com` (homepage, IR landing page, and a document link) | **403** (all three, identical Akamai block) |
| HDFC Bank | `hdfc.bank.in` (homepage and a real document link) | **200** |

**Verified: HDFC Bank's own IR domain (`hdfc.bank.in`) is directly accessible and serves real documents.** A Q1 FY27 earnings presentation PDF was downloaded directly from it (see §4).

**Verified: TCS's entire public website (`tcs.com`), including its IR section, blocks non-browser clients** — same Akamai "Access Denied" signature (`errors.edgesuite.net`) seen in the Phase 0 NSE/BSE spike. This is not screener.in's fault; it's TCS's own site.

**Reliance's own site (`ril.com`) returned 200 on its homepage** — a real server response, not a block — but its specific investor-relations financial-reporting page redirected (301) and that redirect target wasn't followed further in this pass (one planned follow-up request was not run after a mid-session interruption). This is noted as **unverified, not failed** — do not read the 301 as a block; it simply wasn't chased to completion. Unlike TCS and the earlier NSE/BSE result, nothing about `ril.com`'s behavior so far indicates an anti-bot block.

---

## 3. Companies successfully tested (full chain: discover → download → extract)

| Company | Discovery (screener.in) | Document actually downloaded | Text extracted |
|---|---|---|---|
| **Reliance Industries** | Yes | Yes — Annual Report FY2012-13, via NSE archives | Yes |
| **HDFC Bank** | Yes | Yes — Q1 FY27 earnings presentation, via official IR site | Yes |
| **TCS** | Yes (links discovered) | **No** — both the BSE-hosted and TCS-hosted document URLs returned HTTP 403 | Not applicable |

---

## 4. Annual reports successfully downloaded

**One**, real and verified:

- **Reliance Industries — Annual Report FY2012-13**
  - Source: `https://archives.nseindia.com/annual_reports/AR_19_RELIANCE_2012_2013_08052013171218.zip` (an NSE *static archive* path — distinct from the NSE announcements API/homepage that was blocked in Phase 0; this deep static file path returned real content)
  - Downloaded: 200 OK, `application/zip`, 3,301,997 bytes
  - Contents verified via `unzip -l`: `RIL AR 2013 full file.pdf` (3,946,420 bytes) + `RIL_FormA.jpg`
  - PDF verified via `pdfinfo`: genuine PDF 1.6, Creator "Adobe InDesign CS6", **228 pages**, not encrypted
  - Text extraction verified via `pdftotext`: clean, readable text across cover pages, table of contents, auditor's report, and — critically — the actual **Balance Sheet as at 31st March 2013**, with aligned numeric columns (Share Capital, Reserves and Surplus, Long term borrowings, Trade Payables, Fixed Assets, Inventories, Cash and Bank Balances, etc., in ₹ crore) and the document's own printed page number ("116") preserved in the extracted text, matching its own table of contents.

Newer Reliance annual reports (2023-2026, linked from screener.in) were attempted via the BSE-hosted static paths and **failed with HTTP 403** (same Akamai block pattern as Phase 0) — not a success, recorded for completeness.

TCS and HDFC Bank annual reports (also linked from screener.in, also hosted on BSE's static paths) were not separately re-tested beyond the Reliance case, since the BSE hosting pattern had already failed consistently; re-testing identical infrastructure for different tickers was not expected to produce a different result and would have been redundant, not a new data point.

---

## 5. Concall transcripts successfully downloaded

**None of the transcript PDFs themselves were downloaded** — every transcript link discovered via screener.in (for Reliance, TCS, and HDFC Bank alike) pointed to BSE's `stockinfo/AnnPdfOpen.aspx` static path, which returned **HTTP 403** in every attempt.

However, a **closely related primary document did succeed**: HDFC Bank's **Q1 FY27 earnings presentation** (investor presentation, not the transcript itself) was downloaded directly from HDFC Bank's own IR domain:

- Source: `https://www.hdfc.bank.in/content/dam/hdfcbankpws/in/en/pdf/about-us/financial-results/2026-2027/quarter-1/q1fy27-earnings-presentation.pdf`
- Downloaded: 200 OK, `application/pdf`, 766,354 bytes
- PDF verified via `pdfinfo`: genuine PDF 1.7, Creator "Microsoft PowerPoint LTSC", **36 pages**, not encrypted
- Text extraction verified via `pdftotext`: clean, readable text including an actual **income-statement table** — Net interest income, Non-interest income, Net revenue, Operating expenses, Provisions, **Profit before tax, Profit after tax** — for Q1 FY26 / Q4 FY26 / Q1 FY27, with QoQ and YoY percentages already present in the source table.

This is a genuine primary-source document directly relevant to the brief's quarterly-results QoQ/YoY requirement, even though it's a presentation rather than the full transcript. The actual concall transcript (the Q&A document) was not obtained in this pass — flagged as unverified for the transcript-specific requirement, not as a success.

---

## 6. PDF extraction quality

| Document | Tool | Result |
|---|---|---|
| Reliance AR FY2012-13 (228 pp) | `pdftotext -layout` | Full-document extraction succeeded (1,180,159 characters). Headings, table of contents, auditor's report, and the standalone Balance Sheet table all extracted as clean, correctly-ordered text with numeric columns intact. |
| HDFC Bank Q1 FY27 presentation (36 pp) | `pdftotext -layout` | First 4 pages extracted cleanly, including a readable P&L table with aligned figures and QoQ/YoY columns. |

No OCR was required for either document — both are text-layer PDFs (not scanned images), which is favorable for a non-OCR extraction pipeline.

---

## 7. Page-number preservation

**Confirmed for the Reliance annual report**: the document's own printed page number ("116") appeared in the extracted text at the exact physical PDF page corresponding to its own table-of-contents entry for "Balance Sheet" — i.e., a citation like "see p.116 of the FY2013 Annual Report" is verifiably traceable back to the right physical page via `pdftotext -f <n> -l <n>`. This directly supports the brief's requirement that Pull-side answers cite their primary-source location.

Not separately re-verified for the HDFC Bank presentation (presentation slides use slide numbers rather than a formal page-number/TOC scheme, and this wasn't tested in depth in this pass).

---

## 8. Source reliability — comparison table

| Source | Role | Access method | HTTP status | Docs retrieved | Reliability | Limitations |
|---|---|---|---|---|---|---|
| **screener.in** | Index / link discovery | Direct HTTPS, honest client | 200 (all 3 companies) | N/A (index page itself, not source docs) | High in this test | Does not host documents itself; only as good as the links it points to |
| **NSE archives (static annual-report path)** | Document host (Reliance AR 2013) | Direct HTTPS, honest client | 200 | 1 real AR (228 pp) | High for this specific path; **inconsistent with NSE's own main site/API, which is fully blocked** (Phase 0) | Only verified for one older (2013) filing; newer Reliance ARs on screener.in point to BSE, not NSE, so this path's general coverage across companies/years is unverified |
| **BSE static document paths** (`xml-data/corpfiling`, `stockinfo/AnnPdfOpen.aspx`, `bseplus/AnnualReport`) | Document host (most AR + transcript links on screener.in) | Direct HTTPS, honest client | **403, every attempt** | 0 | None observed — same Akamai block as Phase 0's BSE API/homepage test | This is the dominant hosting pattern screener.in links to — its failure is the single biggest gap in this result |
| **Company IR site — HDFC Bank (`hdfc.bank.in`)** | Document host | Direct HTTPS, honest client | 200 | 1 real presentation (36 pp) | High in this test | Only one document type (presentation) tested; transcript/AR not separately tested on this domain |
| **Company IR site — TCS (`tcs.com`)** | Document host | Direct HTTPS, honest client | **403, every attempt (including the homepage itself)** | 0 | None observed | Entire public site blocks non-browser clients |
| **Company IR site — Reliance (`ril.com`)** | Document host | Direct HTTPS, honest client | 200 (homepage), 301 (IR subpage, not followed) | 0 (not reached in this pass) | Unverified — inconclusive, not failed | Needs a follow-up request to the redirect target to confirm |

**Classification:**
- **screener.in: WORKING** (as a discovery/index layer)
- **BSE-hosted documents (the majority of screener.in's links): NOT WORKING**
- **NSE archives static path: WORKING WITH LIMITATIONS** (confirmed for one document; coverage across companies/years unverified, and inconsistent with NSE's own site being otherwise fully blocked)
- **Company-hosted IR documents: WORKING WITH LIMITATIONS** — genuinely working for HDFC Bank, confirmed NOT WORKING for TCS, unverified (not failed) for Reliance. This varies per company, not a single yes/no answer.

---

## 9. Technical limitations

- **screener.in is not a document host.** It's valuable purely as a per-company index that tells you where each document actually lives. Its own accessibility doesn't guarantee the linked document's accessibility — those are separate systems with separate (and inconsistent) bot-protection postures.
- **BSE blocks document downloads the same way it blocks its announcements API** (Phase 0 finding) — this is the majority path screener.in links to for both annual reports and concall transcripts, so this single block has an outsized impact on coverage.
- **Company IR site accessibility is inconsistent and must be checked per-company**, not assumed. HDFC Bank's worked cleanly; TCS's didn't (same Akamai pattern as BSE); Reliance's is inconclusive pending a retest. A production system cannot assume "the company's own site will work" as a blanket fallback.
- **NSE's own static archive subdomain worked for a historical filing even though NSE's live site/API is fully blocked** (Phase 0) — this is a useful but narrow and unverified-at-scale exception; it should not be relied on as a general-purpose NSE document host without testing more companies/years.
- Only one document per working source was fully downloaded and extracted in this pass, consistent with the instruction not to download unnecessary large document collections — so "WORKING" classifications here are based on a real but small sample, not a large-scale crawl.
- No OCR capability was tested (not needed for either sample document, both were text-layer PDFs) — scanned/image-only filings, if encountered later, are an open gap.

---

## 10. Recommended production ingestion approach

**Use screener.in as the discovery/index layer, then fetch the actual document from whichever underlying host the link resolves to — with the understanding that BSE's document host (the majority of screener.in's links) does not work and must not be the only path relied on.**

Concretely, a `fundamentals_fetcher` should:
1. Parse the company's screener.in page for annual-report and concall-section links (this part is confirmed reliable).
2. Attempt the discovered URL directly:
   - If it's a BSE-hosted path → expect failure (403); this is now a known, not a surprising, outcome.
   - If it's a company-owned IR domain or an NSE archive static path → attempt it; some of these work (HDFC Bank, the Reliance 2013 case) and some don't (TCS).
3. **Fall back to a manually-curated document set** (mirroring the Phase 0 announcements recommendation) for companies/periods where the automated path fails — download a handful of real annual reports/presentations by hand (in a real browser) for the chosen demo companies, and ingest those directly into the `documents`/`chunks` tables. This keeps the RAG pipeline itself (chunking, embedding, retrieval, synthesis) fully real and testable regardless of which documents got in via automation vs. by hand.
4. Treat "can this ticker's fundamentals be auto-fetched" as a per-company, testable boolean rather than an assumption — the evidence here shows it genuinely varies (HDFC Bank: yes; TCS: no; Reliance: partially/older-only).

This does **not** require any change to the RAG/retrieval architecture itself (`docs/architecture.md` §3-5) — only to the ingestion step feeding it, exactly as was true for the NSE/BSE announcements finding in Phase 0.

---

## 11. Does the proposed architecture need modification?

**No change needed beyond what Phase 0 already proposed for ingestion.** `docs/architecture.md`'s `fundamentals_fetcher` (§3, item 3) should be understood as: try the automated path per-document, accept that it will not always succeed (BSE-hosted links will consistently fail; company IR sites vary), and have a manual-seed fallback ready — consistent with the pattern already adopted for announcements. The downstream RAG pipeline (chunking, embedding, pgvector retrieval, primary-source-only synthesis) is unaffected either way, since it operates on whatever lands in the `documents` table regardless of ingestion method.

---

## 12. Final recommendation

**C — a combination of both, with screener.in as the index and explicit per-company/per-document verification of the underlying host, backed by a manual-seed fallback for whatever doesn't work automatically.**

Reasoning, from the actual evidence:
- **Screener.in alone (A)** is necessary but not sufficient — it's an excellent index but does not itself host the documents, and most of what it links to (BSE's document servers) is confirmed blocked.
- **Official IR websites alone (B)** are not uniformly reliable either — confirmed working for HDFC Bank, confirmed blocked for TCS, and inconclusive for Reliance. Betting entirely on "the company's own site" is not safe without per-company verification.
- **The combination (C)** is what the evidence actually supports: use screener.in to discover what exists and where, attempt the real source, and don't be surprised or blocked when a given host (especially BSE) fails — have the manual-seed fallback ready, exactly as adopted for the Phase 0 announcements findings. This keeps the demo honest, working, and consistent with "thin-but-working beats broad-but-broken."
