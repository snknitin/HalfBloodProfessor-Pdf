# hb-pdf — Half-Blood Professor PDF — Build Spec v2

Upload a textbook chapter (PDF). Get it back looking like the Half-Blood Prince's copy of
*Advanced Potion-Making*: an expert has scrawled over it in ink — struck out the outdated
number and written the correct one above it, circled a weak claim with an arrow to a terse
margin note, underlined what matters, sketched a little chain diagram in the margin.

**The 30-second demo:** click "Try a sample chapter" → progress line ("Reading… Thinking…
Scribbling…") → annotated PDF renders in the page with visible ink → download. Uploading
your own PDF works the same way.

This spec has two tracks. **Track A (the annotation engine) is DONE and proven** — do not
rebuild it. **Track B (productize on Cloudflare as `hb-pdf`) is what to implement next**,
phase by phase. Each phase has acceptance criteria; implement them in order.

---

## Track A — DONE: the annotation engine

What exists and works (see `outputs/Ch1_annotated.pdf` for proof — 5 pages, 25 annotations):

| File | Role |
|------|------|
| `app/scribe.py` | Ink primitives: clean strike/underline, hand-drawn circles, brackets, checkmarks, compact callout icons, curved arrows, star/asterisk/exclaim doodles, rotated margin notes in embedded handwriting fonts, lists, chain diagrams, dependency trees, and conceptual equation diagrams |
| `app/pipeline.py` | Quote→coordinate matching (`page.search_for` + CJK-ligature fallback), anchor-ordered greedy margin placement, CLI |
| `app/annotations_ch1.json` | 25 hand-authored annotations in the exact JSON schema the LLM must emit |
| `app/fonts/` | Caveat (margin notes), Homemade Apple (scrawled corrections) — OFL/Apache, embeddable |
| `tests/test_smoke.py` | One-command regression check: `python tests/test_smoke.py` |

Run: `python -m app.pipeline "samples/Ch1 - Introductions.pdf" app/annotations_ch1.json out.pdf --pages 2-6 --previews outputs/preview`

**Determinism policy (non-negotiable, keep in Track B):** the LLM decides only *what* to
mark and *what the notes say*. Every coordinate, wobble, and pen stroke is seeded,
deterministic Python (`sha256(pdf_bytes)` seeds the RNG) — same upload, identical ink.

### The annotation JSON contract (canonical — the LLM must emit exactly this)

```json
{"annotations": [
  {"type": "underline", "quote": "verbatim substring from the page", "note": "margin note <= 36 words", "double": false},
  {"type": "strike",    "quote": "the outdated phrase", "correction": "<= 8 words", "note": "optional why"},
  {"type": "circle",    "quote": "weak claim", "note": "margin note; arrow drawn to it"},
  {"type": "doodle",    "quote": "anchor text", "symbol": "star | asterisk | exclaim"},
  {"type": "margin",    "quote": "anchor text", "note": "commentary tied to this line"},
  {"type": "bracket",   "quote": "opening anchor", "end_quote": "optional ending anchor", "note": "section-level insight"},
  {"type": "list",      "quote": "narrative anchor", "title": "optional title", "items": ["step 1", "step 2"]},
  {"type": "checkmark", "quote": "strong evidence", "counter": "optional limitation"},
  {"type": "callout",   "quote": "anchor text", "icon": "question | warning | practice | definition", "note": "expert insight"},
  {"type": "diagram",   "title": "optional caption", "labels": ["node1", "node2", "node3"]}
]}
```

Prompt rules that keep the deterministic side safe (enforce in the system prompt):
- Quotes must be **verbatim substrings, 3–8 words**, never starting or ending inside a
  hyphen-wrapped word (hyphen-split quotes silently fail to match). Underlines may span a
  complete sentence of up to 30 words.
- **≤ 15 annotations per page**; at most one `diagram` per eight-page window.
- Voice: terse, confident, slightly caustic expert ("Obviously dated — Göbekli Tepe, ~9500 BCE").
  Notes carry real, current knowledge: corrections, updated numbers, newer results, better methods.
- Unmatched quotes are dropped silently by the engine — a missing doodle is invisible,
  a misplaced one is broken. This is the safety valve; never try to "fix" it with coordinates from the LLM.

---

## Track B — TO BUILD: `hb-pdf` on Cloudflare

### B0. Decisions (locked — don't relitigate)

- **Two deployables, one repo.** `engine/` = the Python annotation service (Track A + FastAPI,
  Dockerized, deployed as a **Cloudflare Container** behind a thin Worker). `site/` = the
  public website (Higgsfield-managed Worker, `--type website`, project name **`hb-pdf`**).
  Why split: the site gets regenerated/iterated constantly (Codex, Higgsfield, design passes);
  the engine is proven and must not be churned by site iterations.
- **Why a Container:** Cloudflare Workers cannot run PyMuPDF (native wheel) and would cap CPU
  long before 50 pages. Cloudflare Containers run the existing Python engine unchanged —
  everything stays on Cloudflare as requested. (The only alternative is a full TypeScript
  rewrite of scribe/pipeline with pdf.js + pdf-lib; rejected — it re-opens the entire
  proven aesthetic for re-tuning.)
- **LLM:** OpenAI API via the user's GPT credits. Model name comes from env var `HB_MODEL` —
  never hardcode it. **DECIDED: one model for every tier** (currently `gpt-5.4-mini`);
  paid tiers differentiate on limits and priority, never on model. A future swap to an
  open-source model happens by changing `HB_MODEL`/endpoint, evaluated with the B2 harness.
  Temperature 0.3, Structured Outputs (JSON schema) so responses always parse.
- **No storage, ever.** PDF bytes: request body → memory → response. No R2, no disk, no DB.
  The only persisted data: LLM response cache and rate-limit counters in Workers KV
  (content = annotation JSON keyed by hash, never the text itself), and PostHog events.
- **Limits:** digital-text PDFs only (empty extraction → friendly rejection, no OCR).
  Free: ≤ 50 pages, ≤ 20 MB, 3 docs/IP/day. Teacher's Pet (monthly): ≤ 150 pages,
  ≤ 50 MB, 5/day, 30/month. Professor's Pass (one-time whole book): one document,
  ≤ 1,000 pages, ≤ 150 MB. Full tier design in **B6**.

### B1. Engine service (`engine/`)

Wrap Track A in a service. New files only — `app/scribe.py` and `app/pipeline.py` move in
as-is (import path changes are fine; behavior changes are not).

1. `engine/main.py` — FastAPI:
   - `POST /annotate` (body: raw PDF bytes; header `X-HB-Auth: <shared secret>`):
     validate caps → extract text per page → **fan out one LLM call per page, all pages
     concurrently** (`AsyncOpenAI` + `asyncio.gather`, semaphore 40, retry once with jitter
     on 429/5xx, skip a page on second failure) → match quotes → draw ink → return
     `application/pdf` bytes.
   - Progress: send as SSE if `?stream=1` (`extracting`, `thinking p/N`, `scribbling`,
     `done`) with the PDF delivered base64 in the final event; plain request/response otherwise.
   - `GET /healthz` → 200.
   - Skip LLM calls for pages with < 300 chars of text (covers, TOCs, figure pages).
   - Truncate page text sent to the LLM at ~4,000 chars.
   - Cache: key `sha256(model + prompt_version + page_text)` → annotation JSON. In-process
     dict first; if KV env bindings are present, read-through to KV so the sample document
     is permanently free. Bump `prompt_version` to invalidate.
2. `engine/prompts.py` — system prompt implementing the contract + voice above,
   with the JSON schema for Structured Outputs.
3. `engine/Dockerfile` — `python:3.12-slim`, `pip install fastapi uvicorn pymupdf openai`,
   copy app, `uvicorn main:app --host 0.0.0.0 --port 8080`.
4. `engine/wrangler.jsonc` — Worker `hb-pdf-engine` with a Container binding
   (standard instance, `sleepAfter: "15m"`), routes `/annotate` + `/healthz` to the
   container, holds `OPENAI_API_KEY`, `HB_MODEL`, `HB_SHARED_SECRET` as secrets, KV
   namespace binding `HB_CACHE`.

**Acceptance:** `curl -X POST --data-binary @samples/Ch1\ -\ Introductions.pdf` (locally via
`docker run`, then on Cloudflare) returns an annotated PDF for the full 42-page chapter;
second identical run is served from cache with zero LLM calls; smoke test still passes.

**Latency budget for the 10-second target (50 pages, warm container, mini model):**

| Step | Budget |
|------|--------|
| Upload transfer | 1–2 s (user's bandwidth; outside our control) |
| Extract text | ≤ 1 s |
| LLM fan-out (all pages parallel) | 4–8 s — the long pole; parallelism is why |
| Match + draw + save | ≤ 2 s |
| **Total p50** | **~8–13 s** — promise "usually under 15 s", show live progress |

Cold container start adds ~2–5 s; `sleepAfter: 15m` plus the sample-document cache makes
demos warm. Do not add a queue to chase the tail — streaming progress covers it.

### B2. Model evaluation harness (kept for the future open-source swap)

**DECIDED: the model does not change at launch and does not vary by tier.** `HB_MODEL`
stays on the existing mini-tier model (measured: $0.065 / 42-page doc). This section's
harness is NOT a launch task — it exists for the day an open-source model candidate is
tried as a replacement:

1. `engine/eval_models.py` — CLI: `python eval_models.py samples/Ch1*.pdf --models <a>,<b>`
   → runs the same pages through each model/endpoint → writes
   `outputs/eval/<model>/annotated.pdf` + a summary (annotations per page, % quotes
   matched, token usage).
2. Promotion bar: the candidate must retain *specific* corrections (named results, dates,
   numbers) at 12–15 annotations/dense page with a similar quote-match rate. Specificity is the
   product; generic notes ("this may be outdated") fail the candidate.

Already-built cost levers (keep them on): per-page cache, ≤ 15 annotations/page,
`max_output_tokens` = 3,200, short-circuit near-empty pages, tiered daily quotas (B6),
structured outputs (no retry burn on parse failures).

### B3. Website (`site/` — Higgsfield, project name `hb-pdf`)

Create with the Higgsfield websites flow, `--type website` (standalone brand, no Higgsfield
sign-in). The site is a **single-page product** plus nothing else:

- **Hero:** parchment/aged-paper background, dark sepia ink. Headline in the product's
  voice ("Your textbook, corrected by someone who's seen things"). The hero visual is an
  **animated ink sequence**: an SVG of real scribe strokes (wavy underline, a circle, an
  arrow, a margin scrawl) drawing themselves via `stroke-dashoffset` animation over a
  paragraph of fake textbook print. CSS/SVG only — no video file, no Remotion dependency
  for launch (a Remotion promo clip is B5, optional).
- **⚠ Reference images are design references only.** `references/` contains Warner Bros
  film stills — do NOT ship them on the public site. Generate original parchment/ink/
  marginalia hero assets (Higgsfield image gen) that evoke the style without the IP.
- **Upload flow:** dropzone + "Try a sample chapter" button → Turnstile check → POST to
  `/api/annotate` → SSE progress states with the "Reading… Thinking… Scribbling…" copy →
  inline PDF preview (`<embed>`) + Download button. Errors are friendly and specific
  (too many pages, scanned PDF, daily limit reached).
- **Footer lines (required):** "Annotations are AI-generated and may be wrong." ·
  "Upload only content you have the right to use." · "Files are processed in memory and
  never stored."
- **`/api/annotate` route in the site Worker:** verify Turnstile token → quota check
  (free: hashed-IP counter; pass holders: access-key counter — see B6) → forward body to
  the engine with `X-HB-Auth` → stream the engine's response through. The OpenAI key
  lives only in the engine; the shared secret lives only in the site server and engine.
- PostHog: `page_viewed`, `pdf_uploaded` (page count only), `pdf_annotated` (duration),
  `sample_clicked`, `error_occurred` (reason). No content, no filenames.

**Acceptance:** `hb-pdf` deploys via the Higgsfield flow; sample chapter round-trips in
under ~10 s warm; own-PDF upload works from a phone; nothing is written to R2/D1;
the site iterates (copy, design, animation) without touching `engine/`.

### B4. Wiring & ops checklist

- [ ] `wrangler secret put` on engine: `OPENAI_API_KEY`, `HB_MODEL`, `HB_SHARED_SECRET`
- [ ] KV namespaces: `HB_CACHE` (engine), `HB_RATELIMIT` (site)
- [ ] Turnstile site key/secret pair on `site/`
- [ ] Warm the sample-doc cache once after every `prompt_version` bump
- [ ] PostHog project + the 5 events above
- [ ] Verify the 20 MB body path end-to-end (Worker request limits comfortably allow it — test, don't assume)
- [ ] Engine request timeout ≥ 60 s; SSE keeps the connection honest meanwhile
- [ ] `python tests/test_smoke.py` in CI or as a pre-deploy habit

### B5. Polish (only after B1–B4 ship)

- Remotion promo clip (15–30 s: book opens, ink draws itself, corrected page, logo) for
  social sharing — reuse the SVG stroke assets from the hero.
- OG/Twitter card image: one annotated sample page (own-generated, not a film still).
- A small before/after gallery of 2–3 sample pages.
- "Persona" dropdown (Half-Blood Professor / Archaeology Mentor / AI Engineer) — it's a
  one-line system-prompt swap; do it only if demo feedback asks for it.

### B6. Monetization: Teacher's Pet & Professor's Pass (FINAL — all decisions locked)

Context: the live stack is site on Higgsfield (`hb-pdf.higgsfield.app`) + engine on a free
Hugging Face Docker Space + Cloudflare free (Turnstile, KV) — see `DEPLOYMENT_HANDOFF.md`.
Everything below runs on that stack with zero new infrastructure. Cloudflare Containers
remain an optional future migration (Workers Paid plan) and are NOT required for B6.

#### Decisions locked (do not re-ask, do not relitigate)

| Decision | Value |
|---|---|
| Teacher's Pet price | **$5.99 / 30 days**, yearly **$49.99** |
| Professor's Pass price | **$4.99 per book, one-time** |
| Book caps | **1,000 pages / 150 MB.** The page cap is an anti-abuse bound (stitching several PDFs into one file to pay once), not a product limit — it covers virtually every real single book, every job under it is profitable (break-even ≈ 2,575 p), and it bounds wall-time. The 150 MB is a technical bound of the 1 GB Space. Over-cap books get a friendly "split it into two passes" message |
| Book progress UX | **Chapter-aware chunking:** align chunk boundaries to the PDF's table of contents (`doc.get_toc()`) when present, and show chapters finishing live ("✓ Ch 3: Statistical Learning — done · scribbling Ch 4…"); fallback to "Part 3 of 12 (pages 101–150)" when no TOC. The user watches their book get finished chapter by chapter |
| Book result retention | **24 h, encrypted, keyed to access key** — exists as delivery insurance only (so a dropped connection never requires re-crediting or a free re-run), not a library |
| Model | **Same model for every tier** (current `HB_MODEL`); plans differ on limits/priority only; open-source swap possible later via B2 harness |
| Annotation density | **12–15 per dense page — dense marginalia IS the product.** The count includes visual emphasis marks as well as written notes. Margins full of notes, underlines, arrows, fact-checks, and corrections, like an expert proofread it. Fix placement quality, never reduce density |
| Payments go live | **only after the P0 reliability fixes** (smoke report §16, Priority 0–1) |
| Custom domain (`hb-pdf.app`) | **DEFERRED — low priority, do not work on it** |

#### Tiers

| | Free ("Study Hall") | Teacher's Pet — $5.99/30 days ($49.99/yr) | Professor's Pass — $4.99 one-time |
|---|---|---|---|
| What you get | 3 docs/day | 5 docs/day, 30/month | **one whole book, once** |
| Max file size | 20 MB | 50 MB | 150 MB |
| Max pages | 50 | 150 | 1,000 |
| Model | same for all tiers (`HB_MODEL`) | same | same |
| Priority | queued behind paid when busy | admitted first | admitted first; one active book per engine at a time |
| Identified by | hashed IP (daily KV counter) | access key (KV counters) | access key (single-use credit) |

**Pages, not megabytes, drive cost** ($0.00155/page measured on mini). The MB caps are
bandwidth/memory limits; the page caps and monthly ceiling are the cost limits. Never
raise the page cap without redoing the worst-case math below. (And never upgrade the
model per-tier: at frontier pricing a maxed subscriber would cost $90–140/month —
the same-model-everywhere decision is a cost decision, not just a simplicity one.)

#### Cost & price math (from the measured $0.065 / 42-page run)

| Scenario | Cost |
|---|---:|
| Free doc, worst case (50 p, mini) | ~$0.08 |
| Free user, maxed month (3/day × 50 p) | ~$7.20 — Turnstile-gated abuse ceiling |
| Teacher's Pet doc, worst case (150 p, mini) | ~$0.23 |
| Teacher's Pet, maxed month (30 docs × 150 p) | ~$7 |
| Teacher's Pet, realistic month (10–20 docs) | ~$2.30–4.60 |
| Professor's Pass book, typical (300–600 p) | ~$0.47–0.93 — **81–91% margin at $4.99** |
| Professor's Pass book, worst case (1,000 p, mini) | ~$1.55 — still ~61% margin |
| Break-even page count at $4.99 | ~3,220 pages — the 1,000-page cap keeps every job profitable |

**Teacher's Pet: $5.99 / 30 days, $49.99/year** (anchor: z-lib/Anna's Archive donation tiers).
**Professor's Pass: $4.99 one-time per book.** Median Teacher's Pet payer is profitable;
a maxed-out whale costs ~$23 — bounded, acceptable at donation-ware scale. The book pass
is profitable in every case. Revisit after ~20 paying users with telemetry.

#### Identity: access keys, no accounts (the Mullvad / Anna's Archive model)

- Successful payment mints a random key, e.g. `hb-7f3k-92mx-q4tn` (≥ 64 bits entropy),
  stored in KV: `key → {tier: "pass", expires: <ts>, docs_today, docs_month}` with a
  ~32-day TTL. No email, no password, no account record, nothing to breach.
- The success page shows the key with "save this — it IS your account" copy. The site
  stores it in `localStorage`; every `/api/annotate` call sends it in a header.
- **Different device = paste the same key.** That's the whole cross-device story.
- **Recovery = the Stripe receipt.** The checkout success URL carries the Stripe
  `session_id`; a site route exchanges a paid session for its key idempotently, any time.
  Stripe's receipt email (which Stripe sends, not us) links back to that URL, so a lost
  key is recoverable without us storing emails.
- Key sharing is self-limiting: a shared key burns its own quota. No device fingerprinting,
  no concurrent-session policing — the quota IS the enforcement.
- Renewal = buy again (new key, or same key extended if pasted at checkout — implementer's
  choice; new-key-each-time is simpler). No subscriptions, no cancel flow, no customer portal.

#### The Professor's Pass pipeline (whole books, ≤ 1,000 pages / ≤ 150 MB)

A whole book is not a new engine — it is the existing pipeline run in **chapter chunks**:

- **Chunked, not monolithic:** split the document into chunks (PyMuPDF `doc.select`),
  process chunks **sequentially** — pages *within* a chunk still fan out in parallel
  exactly as today. Sequential chunks bound memory on the 1 GB Space, keep OpenAI
  rate-limit pressure flat, and leave inference slots for concurrent small docs. Stitch
  annotated chunks back with `doc.insert_pdf` at the end. Expected wall time: ~2–3 min
  for 400 pages, ~4–6 min at the 1,000-page cap.
- **Chunk along chapters, not arbitrary page counts:** read the PDF outline with
  `doc.get_toc()`. When a usable TOC exists, chunk boundaries follow top-level chapters
  (split any chapter longer than ~50 pages; merge tiny ones), and every chunk carries its
  chapter title. No TOC → plain ~50-page chunks labeled "Part n of N (pages a–b)".
- **Progress shows chapters finishing while they wait** — this is the product moment of
  the book tier: a live list where each chapter goes "queued → thinking → scribbling →
  ✓ done" ("✓ Ch 3: Statistical Learning · scribbling Ch 4…"). SSE emits a per-chunk
  event stream; the site renders the running checklist. No hard deadline; the visibly
  advancing chapter list is the promise. (Side effect: a stitched multi-book file
  produces a garbled chapter list — the abuse cosmetically punishes itself.)
- **Delivery — the one amendment to the no-storage rule:** a paying user must not lose a
  $4.99 result because their laptop slept during minute 2. On completion, store the
  annotated PDF **encrypted, keyed to the access key, TTL 24 h** (R2 or Space disk), and
  return a download link. The retention exists purely as **delivery insurance** — so a
  dropped connection never forces a re-credit or a free re-run — not as a library feature.
  Source PDFs are still never stored; only the finished result, briefly. State this in
  the footer copy ("your annotated book is deleted after 24 hours").
- **Credit semantics:** the book credit is consumed **only on successful completion**.
  A failed run (engine error, too many failed pages) leaves the credit intact and says so.
  Key redeemable for 7 days after purchase; result downloadable 24 h after completion.
- **Upload path:** files > 100 MB cannot transit a Cloudflare proxy Worker (body cap).
  Book uploads go **direct to the engine origin** (CORS-allowed, key-authenticated) —
  the engine URL is already public, and the access key is the gate.
- **Admission:** one active book per engine instance; a second book request queues with
  honest copy ("another book is on the professor's desk — starts in ~N min").

#### Payment rails (one rail grants access; the rest are tips)

- **Stripe Payment Links — the only rail that mints keys.** Three price points, two
  products: Teacher's Pet ($5.99 one-time → 30-day entitlement; $49.99 one-time → 365-day
  entitlement) and Professor's Pass ($4.99 one-time → one book credit).
  Flow: Payment Link → success redirect with `session_id` → site server route verifies the
  session as paid via Stripe API → mints key with the right tier (idempotent on
  `session_id`) → shows it. No webhook needed at this scale; add
  `checkout.session.completed` as hardening later.
- **Buy Me a Coffee: donation button only, grants nothing.** Wiring BMC memberships to
  entitlements means a second fulfillment path and manual reconciliation — skip until
  someone actually asks, then fulfill manually by email.
- **Gift cards (Anna's Archive style): skip.** Pure manual ops; revisit only if a real
  anonymous-payment demand appears.

#### Priority (what "priority" means with one free container)

Admission control, not a queue system: the engine tracks active documents; when at
capacity, free requests get a friendly "busy — try again in a minute" while pass holders
are admitted. If revenue appears, the first dollars upgrade the HF Space instance (or fund
the Workers Paid plan for the Container path) — that's the real priority upgrade.

#### Custom domain: `hb-pdf.app` — **DEFERRED, low priority. Do not work on this now.**

Kept for reference only. `hb-pdf.higgsfield.app` says "higgsfield" because Higgsfield
hosts the site on its platform subdomain — same as `*.pages.dev` or `*.vercel.app`.
When this is eventually picked up:

1. Buy `hb-pdf.app` (~$15–20/yr; Cloudflare Registrar sells at cost). The `.app` TLD is
   HTTPS-only (HSTS-preloaded) — fine, everything here is TLS anyway.
2. **First check whether Higgsfield supports custom domains** (dashboard / CLI publish
   settings). If yes: CNAME `hb-pdf.app` → the Higgsfield site, done.
3. If not: put the domain on Cloudflare (free) and run a **thin reverse-proxy Worker** on
   `hb-pdf.app` that forwards everything to `hb-pdf.higgsfield.app` (free Workers proxy
   fine; SSE streams through). Note: Cloudflare's ~100 MB request-body limit is below the
   150 MB whole-book cap, so Professor's Pass uploads must keep using the direct engine
   path.
4. Either way: add `hb-pdf.app` to the Turnstile widget's allowed hostnames, update
   PostHog's allowed origin, and keep the higgsfield.app URL as a redirect.

#### B6 acceptance

- Free flow unchanged except new limits (20 MB / 3-per-day / 50 pages).
- Buying each product end-to-end in Stripe test mode: pay → key shown → key pastes on a
  second device → tier limits apply → Teacher's Pet expires after 30 days with a friendly
  renew message → Professor's Pass credit survives a failed run, is consumed on success.
- A real ~50 MB / 150-page Teacher's Pet doc and a ~400-page book round-trip (memory-test
  the HF Space — 1 GB RAM with a large PDF plus render copies is the risk, not cost).
- Book result: re-downloadable with the key within 24 h; gone (verified) after TTL.
- Quota counters: free per hashed IP, paid per key, monthly ceiling enforced.
- No emails, filenames, or source PDFs stored anywhere; persisted data is only
  `key → entitlement/counters` in KV plus the encrypted 24 h book result.

### B7. Developer testing harness (local, no IP limits, gitignored)

Rate limits, Turnstile, and quotas live in the **site route** — the engine has none of
them, only the `X-HB-Auth` shared secret. So the developer path that bypasses every limit
without building a production backdoor is simply: **run the engine locally and hit it
directly**.

- `dev/` directory, **listed in `.gitignore`** (as is `.env`): nothing in it can reach GitHub.
- `dev/.env` (or root `.env`): `OPENAI_API_KEY`, `HB_MODEL`, `HB_SHARED_SECRET=devsecret`.
- Run the engine: `uvicorn engine.main:app --port 8080` (or `docker build -f
  engine/Dockerfile . && docker run --env-file .env -p 8080:8080 …`) — same code path as
  production, zero rate limits.
- `dev/loadtest.py` (to be written by the implementing agent; loads `.env` itself via
  python-dotenv):
  - Takes a glob of PDFs + concurrency flag; fires N parallel `/annotate` requests at
    localhost (or, with the real secret, at the deployed HF engine — also skips site limits).
  - Case matrix to cover: valid small doc, valid 42-page doc, 150-page doc, chunked book
    path, scanned/no-text PDF (expect 422), password-protected (422), > page-cap (413/422),
    corrupt bytes (422), unicode/ligature-heavy doc, two documents concurrently, repeat run
    (expect full cache hit, zero LLM calls).
  - Per-run report: status, wall time, token usage + estimated cost, retries, failed pages,
    quote-match %, drop reasons — written to `dev/results/<timestamp>.json` so regressions
    are diffable.
- Testing against the *deployed* engine still spends real OpenAI tokens and shares the one
  free container with real users — prefer localhost for volume runs, deployed for
  smoke-verification only.
- OCR/scanned-PDF support: explicitly **out of scope** for now; the harness just asserts
  the friendly rejection.

---

## THE TASK QUEUE — implement in this order, one task per session

Every product decision is already made (see "Decisions locked" in B6). When prompting an
agent, say **"Implement Task N from BUILD_SPEC.md"** — no other context should be needed.

**Task 1 — Reliability P0/P1** (from `outputs/ENGINE_SMOKE_TEST_AND_OPTIMIZATION_REPORT.md`
§16, Priority 0 and 1): per-annotation renderer validation and isolation (one bad
annotation must never 500 the document), rectangle clamping, character-length caps,
distinguish valid-empty vs failed pages, never cache operational failures, deadline-aware
retries, fail the document with a clear error when too many pages fail.
*Done when:* the previously-failing Ch1 case renders; a synthetic bad-annotation test
passes; failures appear in SSE progress and final metadata.

**Task 2 — Dev harness** (B7): `dev/loadtest.py` + case matrix + per-run JSON reports.
*Done when:* the full matrix runs green against the locally-run engine, including the
cache-hit repeat and two-concurrent-documents cases.

**Task 3 — Tiers, keys, and quotas** (B6, no payments yet): free limits 20 MB / 3-day /
50 pages; access-key model in KV (mint, verify, expire, counters); tier-aware
`/api/annotate` route; a dev-only key-minting script in `dev/` for testing paid flows.
*Done when:* a dev-minted Teacher's Pet key gets 150 p/50 MB/10-day limits on a second
device, and expiry produces the friendly renew message.

**Task 4 — Professor's Pass book pipeline** (B6): chapter-aware chunking via `get_toc()`
(fallback ~50-page parts), sequential chunk processing + stitching, per-chapter SSE
progress checklist, encrypted 24 h result with key-gated re-download, credit consumed
only on success, direct-to-engine upload for >100 MB, one-active-book admission,
1,000-page cap with a friendly "split into two passes" over-cap message.
*Done when:* a ~400-page book round-trips on the deployed engine with a dev-minted key
showing chapters ticking off live; a no-TOC PDF falls back to part labels; a mid-run
disconnect still allows re-download; a forced failure preserves the credit; a
1,200-page file is rejected with the friendly message.

**Task 5 — Stripe** (B6, only after Tasks 1–4): two Payment Links (three price points:
$5.99/30-day, $49.99/365-day, $4.99/book), success-page session verification, idempotent key
minting, BuyMeACoffee as a no-entitlement tip button, footer payment-policy line.
*Done when:* the full B6 acceptance list passes in Stripe test mode.

**Task 6 — Feedback, sharing & feature-request intake** (independent of Tasks 1–5; can
ship anytime). Goal: let regular users react, share, and send feedback that lands in
snk.nitin@gmail.com pre-sorted, and route power users to GitHub — reusing the site's
existing Turnstile + KV + PostHog. **Design principle: zero resistance — the lightest
signal must cost one tap and zero typing; a layperson interacts without a form, account,
or decision. Never force a text box; reveal it only after a tap, always optional.**

#### Locked implementation decisions

- **Email provider: Resend.** Use its REST API directly from the site Worker (no SDK is
  necessary). Store `RESEND_API_KEY` and `HB_FEEDBACK_TO_EMAIL` as Higgsfield Worker
  secrets; never hardcode either value in client or server source. Until a custom domain
  exists, send from `HB PDF <onboarding@resend.dev>`. Resend permits that testing sender
  to deliver only to the email address associated with the Resend account, so create the
  account with the destination Gmail address. At implementation time, verify the current
  free quota and sender restriction against Resend's official documentation.
- **PostHog must be explicitly initialized.** The current `window.posthog?.capture(...)`
  calls are no-ops unless Higgsfield injects PostHog externally; do not assume that it
  does. Configure the public PostHog project token and API host, initialize the client
  once, and keep capture calls safe when analytics is unavailable. A PostHog project
  token is public configuration, not a server secret. Do not send PDF content, filename,
  access key, feedback text, or email address to PostHog.
- **Anonymous job correlation:** generate a fresh `crypto.randomUUID()` in the browser
  when each chapter/book annotation starts. Reuse that ID for its start, completion,
  failure, reaction, and feedback events. It is an opaque correlation ID only — never
  derive it from the PDF, filename, access key, email, or IP.
- **Written feedback gets its own Turnstile token.** Turnstile tokens are single-use;
  never reuse an upload/book token. Render/reset a dedicated feedback widget only after
  the user elects to send text. Bare one-tap reactions do not require Turnstile.
- **KV is a soft abuse limiter, not an atomic quota.** Workers KV is eventually
  consistent, so the 5/IP/day read-modify-write counter is sufficient for ordinary spam
  and repeated submissions but cannot guarantee rejection of a coordinated concurrent
  flood. Do not add a Durable Object for this task. Turnstile + honeypot + strict payload
  caps + the KV soft limit + Resend's provider quotas are the layered controls. If abuse
  appears in telemetry, move the counter to a Durable Object or Cloudflare rate-limiting
  rule later.
- **Accurate privacy language:** “store nothing” means the hb-pdf application does not
  persist the feedback payload in KV, D1, R2, logs, or any application database. Resend
  and Gmail necessarily process and retain the delivered email. The site policy must say
  this plainly and disclose the optional reply email, submitted message, browser context,
  and temporary salted IP-hash rate-limit record. Never log request bodies.

- **Post-download success card is the primary surface** (highest-intent moment). Three
  rows, in increasing order of effort:
  1. **One-tap reaction** — `😍 🙂 😐 😞` (or 👍/👎). A single click fires instantly, no
     modal, no Turnstile challenge. *Only after* the tap, an optional one-line "anything to
     add?" box slides in — never required. A reaction may be changed; capture the latest
     choice and prevent accidental rapid duplicate events in the client.
  2. **Share row** — a native **Share** button + a **Copy link** button (see sharing below).
  3. **Quiet deeper row** — small "Idea? Bug? → Feedback" (opens the modal) and "GitHub ↗".
- Show this card after a chapter download is initiated and after a completed book download
  is initiated. Do not place it between the ready result and its primary Download action.
- **Where signals go (no new infra):** bare reactions → **PostHog** event
  `feedback_reaction {rating, route, jobId}` (NOT email — aggregate on a dashboard, don't
  flood the inbox). Reaction-with-text or the full modal → `/api/feedback` → Gmail. Share
  clicks → PostHog `share_clicked {network}`.
- **Sharing (frictionless progressive-enhancement ladder):** primary button uses the **Web Share API
  (`navigator.share()`)** → native OS share sheet on mobile (one tap, every app). Where
  unavailable (desktop), fall back to **Copy link** + a couple of intent links (X:
  `intent/tweet`, WhatsApp: `wa.me/?text=`, LinkedIn). **Pre-write editable share copy**
  ("I turned a boring textbook chapter into an expert-annotated one with hb-pdf — it strikes
  outdated facts and scribbles margin notes like a professor. Try it:" + URL). Append
  `?ref=share&utm_source={network}` for PostHog virality attribution (`native_share`,
  `copy`, `x`, `whatsapp`, or `linkedin`). Call `navigator.share()` synchronously from the
  button's click handler so it retains the browser's required user activation. Treat user
  cancellation as neither an error nor a successful share event. Copy-link must show an
  accessible on-page “Copied” confirmation and fall back when the Clipboard API fails.
  *(Future, not now:
  sharing an image of the annotated page — most viral but touches private content + asset
  plumbing; text+link ships today.)*

- **New route `POST /api/feedback` in the site Worker** — a near-copy of `/api/annotate`'s
  front matter: verify the Turnstile token server-side, KV rate-limit (5/IP/day), honeypot
  check. Then send an email; store nothing. Payload:
  `{type: "bug|idea|praise|other", message, email?(optional reply-to), context:{route, ts, userAgent, jobId?, errorMsg?}}`.
- Server validation is authoritative: JSON only; reject unknown fields; type allowlist;
  message 1–2,000 characters; optional email ≤ 254 characters and syntactically valid;
  route/error/user-agent fields length-capped; timestamp normalized server-side; job ID
  must be a UUID; total request body ≤ 16 KB. The hidden honeypot field must be empty.
  Whitelist context fields rather than spreading the supplied object into logs or email.
- Hash the Cloudflare client IP with the existing `RATE_LIMIT_SALT`; use a distinct
  `feedback:daily:{yyyy-mm-dd}:{hash}` KV key with a short TTL. Do not store the raw IP.
  Return friendly `400`, `403`, `413`, `429`, and `503` JSON errors. A successful request
  returns `202` and an on-page thank-you state. Do not retry an email automatically in a
  way that could create duplicates; send a Resend idempotency key for each submission.
- Send plain text email rather than rendering user input as HTML. If supplied and valid,
  set the user's optional email as `Reply-To`; never put it in `From`. Propagate Resend
  failures as a generic friendly error without leaking provider details or secrets.
- **Subject tag for Gmail filtering:** `[HB-PDF] {Type} — "{first ~60 chars of message}"`.
  Strip CR/LF and control characters from the subject fragment. Body includes only the
  whitelisted context fields. **Never** include the PDF, its filename, access key, or its text.
  (Human sets a Gmail filter: `subject:[HB-PDF]` → label `hb-pdf`, star, never-spam.)
- **Persistent + contextual entry points to the modal:** an always-visible "Feedback" pill
  anchored to a screen edge (opposite the primary CTA) opens the modal (type selector,
  message box, optional email, honeypot, existing Turnstile widget, on-page thank-you
  state). The error state shows a "Didn't work? Tell us →" that opens the modal pre-set to
  type=Bug with `errorMsg` included in hidden context but not forced into the editable
  message. Use one reusable feedback form/state machine for the inline reaction follow-up
  and the modal so validation and Turnstile behavior cannot drift. The modal must trap
  focus, close with Escape, restore focus, carry accessible labels, and announce submit
  success/errors. (The post-download card above is the main driver; the
  pill just guarantees feedback is reachable from anywhere.)
- **GitHub path inside the modal (for structured requests):** two links —
  `issues/new?template=feature_request.yml` and `issues/new?labels=bug&template=bug_report.yml`.
  Add those two issue **forms** + `config.yml` (`blank_issues_enabled: false`, contact link
  back to the site) under `.github/ISSUE_TEMPLATE/`. Optional footer "★ Star on GitHub" link.

#### Expected implementation shape

- `site/app/src/components/feedback-experience.tsx` — success card, persistent pill,
  accessible modal, inline optional comment, share controls, and thank-you/error states.
- `site/app/src/lib/analytics.client.ts` — one-time PostHog initialization and typed,
  privacy-safe capture helpers.
- `site/app/src/lib/feedback.ts` — shared payload types, client limits, share copy, and
  referral URL builder.
- `site/app/src/lib/turnstile.server.ts` — shared server verifier extracted without
  changing the annotation route's existing behavior.
- `site/app/src/lib/rate-limit.server.ts` — salted-IP hashing and namespaced KV soft-limit
  helper. Refactoring existing duplicated logic is allowed only with regression tests.
- `site/app/src/routes/api/feedback.ts` — validation, honeypot, dedicated Turnstile token,
  soft rate limit, and direct Resend REST call.
- `.github/ISSUE_TEMPLATE/{feature_request.yml,bug_report.yml,config.yml}` — valid GitHub
  issue forms targeting `snknitin/HalfBloodProfessor-Pdf`.
- Add focused tests for payload validation, privacy-field filtering, subject sanitization,
  honeypot rejection, Turnstile failure, KV limit response, Resend failure, share URL/UTM
  generation, and reaction de-duplication. Mock all external calls; tests send no email and
  no PostHog event.

#### Task 6 configuration and handoff

- Higgsfield secrets: `RESEND_API_KEY`, `HB_FEEDBACK_TO_EMAIL`.
- PostHog public configuration: project token + API host, supplied through the site's
  supported public runtime/build configuration and never confused with a secret.
- Existing secrets reused: `TURNSTILE_SECRET`, `RATE_LIMIT_SALT`; existing binding reused:
  `KV`. No D1, R2, Durable Object, webhook, account system, or PDF storage is added.
- Update the privacy/policies page with the accurate feedback-processing disclosure.
- Human-only final setup: create the Resend account with the destination Gmail address,
  add the two Higgsfield secrets, create the Gmail filter, and provide PostHog public config.

*Done when:* a one-tap reaction after either download fires exactly one privacy-safe
PostHog event with no typing or challenge; analytics are confirmed initialized rather than
silently optional; the native Share button opens the OS share sheet on a supported mobile
browser and Copy-link works on desktop with pre-filled `?ref=share`/UTM copy; cancellation
is quiet; a text submission using its own Turnstile token arrives in Gmail with the tagged,
sanitized subject and whitelisted context but no PDF content, filename, or access key; the
application persists no feedback body; honeypot + Turnstile + payload caps + the KV soft
limit reject ordinary spam/repeated submissions; the error-state trigger opens a Bug report
with safe error context; the modal passes keyboard/focus checks; both GitHub template links
open valid pre-labeled issue forms; automated tests and the existing site tests/build pass.

**Deferred, do not pick up:** custom domain (`hb-pdf.app`), OCR/scanned PDFs, model
changes (B2 harness is future-only), Cloudflare Containers migration, Remotion promo;
a conservative deterministic non-content-page classifier before model calls that skips
tables of contents, indexes, glossaries, bibliographies/references, and administrative or
empty pages using extracted headings, PDF TOC metadata, lexical signals, and layout
heuristics, logs the skip reason, and sends uncertain pages rather than risking lost content.

### Iteration workflow (how the human works on this)

Open this same project folder in the Codex app; its in-app browser previews `site/` while
iterating on design. The contracts that must survive any iteration: the annotation JSON
schema, the two-Worker split, the no-storage rule, and determinism in the engine. When
prompting an agent to build, say: **"Implement Track B phase B1 from BUILD_SPEC.md"** (then
B2, B3, B4) — one phase per session, run its acceptance criteria before moving on.

---

## Risks & edge cases (both tracks)

| Risk | Mitigation |
|------|-----------|
| Quote doesn't match (hyphenation, ligatures, paraphrase) | Verbatim 3–8 word quotes; ligature-substitution fallback (hit in practice: MLSysBook maps fi/fl/ffi/ff to CJK codepoints); drop unmatched silently |
| Scanned/image PDF | Empty extraction → reject with "works on digital-text PDFs". No OCR |
| LLM returns broken JSON | Structured Outputs + one retry, then skip the page — the rest still renders |
| Hallucinated corrections | UI disclaimer; prompt favors hedged phrasing; brand as study companion, not fact-checker |
| Film stills on the public site | Never — design reference only; generate original assets |
| API key/secret leakage | Key only in engine secrets; site→engine authed by shared secret; nothing client-side |
| Cost abuse | Turnstile + tiered quotas (free 3/day/IP, pass 5/day + 30/mo per key) + page caps + per-page cache |
| Key leak / sharing | A shared key burns its own quota — self-limiting; no fingerprinting needed |
| Whale pass holders | Monthly ceiling (30 docs) bounds worst case at ~$7/user/mo; telemetry decides if pricing moves |
| Big book OOMs the 1 GB Space | Sequential chapter chunks + 150 MB / 1,000-page caps + memory test in B6 acceptance; upgrade the Space instance with first revenue |
| Stitched multi-book files on one $4.99 pass | 1,000-page cap bounds leakage at ~2 books per fee while every job stays profitable (break-even ~3,220 p); chapter progress list looks garbled for stitched files. Do NOT build stitch-detection unless telemetry shows real leakage |
| Paying user loses a long-run result | Book results stored encrypted 24 h, re-downloadable by key; credit consumed only on success |
| Cold container start | `sleepAfter: 15m` + cached sample doc keeps demos snappy; progress UI absorbs the rest |
| Copyright of uploads | In-memory only, never stored, never public; "upload only content you may use" |
| Noisy/ugly pages | Density targets 12–15 on dense pages (dense marginalia IS the product) — the fix is placement quality: rectangle clamping, correction wrapping, both-margin scoring, per-annotation render isolation (smoke report §16). Seeded RNG → reproducible → debuggable |
