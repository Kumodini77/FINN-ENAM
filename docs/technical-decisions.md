# FINN — Technical Decisions

Why things were built this way, not just what was built.

## Why deterministic rules for Push priority and classification, not an LLM

`priority.py`'s formula (`category_weight × recency_decay`, fixed inspectable
tables, fixed thresholds) and `classification.py`'s keyword rule table are both
fully deterministic and free to run on every filing. Reasons:
1. **Cost-efficiency is an explicit grading criterion** — classifying and
   scoring every filing with an LLM call would be the opposite of "use a
   cheap/fast model for classification and bulk extraction."
2. **Auditability** — `priority.py`'s `PriorityResult.rationale` is a plain
   string built from the same numbers the UI shows; there is no hidden model
   judgment a user can't verify.
3. **Reproducibility** — the same filing always gets the same category and
   priority. An LLM call doesn't guarantee that.

An *optional* Anthropic call exists only for titles the rule table leaves
genuinely ambiguous, gated on `ANTHROPIC_API_KEY` being configured. It never
runs for Pull.

## Why hybrid retrieval, not vector-only

Measured directly against the genuine HDFC Q1 FY27 document: for "What was
HDFC Bank's net interest income in Q1 FY27?", the real P&L table ranked **26th
of 203 chunks** by cosine similarity alone — short, generic prose (a page
footer repeating "HDFC Bank") ranked closer than the actual answer. This is a
real, measured embedding-model limitation for dense numeric table content
against natural-language questions, not a hypothetical concern.

The fix is **hybrid, not a bigger `match_count`**: the existing RPC's 20-row
cap is a deliberate, reviewed server-side limit (migrations 006/008); raising
it blindly doesn't fix a ranking problem, it just returns more wrong results.
Instead, an **independent lexical search** (plain REST reads over the same
company-isolated, completed-documents-only data) can surface the right chunk
regardless of where it ranks by vector similarity, and a **hard priority
tier** (not just an additive score bonus) ensures structured table evidence
always outranks prose for a numerical question — an additive bonus alone was
tried first and wasn't enough; a short, highly vector-similar prose chunk that
happened to repeat the same metric name still won.

## Why MiniLM is local, not an API-based embedding model

Explicit project constraint: no paid embedding API, no dependency on an
Anthropic/OpenAI API *entitlement* (a Claude subscription is not the same as
API access). `sentence-transformers/all-MiniLM-L6-v2` runs entirely on-device,
pinned to an exact Hugging Face commit SHA (not the `main` branch, which can
drift), with a persistent on-disk cache so repeated runs don't re-download or
re-embed identical text.

## Why reliable evidence is preferred to unsupported generated prose

**No answer-generation LLM is configured in this build.** This was a
deliberate choice stated explicitly rather than hidden: a Claude Pro
subscription does not include API access, and the project was instructed not
to assume otherwise or introduce a paid dependency. Rather than fake a
chatbot by lightly dressing up retrieval results as "AI analysis," every
`/api/research/ask` response says plainly, in a `generation_note` field, that
it is deterministic retrieval and pattern-matched extraction — not synthesis.
A numerical question gets an exact, cited figure (extracted by regex-based
period-binding over a real table row, never guessed); anything else gets the
ranked, cited evidence itself, labeled as evidence, not answered for the user.

## Why original company-source references are preserved everywhere

Every chunk, document, event, and alert carries its original source URL, page
reference (where applicable), and reporting period through every layer — the
Pydantic models, the API responses, and the frontend cards. This is not
incidental: per the assignment's own requirement, Pull answers must be
traceable to primary company documents, never to a model's memorized
knowledge or an unlinked summary. A citation that can't be clicked through to
the actual source document is treated as a defect, not a nice-to-have.

## Why `chunk_type`/`needs_manual_review` instead of a confidence score

A single float "confidence" score invites being silently averaged, thresholded,
or ignored downstream. Instead: `prose` / `table_row_group` (confidently
structured) / `table_unparsed` (ambiguous, raw text preserved verbatim) are
three explicit states, and `needs_manual_review` is **structurally mandatory**
(a database check constraint, not just an application convention) whenever
`chunk_type = 'table_unparsed'`. `extract_numeric_answer()` and the hybrid
re-ranker both check `chunk_type`/`needs_manual_review` directly — there is no
path by which an unreliable extraction can be presented as a verified figure.

## Why event grouping needed no new migration

Grouping is computed at read time from existing `announcements` fields (ticker,
category, title/extracted_text) via the same period-resolution logic already
built for Pull — reused, not duplicated. A new migration was considered (an
explicit `event_id` column) and rejected: it would require backfilling
historical rows and maintaining write-time grouping logic for a prototype with
one real company's data, which is the kind of unnecessary schema expansion the
project was explicitly asked to avoid ("don't over-engineer the data
plumbing").

## What was deliberately left out

- **Buy/sell recommendations, price targets, opaque "AI confidence" scores** —
  explicitly out of scope; every signal FINN shows is either a reported fact,
  a stated calculation, or a disclosed management statement, never collapsed
  into a single verdict.
- **A multi-agent research planner** — Pull is retrieval + deterministic
  extraction, not an agent loop; adding one without an underlying generation
  model to actually synthesize a plan would be theater, not functionality.
- **Full exchange-wide automated scraping** — confirmed non-viable via direct
  automated access (`docs/filing-access-spike.md`); building around a blocked
  access path would misrepresent what the product can actually do.
- **Guidance-vs-actual and narrative-change tracking** — would require
  fabricating multi-quarter history or transcript content that doesn't exist;
  the honest choice was to defer, not to manufacture a convincing-looking demo.
