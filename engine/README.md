# hb-pdf engine

An authenticated FastAPI/PyMuPDF service deployed as a Hugging Face Docker Space.
Source PDF bodies and chapter results remain in memory. Annotation JSON may be cached
by hash. A completed Professor's Pass book is encrypted with its access key and kept
on engine disk for at most 24 hours as delivery insurance.

## Local container

Build from the repository root so the unchanged Track A `app/` package is included:

```powershell
docker build -f engine/Dockerfile -t hb-pdf-engine .
docker run --rm -p 8080:8080 `
  -e OPENAI_API_KEY=replace-later `
  -e HB_MODEL=replace-later `
  -e HB_SHARED_SECRET=local-secret `
  hb-pdf-engine
```

Health check:

```powershell
curl.exe http://localhost:8080/healthz
```

Plain PDF response:

```powershell
curl.exe -X POST http://localhost:8080/annotate `
  -H "X-HB-Auth: local-secret" `
  -H "Content-Type: application/pdf" `
  --data-binary "@samples/Ch1 - Introductions.pdf" `
  --output outputs/annotated-service.pdf
```

Add `?stream=1` for SSE progress. The final `done` event contains the result in
`pdf_base64` plus content-free processing metadata. Page progress identifies
`success`, `valid_empty`, `skipped`, `failed`, and `timed_out` results. Plain PDF
responses expose the compact form of the same data in `X-HB-Metadata`.

Operational failures are never cached. A document may finish with a small number
of failed pages (reported in metadata), but fails clearly instead of returning a
misleading partial result when more than 20% of readable pages fail. Inference is
deadline-aware; set `HB_DOCUMENT_DEADLINE_SECONDS` to override the 55-second
default.

## Whole-book route

`POST /annotate-book` accepts up to 1,000 pages / 150 MB and requires
`X-HB-Access-Key` plus a short-lived `X-HB-Book-Token` minted by the site. It emits an
SSE plan and chapter start/done events, processes chapter-aware chunks sequentially,
and returns a `result_id`. Download with `GET /book-result/{result_id}` and the same
access-key header. Set:

- `HB_BOOK_CALLBACK_URL=https://hb-pdf.higgsfield.app/api/book/complete`
- `HB_BOOK_STORAGE_SECRET` to a separate random 32-byte value (recommended; the
  shared secret is used as a fallback)
- `HB_BOOK_RESULT_DIR` only when overriding the default `/tmp/hb-book-results`

## Cloudflare setup

From `engine/`, install the Worker dependencies, create `HB_CACHE`, and replace the
zero placeholder ID in `wrangler.jsonc` with the returned namespace ID:

```powershell
npm install
npx.cmd wrangler kv namespace create HB_CACHE
```

Provide runtime values only when you are ready to deploy:

```powershell
npx.cmd wrangler secret put OPENAI_API_KEY
npx.cmd wrangler secret put HB_MODEL
npx.cmd wrangler secret put HB_SHARED_SECRET
npm run deploy
```

Set `HB_MODEL` to `gpt-5.4-mini`. It is a model name, not a key. Use a long random
value for `HB_SHARED_SECRET`; the site server must receive the exact same value.
