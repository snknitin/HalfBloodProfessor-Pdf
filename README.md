# Half-Blood Professor PDF

Upload a textbook chapter. Get it back annotated like the Half-Blood Prince's copy of
*Advanced Potion-Making* — outdated facts struck out with corrections inked above them,
weak claims circled with arrows to caustic margin notes, the important lines underlined,
the hopeless paragraphs scribbled out entirely. In handwriting, in the margins, on your PDF.

> "This prototype supports small chapters." Upload only content you have the right to use.
> Annotations are AI-generated and may be wrong.

## How it works

1. **Extract** — PyMuPDF pulls the text (with coordinates) from each page.
2. **Think** — one LLM call per page returns JSON: which exact phrases to strike, circle,
   underline, or scribble out, and what the margin notes say.
3. **Scribble** — deterministic Python maps each quoted phrase back to its coordinates
   (`page.search_for`) and draws hand-jittered vector ink: wavy strikethroughs, imperfect
   circles, rotated cursive margin notes in an embedded handwriting font.
4. **Download** — the annotated PDF streams straight back. Nothing is stored.

The LLM only decides *what* to mark and *what the notes say* — every coordinate, wobble,
and pen stroke is seeded, deterministic Python, so inference cost stays at one small
JSON-mode call per page and identical uploads produce identical ink.

## Stack

| | |
|---|---|
| Server + pipeline | Python, FastAPI, PyMuPDF (one service, no queue, no DB) |
| LLM | OpenAI API, JSON mode, one call per page, cached by page hash |
| Frontend | Single static HTML page (drag-drop, inline preview, download) |
| Fonts | Caveat + Homemade Apple (OFL, embedded) |
| Analytics | PostHog (3 events) |
| Hosting | Railway/Render behind Cloudflare DNS |

Full architecture, scope decisions, LLM contract, and rendering spec: **[BUILD_SPEC.md](BUILD_SPEC.md)**

## Quickstart

```bash
pip install pymupdf

# annotate a PDF from an annotation JSON (see app/annotations_ch1.json for the schema)
python -m app.pipeline "samples/Ch1 - Introductions.pdf" app/annotations_ch1.json \
       outputs/Ch1_annotated.pdf --pages 2-6 --previews outputs/preview

# smoke test (one of each ink mark, incl. the ligature-matching fallback)
python tests/test_smoke.py
```

The annotation JSON is exactly what the LLM will emit (see the contract in
[BUILD_SPEC.md](BUILD_SPEC.md#llm-contract)); today it can also be authored by hand,
which keeps the renderer testable with zero inference cost.

## Limits (by design)

Digital-text PDFs only (no OCR), ≤ 15 pages, ≤ 10 MB, English-first. See the cut list in
[BUILD_SPEC.md](BUILD_SPEC.md#out-cut-with-re-add-triggers) for what was deliberately skipped and when it comes back.

## Status

- [x] Problem refined, references collected ([references/](references/))
- [x] Build spec
- [x] Phase 1: ink primitives ([app/scribe.py](app/scribe.py)) — wavy strike/underline, circles,
      arrows, highlights, scribbles, doodles, margin notes, vertical/horizontal chain diagrams
- [x] Phase 2: quote → coordinates with ligature fallback + margin placement engine
      ([app/pipeline.py](app/pipeline.py))
- [x] End-to-end proof: [outputs/Ch1_annotated.pdf](outputs/Ch1_annotated.pdf) — 5 pages,
      25 expert annotations, from [app/annotations_ch1.json](app/annotations_ch1.json)
- [ ] Phase 3: LLM per page (annotation JSON currently hand-authored to the same schema)
- [ ] Phase 5: web UI (FastAPI + static page)
- [ ] Phase 6: deploy + PostHog
