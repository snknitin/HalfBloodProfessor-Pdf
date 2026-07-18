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
| `app/scribe.py` | Ink primitives: wavy strike/underline, hand-drawn circles, curved arrows, highlighter quads, cross-hatch scribbles, star/asterisk/exclaim doodles, rotated margin notes in embedded handwriting fonts, chain diagrams (horizontal row or vertical margin column) |
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
  {"type": "underline", "quote": "verbatim substring from the page", "note": "margin note <= 14 words", "double": false},
  {"type": "strike",    "quote": "the outdated phrase", "correction": "<= 5 words", "note": "optional why"},
  {"type": "circle",    "quote": "weak claim", "note": "margin note; arrow drawn to it"},
  {"type": "highlight", "quote": "key phrase"},
  {"type": "scribble",  "quote": "opening words of a bad passage", "note": "dismissive comment"},
  {"type": "doodle",    "quote": "anchor text", "symbol": "star | asterisk | exclaim"},
  {"type": "margin",    "quote": "anchor text", "note": "commentary tied to this line"},
  {"type": "diagram",   "title": "optional caption", "labels": ["node1", "node2", "node3"]}
]}
```

Prompt rules that keep the deterministic side safe (enforce in the system prompt):
- Quotes must be **verbatim substrings, 3–8 words**, never starting or ending inside a
  hyphen-wrapped word (hyphen-split quotes silently fail to match).
- **≤ 6 annotations per page**; at most one `diagram` per document.
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
  never hardcode it. Default to the current **mini tier** model; the nano tier is the
  cost-cutting candidate to evaluate (see B2). Temperature 0.3, Structured Outputs (JSON
  schema) so responses always parse.
- **No storage, ever.** PDF bytes: request body → memory → response. No R2, no disk, no DB.
  The only persisted data: LLM response cache and rate-limit counters in Workers KV
  (content = annotation JSON keyed by hash, never the text itself), and PostHog events.
- **Limits:** ≤ 50 pages, ≤ 20 MB, digital-text PDFs only (empty extraction → friendly
  rejection, no OCR). Public usage: 3 documents per IP per day.

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

### B2. Model quality ladder (cost control)

Rough per-document cost at 50 pages: ~75k input + ~25k output tokens. At mini-tier pricing
that is on the order of **$0.05–0.10/doc**; nano tier is ~5–10× cheaper. (Check current
pricing; don't trust this table's absolutes, trust the ratios.)

1. `engine/eval_models.py` — CLI: `python eval_models.py samples/Ch1*.pdf --models <a>,<b>`
   → runs the same pages through each model → writes `outputs/eval/<model>/annotated.pdf`
   + a one-page text summary (annotations per page, % quotes matched, token usage).
2. Judge by eye: does the nano tier still produce *specific* corrections (named results,
   dates, numbers) or does it drift generic ("this may be outdated")? Specificity is the
   product; that's the promotion bar between tiers.
3. Set the winner as `HB_MODEL`. Keep the mini tier for the bundled sample doc regardless —
   it's cached, so it costs once and demos at top quality forever.

Already-built cost levers (keep them on): per-page cache, ≤ 6 annotations/page,
`max_output_tokens` ≈ 700, short-circuit near-empty pages, 3 docs/IP/day, structured
outputs (no retry burn on parse failures).

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
- **`/api/annotate` route in the site Worker:** verify Turnstile token → KV rate limit
  (3/day/IP, keyed on hashed IP) → forward body to the engine Worker with `X-HB-Auth` →
  stream the engine's response through. The OpenAI key lives only in the engine; the
  shared secret lives only in the two Workers.
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
| Cost abuse | Turnstile + 3 docs/IP/day + 50-page/20 MB caps + per-page cache |
| Cold container start | `sleepAfter: 15m` + cached sample doc keeps demos snappy; progress UI absorbs the rest |
| Copyright of uploads | In-memory only, never stored, never public; "upload only content you may use" |
| Noisy/ugly pages | ≤ 6 annotations/page, greedy margin push-down, seeded RNG → reproducible → debuggable |
