# HalfBlood Professor PDF

Upload a searchable textbook chapter and get back a new PDF with useful underlines,
circles, corrections, diagrams, and handwritten margin notes. The AI decides what to
mark; deterministic Python draws every coordinate and pen stroke.

Public site: **https://hb-pdf.higgsfield.app**

## Videos

### Motivation

[![Watch the HalfBlood Professor motivation video](https://img.youtube.com/vi/jVXj5G1zeqo/hqdefault.jpg)](https://youtu.be/jVXj5G1zeqo)

### Demo

[![Watch the HalfBlood Professor demo video](https://img.youtube.com/vi/sMI9_z5XCMk/hqdefault.jpg)](https://youtu.be/sMI9_z5XCMk)

> Upload only content you have the right to use. Annotations are AI-generated and may
> be wrong. PDF bytes and extracted text are processed in memory and never stored.

## Current architecture

1. The Higgsfield site accepts a PDF, verifies Cloudflare Turnstile, and enforces three
   free requests per IP hash per day with KV.
2. Its server route streams the file to the authenticated Cloudflare engine.
3. FastAPI extracts text with PyMuPDF and calls OpenAI once per page with a strict
   structured-output schema.
4. The unchanged Track A renderer maps exact quotes to coordinates and returns the
   annotated PDF as a streamed result.

| Part | Implementation |
| --- | --- |
| Website | React 19 + TanStack Start on Higgsfield |
| API protection | Cloudflare Turnstile + server-side secret verification |
| Rate limit | 3 annotations per IP hash per UTC day in KV |
| Engine | FastAPI + PyMuPDF in a Cloudflare Container |
| LLM | OpenAI Responses API, `gpt-5.4-mini`, strict structured outputs |
| Storage | No PDF storage; annotation JSON cache only |

## Limits

- Searchable, digital-text PDFs only; scanned PDFs need OCR first.
- Up to 50 pages and 20 MB.
- English-first annotations.

## Local renderer quickstart

```powershell
pip install pymupdf
python -m app.pipeline "samples/Ch1 - Introductions.pdf" app/annotations_ch1.json `
  outputs/Ch1_annotated.pdf --pages 2-6 --previews outputs/preview
python tests/test_smoke.py
```

## Engine tests

```powershell
docker build -f engine/Dockerfile -t hb-pdf-engine .
docker run --rm hb-pdf-engine python -m unittest discover -s tests -p test_engine.py
```

## Production activation

The visual site is deployed. The upload API becomes live after these account-owned
secrets are entered:

1. Register this Cloudflare account's `workers.dev` subdomain once at the
   [Workers onboarding page](https://dash.cloudflare.com/5e38dd8c3a09cad103db7c0d5139f40c/workers/onboarding).
2. From `engine/`, deploy the Worker and enter the OpenAI key only at Wrangler's hidden
   prompt:

```powershell
cd engine
npm run deploy
npx.cmd wrangler secret put OPENAI_API_KEY
```

`HB_MODEL` is not another key. It is the model name, currently `gpt-5.4-mini`.
`HB_SHARED_SECRET` is not purchased or acquired from a provider. It is a random private
password generated once and installed on both the engine and site so only the site can
call the engine. The Turnstile widget already exists; its private verification value
must also be installed as a site secret.

See [engine/README.md](engine/README.md) for the service commands and
[BUILD_SPEC.md](BUILD_SPEC.md) for the complete product specification.

## Status

- [x] Track A deterministic PDF renderer
- [x] Track B1 authenticated engine, structured OpenAI calls, caching, SSE, tests
- [x] 50-page and 20 MB validation
- [x] Higgsfield website, responsive upload UI, sample PDF, preview, download
- [x] Turnstile widget and server verification path
- [x] KV daily rate-limit path
- [x] Public website deployment
- [ ] One-time Cloudflare Workers subdomain registration
- [ ] Account-owned production secret entry and final live API round-trip
