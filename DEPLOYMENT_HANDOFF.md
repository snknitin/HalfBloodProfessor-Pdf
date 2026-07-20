# HalfBlood Professor: production deployment status

Updated: 2026-07-18

## Executive summary

The public website and Python annotation engine are deployed and connected. A production browser test completed Turnstile verification, sent the bundled sample through the Higgsfield server route and Hugging Face engine, invoked OpenAI, and returned a downloadable annotated PDF.

The current Track B architecture uses a Cloudflare **Container**, not an ordinary Worker. Cloudflare allows up to 100 ordinary Workers on the free plan, but it does not provide Container CPU, memory, or disk on that plan. The Cloudflare API rejected the image with:

> Unauthorized: You do not have access to Cloudflare Containers. Deploying containers requires the Workers Paid plan.

This is unrelated to project count or current request usage.

The no-payment production path is active: Higgsfield hosts the UI and server proxy, Cloudflare supplies Turnstile, and a free Hugging Face Docker Space runs Python/PyMuPDF. Cloudflare Containers remain an optional future migration because they require the Workers Paid plan.

## Completed work

### Track A

- Deterministic PyMuPDF renderer is complete.
- Quote matching, handwritten corrections, underlines, circles, arrows, scribbles, doodles, highlights, diagrams, and margin placement work.
- The user has tested the complete local flow with their OpenAI key successfully.

### Track B1 engine

- `engine/main.py`: FastAPI `/annotate` and `/healthz`.
- Raw PDF and SSE response modes.
- Tier-aware 50/150-page and 25/100 MB chapter validation.
- Scanned/non-searchable PDF rejection.
- Concurrent per-page OpenAI Responses API calls.
- Strict structured-output annotation schema.
- Retry-once behavior for 429/5xx.
- Deterministic in-memory rendering.
- In-memory and optional KV annotation cache.
- Shared-secret authentication with `X-HB-Auth`.
- Cloudflare Worker, Durable Object/Container wrapper, Dockerfile, KV binding, and Wrangler config.
- Twenty-five engine tests pass.
- Wrangler dry-run and Docker image build pass.

Root GitHub repository:

- Repository: `snknitin/HalfBloodProfessor-Pdf`
- Main commit: `2021be69fc6049eeaf03162d84d29d6fd9d5e423`
- Merged PR: `https://github.com/snknitin/HalfBloodProfessor-Pdf/pull/2`

### Track B3 website

- Public URL: `https://hb-pdf.higgsfield.app`
- Higgsfield website ID: `035d7dd4-b456-4a94-8377-e99eb4e90c86`
- Current site commit: `68734eb`
- React/TanStack upload interface.
- Original, reference-driven magical annotated-book hero image.
- Dark potion-study visual direction, animated ink strokes, floating embers, parchment dropzone.
- Original public sample PDF.
- Turnstile client widget.
- `/api/annotate` server route.
- Hashed-IP KV rate-limit code for five documents/day plus paid access-key quotas.
- SSE progress UI, PDF preview, and download UI.
- Required legal/privacy footer text.
- Friendly limit, scanned-PDF, and rate-limit errors.
- Production site returns HTTP 200.
- Production sample round-trip returns an annotated PDF.

### Tasks 2–5 implemented locally (not yet deployed)

- The full 15-case B7 matrix passes, including the real 42-page sample, a 150-page
  Teacher's Pet document, concurrent documents, a full-cache repeat, two 400-page
  books, and the 1,200-page friendly rejection.
- Access keys, expiry, 10/day and 100/month Teacher's Pet counters, and cross-device
  browser storage are implemented and tested.
- Professor's Pass chunk planning, live chapter progress, direct engine upload,
  encrypted 24-hour recovery, success-only credit consumption, and one-active-book
  admission are implemented and tested locally.
- Stripe session verification and idempotent fulfillment are implemented. Actual
  Stripe test-mode acceptance remains pending the account-owned Stripe test secret
  and three Payment Links.

### Production runtime

- Engine Space: `https://huggingface.co/spaces/NikeZoldyck/hb-pdf-engine`
- Engine origin: `https://nikezoldyck-hb-pdf-engine.hf.space`
- Hardware: Hugging Face CPU Basic, free tier.
- `GET /healthz` returns `{"status":"ok"}`.
- Runtime secrets and model configuration are installed through host settings and are not committed.
- Higgsfield is configured with the engine URL, shared authentication, Turnstile validation, and rate-limit salt.

The `site/` directory is a separate Higgsfield Git repository and is intentionally ignored by the parent repository.

## Existing Cloudflare resources

- Account ID: `5e38dd8c3a09cad103db7c0d5139f40c`
- Account email: `snk.nitin@gmail.com`
- Workers subdomain: `snk-nitin.workers.dev`
- Engine Worker name: `hb-pdf-engine`
- Uploaded, non-deployed Worker version: `8d166c92-c0cb-44dc-9768-fd9207cbb9b9`
- Engine KV namespace: `HB_CACHE`
- Engine KV ID: `6f8c1b7c890c483f9372bf7793613363`
- Turnstile widget name: `halfblood-professor-pdf`
- Public Turnstile site key: `0x4AAAAAAD4drX-Sk9odIZh4`
- Turnstile allowed hostname: `hb-pdf.higgsfield.app`

Do not create duplicates of these resources.

## Secrets and configuration

Never commit any of these values.

### Engine host

- `OPENAI_API_KEY`: reuse the working local OpenAI key.
- `HB_MODEL`: `gpt-5.4-mini`.
- `HB_SHARED_SECRET`: generate a random 32-byte value once.
- `HB_BOOK_CALLBACK_URL`: `https://hb-pdf.higgsfield.app/api/book/complete`.
- `HB_BOOK_STORAGE_SECRET`: a separate random 32-byte value for encrypted 24-hour results.

### Higgsfield site

- `ENGINE_URL`: public HTTPS origin of the deployed engine, with no trailing slash.
- `HB_SHARED_SECRET`: exact same value as the engine.
- `TURNSTILE_SECRET`: private secret for the existing Turnstile widget.
- `RATE_LIMIT_SALT`: a separate random 32-byte value.
- `STRIPE_SECRET_KEY`: Stripe test secret (`sk_test_...`) until launch.
- `STRIPE_MONTHLY_LINK`, `STRIPE_YEARLY_LINK`, `STRIPE_BOOK_LINK`: the three Stripe
  Payment Link URLs. Configure each Link's post-payment redirect to
  `https://hb-pdf.higgsfield.app/success?session_id={CHECKOUT_SESSION_ID}`.
- `BUY_ME_A_COFFEE_URL`: optional tip URL; it grants no entitlement.

The Stripe prices must be one-time USD payments of exactly `$5.00`, `$40.00`, and
`$3.99`. The success route verifies the Checkout Session directly with Stripe before
minting any key, and repeated visits return the same key.

The OpenAI key belongs only on the engine. It must never be sent to the browser or stored in the site.

## Deployment path A: preserve the Cloudflare Container architecture

This requires Workers Paid. After the account is upgraded:

```powershell
cd E:\GIT_ROOT\Projects\HalfBloodProfessor-Pdf\engine
npx.cmd wrangler deploy
npx.cmd wrangler secret put OPENAI_API_KEY
npx.cmd wrangler secret put HB_MODEL
npx.cmd wrangler secret put HB_SHARED_SECRET
```

Enter `gpt-5.4-mini` for `HB_MODEL`. Enter the same generated secret later into the Higgsfield site.

Expected engine URL:

`https://hb-pdf-engine.snk-nitin.workers.dev`

Verify:

```powershell
curl.exe https://hb-pdf-engine.snk-nitin.workers.dev/healthz
```

Then set the four Higgsfield server secrets and redeploy website ID `035d7dd4-b456-4a94-8377-e99eb4e90c86`.

## Deployment path B: no Cloudflare payment (active)

The engine is deployed to a Hugging Face Docker Space using `engine/Dockerfile.hf`. It provides:

- public HTTPS;
- at least 1 GB memory;
- request timeout of at least 60 seconds;
- environment secrets;
- outbound access to `api.openai.com`;
- scale-to-zero or low-cost idle behavior if desired.

No engine rewrite was required. A local equivalent can be built from the repository root because the Dockerfile copies both `app/` and `engine/`:

```powershell
docker build -f engine/Dockerfile -t hb-pdf-engine .
```

The required engine and site configuration is installed. The public site was redeployed and the bundled sample completed successfully.

Cloudflare can remain free for Turnstile and ordinary Workers/KV. The Python/PyMuPDF execution must stay on the external Docker host.

### Do not choose this shortcut

Do not translate `engine/main.py` into an ordinary Worker during a timed deployment. PyMuPDF is a native Python extension, and the free Worker CPU allowance is only 10 ms per invocation. A correct Worker-native rewrite would require replacing PyMuPDF and retesting the entire deterministic rendering layer.

## Remaining specification work

### B1 production follow-up

- Confirm a repeated run uses cached annotation JSON and makes zero additional LLM calls.
- Add an explicit automated production check for missing/wrong authentication returning 401.

### B2 model quality ladder: not built

- Add `engine/eval_models.py`.
- Compare mini and nano candidates.
- Produce per-model annotated PDFs and summary metrics.
- The current practical model selection is `gpt-5.4-mini` because the user verified its local output.

### B3 website follow-up

- Complete one user-PDF round-trip from another device/phone.
- Confirm the deployed site KV binding increments the five/day counter.
- Connect a PostHog project; capture hooks exist but no project is configured.

### B4 operations checklist

- Confirm both KV bindings: engine cache and site rate limit.
- Warm the bundled sample once and verify cache reuse.
- Configure PostHog and verify the five specified events without filenames or content.
- Test real 25 MB free and 100 MB Teacher's Pet requests end to end.
- Verify a request timeout of at least 60 seconds.
- Put `tests/test_engine.py` and `tests/test_smoke.py` into CI.

### B5 optional polish

- 15-30 second Remotion promo clip.
- Replace the older OG SVG with a social card based on the new annotated-book visual system.
- Add a two- or three-page before/after gallery.
- Add personas only if demo feedback justifies it.

## Production verification checklist

1. `GET <ENGINE_URL>/healthz` returns `{"status":"ok"}`.
2. Missing or wrong `X-HB-Auth` returns 401.
3. Site Turnstile completes on `hb-pdf.higgsfield.app`.
4. Sample button selects the original sample PDF.
5. Annotation emits Reading/Thinking/Scribbling progress.
6. Annotated PDF renders inline and downloads.
7. Sixth request from the same IP/day returns 429.
8. 51-page PDF is rejected with the friendly limit message.
9. Scanned PDF is rejected with the OCR guidance.
10. No PDF bytes or extracted text appear in KV, logs, PostHog, R2, or D1.

## Follow-up implementation task

Continue with the remaining B2 evaluation harness, production cache/rate-limit checks, PostHog configuration, CI smoke tests, and optional B5 polish. Do not recreate the existing Turnstile widget, KV resources, Hugging Face Space, or Higgsfield site.
