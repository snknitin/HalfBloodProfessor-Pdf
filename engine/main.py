"""FastAPI service for deterministic, in-memory PDF annotation."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import os
import random
import urllib.error
import urllib.request
from collections.abc import Awaitable, Callable
from typing import Any

import fitz
from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import Response, StreamingResponse
from openai import APIStatusError, AsyncOpenAI, RateLimitError

from engine.prompts import PROMPT_VERSION, RESPONSE_FORMAT, SYSTEM_PROMPT
from engine.render import annotate_bytes

MAX_PDF_BYTES = 20 * 1024 * 1024
MAX_PAGES = 50
MIN_PAGE_CHARS = 300
MAX_PAGE_TEXT_CHARS = 4_000
MAX_OUTPUT_TOKENS = 700

app = FastAPI(title="hb-pdf engine", docs_url=None, redoc_url=None)

_memory_cache: dict[str, list[dict[str, Any]]] = {}
_cache_locks: dict[str, asyncio.Lock] = {}
_client: AsyncOpenAI | None = None
_llm_semaphore = asyncio.Semaphore(40)
_retry_rng = random.SystemRandom()

ProgressCallback = Callable[[str], Awaitable[None]]


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/annotate")
async def annotate(
    request: Request,
    stream: bool = Query(default=False),
    x_hb_auth: str | None = Header(default=None),
):
    _verify_auth(x_hb_auth)
    pdf_bytes = await _read_pdf(request)

    if not stream:
        result = await _process_pdf(pdf_bytes)
        return Response(
            result,
            media_type="application/pdf",
            headers={"Content-Disposition": 'inline; filename="annotated.pdf"'},
        )

    async def event_stream():
        yield _sse("progress", {"stage": "extracting"})
        queue: asyncio.Queue[str] = asyncio.Queue()

        async def progress(stage: str) -> None:
            await queue.put(stage)

        task = asyncio.create_task(_process_pdf(pdf_bytes, progress))
        try:
            while not task.done():
                try:
                    stage = await asyncio.wait_for(queue.get(), timeout=0.1)
                except TimeoutError:
                    continue
                yield _sse("progress", {"stage": stage})

            while not queue.empty():
                yield _sse("progress", {"stage": queue.get_nowait()})

            result = await task
            yield _sse(
                "done",
                {
                    "stage": "done",
                    "content_type": "application/pdf",
                    "pdf_base64": base64.b64encode(result).decode("ascii"),
                },
            )
        except HTTPException as exc:
            yield _sse("error", {"stage": "error", "detail": exc.detail})
        except Exception:
            yield _sse(
                "error",
                {"stage": "error", "detail": "The PDF could not be annotated."},
            )
        finally:
            if not task.done():
                task.cancel()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _verify_auth(provided: str | None) -> None:
    expected = os.getenv("HB_SHARED_SECRET")
    if not expected:
        raise HTTPException(status_code=503, detail="Engine authentication is not configured.")
    if not provided or not hmac.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="Unauthorized.")


async def _read_pdf(request: Request) -> bytes:
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > MAX_PDF_BYTES:
                raise HTTPException(
                    status_code=413, detail="PDF must be 20 MB or smaller."
                )
        except ValueError:
            pass

    chunks = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > MAX_PDF_BYTES:
            raise HTTPException(status_code=413, detail="PDF must be 20 MB or smaller.")
        chunks.append(chunk)
    if not chunks:
        raise HTTPException(status_code=400, detail="Upload a PDF in the request body.")
    return b"".join(chunks)


def _extract_pages(pdf_bytes: bytes) -> list[str]:
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception as exc:
        raise HTTPException(status_code=422, detail="The upload is not a valid PDF.") from exc

    try:
        if doc.needs_pass:
            raise HTTPException(
                status_code=422, detail="Password-protected PDFs are not supported."
            )
        if doc.page_count == 0:
            raise HTTPException(status_code=422, detail="The PDF has no pages.")
        if doc.page_count > MAX_PAGES:
            raise HTTPException(
                status_code=422, detail="PDF must have 50 pages or fewer."
            )
        texts = [page.get_text("text").strip() for page in doc]
    finally:
        doc.close()

    if not any(texts):
        raise HTTPException(
            status_code=422,
            detail=(
                "This works on digital-text PDFs. Scanned PDFs need OCR and are not "
                "supported."
            ),
        )
    return texts


async def _process_pdf(
    pdf_bytes: bytes, progress: ProgressCallback | None = None
) -> bytes:
    page_texts = await asyncio.to_thread(_extract_pages, pdf_bytes)
    total_pages = len(page_texts)
    completed = 0
    progress_lock = asyncio.Lock()

    async def run_page(page_number: int, page_text: str):
        nonlocal completed
        result = await _page_job(page_number, page_text)
        async with progress_lock:
            completed += 1
            current = completed
        if progress:
            await progress(f"thinking {current}/{total_pages}")
        return result

    page_results = await asyncio.gather(
        *(
            run_page(index + 1, page_text)
            for index, page_text in enumerate(page_texts)
        )
    )

    annotations = []
    diagram_seen = False
    for page_number, page_annotations in sorted(page_results):
        for annotation in page_annotations:
            if annotation["type"] == "diagram":
                if diagram_seen:
                    continue
                diagram_seen = True
            annotations.append({"page": page_number, **annotation})

    if progress:
        await progress("scribbling")
    result, _ = await asyncio.to_thread(annotate_bytes, pdf_bytes, annotations)
    return result


async def _page_job(page_number: int, page_text: str):
    if len(page_text) < MIN_PAGE_CHARS:
        return page_number, []
    annotations = await _annotations_for_page(page_text[:MAX_PAGE_TEXT_CHARS])
    return page_number, annotations


async def _annotations_for_page(page_text: str) -> list[dict[str, Any]]:
    model = os.getenv("HB_MODEL")
    if not model:
        raise HTTPException(status_code=503, detail="HB_MODEL is not configured.")
    cache_key = hashlib.sha256(
        f"{model}\0{PROMPT_VERSION}\0{page_text}".encode("utf-8")
    ).hexdigest()

    cached = _memory_cache.get(cache_key)
    if cached is not None:
        return cached

    lock = _cache_locks.setdefault(cache_key, asyncio.Lock())
    async with lock:
        cached = _memory_cache.get(cache_key)
        if cached is not None:
            return cached

        cached = await _kv_get(cache_key)
        if cached is not None:
            _memory_cache[cache_key] = cached
            return cached

        generated = await _call_openai(model, page_text)
        _memory_cache[cache_key] = generated
        await _kv_put(cache_key, generated)
        return generated


def _get_client() -> AsyncOpenAI:
    global _client
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=503, detail="OPENAI_API_KEY is not configured.")
    if _client is None:
        _client = AsyncOpenAI(api_key=api_key)
    return _client


async def _call_openai(model: str, page_text: str) -> list[dict[str, Any]]:
    client = _get_client()
    for attempt in range(2):
        try:
            async with _llm_semaphore:
                response = await client.responses.create(
                    model=model,
                    instructions=SYSTEM_PROMPT,
                    input=(
                        "Annotate this textbook page. Quotes must be copied exactly from "
                        "the text below.\n\n<page>\n"
                        f"{page_text}\n</page>"
                    ),
                    temperature=0.3,
                    max_output_tokens=MAX_OUTPUT_TOKENS,
                    text={"format": RESPONSE_FORMAT},
                )
            payload = json.loads(response.output_text)
            return _sanitize_annotations(payload)
        except Exception as exc:
            retryable = _is_retryable(exc) or isinstance(
                exc, (json.JSONDecodeError, KeyError, TypeError, ValueError)
            )
            if attempt == 0 and retryable:
                await asyncio.sleep(_retry_rng.uniform(0.2, 0.8))
                continue
            return []
    return []


def _is_retryable(exc: Exception) -> bool:
    if isinstance(exc, RateLimitError):
        return True
    return isinstance(exc, APIStatusError) and exc.status_code >= 500


def _sanitize_annotations(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict) or not isinstance(payload.get("annotations"), list):
        raise ValueError("Invalid annotation payload")

    result = []
    for annotation in payload["annotations"][:6]:
        if not isinstance(annotation, dict):
            continue
        kind = annotation.get("type")
        if kind == "diagram":
            labels = annotation.get("labels")
            if isinstance(labels, list) and 2 <= len(labels) <= 5:
                clean = {
                    "type": "diagram",
                    "labels": [str(label) for label in labels],
                }
                if annotation.get("title"):
                    clean["title"] = str(annotation["title"])
                result.append(clean)
            continue

        if kind not in {
            "underline",
            "strike",
            "circle",
            "highlight",
            "scribble",
            "doodle",
            "margin",
        }:
            continue
        quote = annotation.get("quote")
        if not isinstance(quote, str) or not 3 <= len(quote.split()) <= 8:
            continue

        clean = {"type": kind, "quote": quote}
        if annotation.get("note"):
            clean["note"] = _limit_words(str(annotation["note"]), 14)
        if kind == "underline":
            clean["double"] = bool(annotation.get("double", False))
        elif kind == "strike" and annotation.get("correction"):
            clean["correction"] = _limit_words(str(annotation["correction"]), 5)
        elif kind == "doodle" and annotation.get("symbol") in {
            "star",
            "asterisk",
            "exclaim",
        }:
            clean["symbol"] = annotation["symbol"]
        result.append(clean)
    return result


def _limit_words(text: str, limit: int) -> str:
    return " ".join(text.split()[:limit])


async def _kv_get(key: str) -> list[dict[str, Any]] | None:
    base_url = os.getenv("HB_CACHE_URL")
    if not base_url:
        return None

    def get():
        try:
            with urllib.request.urlopen(f"{base_url.rstrip('/')}/{key}", timeout=2) as response:
                return response.read()
        except (urllib.error.URLError, TimeoutError):
            return None

    raw = await asyncio.to_thread(get)
    if raw is None:
        return None
    try:
        return _sanitize_annotations(json.loads(raw))
    except (json.JSONDecodeError, TypeError, ValueError):
        return None


async def _kv_put(key: str, annotations: list[dict[str, Any]]) -> None:
    base_url = os.getenv("HB_CACHE_URL")
    if not base_url:
        return
    body = json.dumps({"annotations": annotations}, separators=(",", ":")).encode()

    def put():
        request = urllib.request.Request(
            f"{base_url.rstrip('/')}/{key}", data=body, method="PUT"
        )
        request.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(request, timeout=2):
                pass
        except (urllib.error.URLError, TimeoutError):
            pass

    await asyncio.to_thread(put)


def _sse(event: str, data: dict[str, Any]) -> str:
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return f"event: {event}\ndata: {payload}\n\n"
