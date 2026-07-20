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

1. The Higgsfield site accepts a PDF, verifies Cloudflare Turnstile, and enforces five
   free requests per IP hash per day or paid access-key quotas with KV.
2. Its server route streams chapters to the authenticated Hugging Face engine. Whole
   books upload directly to the engine with a short-lived, site-signed authorization.
3. FastAPI extracts text with PyMuPDF and calls OpenAI once per page with a strict
   structured-output schema.
4. The unchanged Track A renderer maps exact quotes to coordinates and returns the
   annotated PDF as a streamed result. Whole books run in chapter-aware chunks and the
   encrypted result remains recoverable with its access key for 24 hours.

| Part | Implementation |
| --- | --- |
| Website | React 19 + TanStack Start on Higgsfield |
| API protection | Cloudflare Turnstile + server-side secret verification |
| Rate limit | Free IP quota plus Teacher's Pet and Professor's Pass keys in KV |
| Engine | FastAPI + PyMuPDF in a free Hugging Face Docker Space |
| LLM | OpenAI Responses API, `gpt-5.4-mini`, strict structured outputs |
| Storage | Sources never stored; completed books encrypted on engine disk for 24 hours |

## Limits

- Searchable, digital-text PDFs only; scanned PDFs need OCR first.
- Free: 50 pages, 25 MB, 5 documents/day.
- Teacher's Pet: 150 pages, 100 MB, 10/day and 100/month.
- Professor's Pass: one book up to 1,000 pages and 150 MB.
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

## Production configuration

The visual site and chapter engine are already deployed. The OpenAI key stays only in
the Hugging Face Space. See [DEPLOYMENT_HANDOFF.md](DEPLOYMENT_HANDOFF.md) for the exact
Hugging Face and Higgsfield variables required by the tier, book, and Stripe features.

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
- [x] Free and Teacher's Pet tier limits and access-key quotas
- [x] Chapter-aware whole-book pipeline and encrypted 24-hour recovery
- [x] Stripe paid-session fulfillment routes and receipt-key recovery
- [x] Higgsfield website, responsive upload UI, sample PDF, preview, download
- [x] Turnstile widget and server verification path
- [x] KV daily rate-limit path
- [x] Public website deployment
- [x] Full local and deployed B7 matrices, including 150-page and 400-page cases
- [x] Three one-time Stripe test products and Payment Links with success redirects
- [ ] Add the Stripe test secret to Higgsfield and run all three test checkouts
- [ ] Add the optional Buy Me a Coffee profile URL
