# hb-pdf engine

Track B phase B1: an authenticated FastAPI service behind a Cloudflare Container
Worker. PDF bodies and annotated results remain in memory. Only annotation JSON is
cached, keyed by a hash; no PDF text or bytes are persisted.

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
`pdf_base64`.

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
