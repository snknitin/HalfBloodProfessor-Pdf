"""FastAPI service for deterministic, in-memory PDF annotation."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import math
import os
import random
import time
import urllib.error
import urllib.request
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

import fitz
from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    RateLimitError,
)

from engine.prompts import PROMPT_VERSION, RESPONSE_FORMAT, SYSTEM_PROMPT
from engine.render import annotate_bytes
from engine.validation import sanitize_annotations
from engine.books import (
    BOOK_MAX_BYTES,
    BookChunk,
    extract_chunk,
    inspect_book,
    latest_result,
    load_encrypted_result,
    original_toc,
    save_encrypted_result,
    stitch_chunks,
)

FREE_MAX_PDF_BYTES = 25 * 1024 * 1024
FREE_MAX_PAGES = 50
TEACHER_MAX_PDF_BYTES = 100 * 1024 * 1024
TEACHER_MAX_PAGES = 150
MIN_PAGE_CHARS = 300
MAX_PAGE_TEXT_CHARS = 4_000
MAX_OUTPUT_TOKENS = 1_400
DEFAULT_DOCUMENT_DEADLINE_SECONDS = 55.0
MAX_PAGE_CALL_SECONDS = 25.0
MIN_RETRY_BUDGET_SECONDS = 1.0
MAX_FAILED_PAGE_RATIO = 0.20

logger = logging.getLogger(__name__)

app = FastAPI(title="hb-pdf engine", docs_url=None, redoc_url=None)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://hb-pdf.higgsfield.app",
        "http://localhost:3000",
        "http://localhost:5173",
    ],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "X-HB-Access-Key", "X-HB-Book-Token"],
    expose_headers=["Content-Disposition"],
)

_memory_cache: dict[str, list[dict[str, Any]]] = {}
_cache_locks: dict[str, asyncio.Lock] = {}
_client: AsyncOpenAI | None = None
_llm_semaphore = asyncio.Semaphore(40)
_retry_rng = random.SystemRandom()
_book_lock = asyncio.Lock()
_background_book_tasks: set[asyncio.Task[Any]] = set()
_redeemed_book_tokens: set[str] = set()
_active_book_keys: set[str] = set()

ProgressEvent = dict[str, Any]
ProgressCallback = Callable[[ProgressEvent], Awaitable[None]]


@dataclass
class InferenceResult:
    status: str
    annotations: list[dict[str, Any]] = field(default_factory=list)
    error_category: str | None = None
    attempts: int = 0
    cache_hit: bool = False
    usage: dict[str, int] = field(default_factory=dict)


@dataclass
class PageResult(InferenceResult):
    page_number: int = 0


@dataclass
class ProcessResult:
    pdf_bytes: bytes
    metadata: dict[str, Any]


class DocumentProcessingError(HTTPException):
    def __init__(self, status_code: int, detail: str, metadata: dict[str, Any]):
        super().__init__(status_code=status_code, detail=detail)
        self.metadata = metadata


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/annotate")
async def annotate(
    request: Request,
    stream: bool = Query(default=False),
    x_hb_auth: str | None = Header(default=None),
    x_hb_tier: str | None = Header(default=None),
):
    _verify_auth(x_hb_auth)
    max_bytes, max_pages = _tier_limits(x_hb_tier)
    pdf_bytes = await _read_pdf(request, max_bytes)

    if not stream:
        result = await _process_pdf(pdf_bytes, max_pages=max_pages)
        return Response(
            result.pdf_bytes,
            media_type="application/pdf",
            headers={
                "Content-Disposition": 'inline; filename="annotated.pdf"',
                "X-HB-Metadata": _metadata_header(result.metadata),
            },
        )

    async def event_stream():
        yield _sse("progress", {"stage": "extracting"})
        queue: asyncio.Queue[ProgressEvent] = asyncio.Queue()

        async def progress(event: ProgressEvent) -> None:
            await queue.put(event)

        task = asyncio.create_task(_process_pdf(pdf_bytes, progress, max_pages=max_pages))
        try:
            while not task.done():
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=0.1)
                except TimeoutError:
                    continue
                yield _sse("progress", event)

            while not queue.empty():
                yield _sse("progress", queue.get_nowait())

            result = await task
            yield _sse(
                "done",
                {
                    "stage": "done",
                    "content_type": "application/pdf",
                    "pdf_base64": base64.b64encode(result.pdf_bytes).decode("ascii"),
                    "metadata": result.metadata,
                },
            )
        except HTTPException as exc:
            payload = {
                "stage": "error",
                "detail": exc.detail,
                "status_code": exc.status_code,
            }
            metadata = getattr(exc, "metadata", None)
            if metadata is not None:
                payload["metadata"] = metadata
            yield _sse("error", payload)
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


@app.post("/annotate-book")
async def annotate_book(
    request: Request,
    x_hb_access_key: str | None = Header(default=None),
    x_hb_book_token: str | None = Header(default=None),
):
    """Process one whole book directly at the engine with site-signed authorization."""
    access_key = (x_hb_access_key or "").strip().lower()
    token_id = _verify_book_token(x_hb_book_token, access_key)
    if token_id in _redeemed_book_tokens:
        raise HTTPException(status_code=409, detail="This Professor's Pass has already finished a book.")
    if access_key in _active_book_keys:
        raise HTTPException(
            status_code=409,
            detail="This Professor's Pass already has a book on the professor's desk.",
        )
    try:
        await asyncio.to_thread(latest_result, access_key)
    except HTTPException as exc:
        if exc.status_code not in {404, 410}:
            raise
    else:
        raise HTTPException(
            status_code=409,
            detail="This Professor's Pass has already finished a book.",
        )

    _redeemed_book_tokens.add(token_id)
    _active_book_keys.add(access_key)
    try:
        pdf_bytes = await _read_pdf(request, BOOK_MAX_BYTES)
    except Exception:
        _active_book_keys.discard(access_key)
        raise
    was_queued = _book_lock.locked()

    async def event_stream():
        queue: asyncio.Queue[ProgressEvent] = asyncio.Queue()

        async def progress(event: ProgressEvent) -> None:
            await queue.put(event)

        async def run() -> ProcessResult:
            if was_queued:
                await progress(
                    {
                        "stage": "queued",
                        "detail": "Another book is on the professor's desk. Yours will start next.",
                    }
                )
            async with _book_lock:
                return await _process_book(pdf_bytes, access_key, token_id, progress)

        task = asyncio.create_task(run())
        _background_book_tasks.add(task)

        def release_book(completed: asyncio.Task[Any]) -> None:
            _background_book_tasks.discard(completed)
            _active_book_keys.discard(access_key)

        task.add_done_callback(release_book)
        try:
            while not task.done():
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=0.25)
                except TimeoutError:
                    continue
                yield _sse("progress", event)
            while not queue.empty():
                yield _sse("progress", queue.get_nowait())
            result = await task
            yield _sse("done", {"stage": "done", **result.metadata})
        except HTTPException as exc:
            yield _sse(
                "error",
                {"stage": "error", "status_code": exc.status_code, "detail": exc.detail},
            )
        except Exception:
            logger.exception("book_processing_failed")
            yield _sse(
                "error",
                {
                    "stage": "error",
                    "detail": "The book could not be completed. Your credit was not consumed.",
                },
            )
        # Deliberately do not cancel task on disconnect. The encrypted result remains
        # recoverable for 24 hours, which is the paid delivery guarantee.

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-store", "X-Accel-Buffering": "no"},
    )


@app.get("/book-result/{result_id}")
async def book_result(
    result_id: str,
    x_hb_access_key: str | None = Header(default=None),
):
    access_key = (x_hb_access_key or "").strip().lower()
    if not access_key:
        raise HTTPException(status_code=401, detail="Enter the Professor's Pass that created this result.")
    pdf_bytes = await asyncio.to_thread(load_encrypted_result, result_id, access_key)
    return Response(
        pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="professors-notes.pdf"'},
    )


@app.get("/book-result-latest")
async def book_result_latest(x_hb_access_key: str | None = Header(default=None)):
    access_key = (x_hb_access_key or "").strip().lower()
    if not access_key:
        raise HTTPException(status_code=401, detail="Enter the Professor's Pass used for this book.")
    return await asyncio.to_thread(latest_result, access_key)


def _verify_auth(provided: str | None) -> None:
    expected = os.getenv("HB_SHARED_SECRET")
    if not expected:
        raise HTTPException(status_code=503, detail="Engine authentication is not configured.")
    if not provided or not hmac.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="Unauthorized.")


def _tier_limits(tier: str | None) -> tuple[int, int]:
    normalized = tier.strip().lower() if isinstance(tier, str) else "free"
    if normalized == "free":
        return FREE_MAX_PDF_BYTES, FREE_MAX_PAGES
    if normalized == "teacher":
        return TEACHER_MAX_PDF_BYTES, TEACHER_MAX_PAGES
    raise HTTPException(status_code=400, detail="Unknown annotation tier.")


async def _read_pdf(request: Request, max_bytes: int = FREE_MAX_PDF_BYTES) -> bytes:
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > max_bytes:
                raise HTTPException(
                    status_code=413, detail=f"PDF must be {_mb(max_bytes)} MB or smaller."
                )
        except ValueError:
            pass

    chunks = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(
                status_code=413, detail=f"PDF must be {_mb(max_bytes)} MB or smaller."
            )
        chunks.append(chunk)
    if not chunks:
        raise HTTPException(status_code=400, detail="Upload a PDF in the request body.")
    return b"".join(chunks)


def _extract_pages(pdf_bytes: bytes, max_pages: int = FREE_MAX_PAGES) -> list[str]:
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
        if doc.page_count > max_pages:
            raise HTTPException(
                status_code=422, detail=f"PDF must have {max_pages} pages or fewer."
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
    pdf_bytes: bytes,
    progress: ProgressCallback | None = None,
    max_pages: int = FREE_MAX_PAGES,
) -> ProcessResult:
    page_texts = await asyncio.to_thread(_extract_pages, pdf_bytes, max_pages)
    total_pages = len(page_texts)
    deadline = asyncio.get_running_loop().time() + _document_deadline_seconds()
    completed = 0
    progress_lock = asyncio.Lock()

    async def run_page(page_number: int, page_text: str) -> PageResult:
        nonlocal completed
        result = await _page_job(page_number, page_text, deadline)
        async with progress_lock:
            completed += 1
            current = completed
        if progress:
            event: ProgressEvent = {
                "stage": f"thinking {current}/{total_pages}",
                "page": page_number,
                "status": result.status,
            }
            if result.error_category:
                event["error_category"] = result.error_category
            await progress(event)
        return result

    page_results = await asyncio.gather(
        *(
            run_page(index + 1, page_text)
            for index, page_text in enumerate(page_texts)
        )
    )

    metadata = _page_metadata(page_results, total_pages)
    failed = [result for result in page_results if result.status in {"failed", "timed_out"}]
    eligible = [result for result in page_results if result.status != "skipped"]
    allowed_failures = math.floor(len(eligible) * MAX_FAILED_PAGE_RATIO)
    if len(failed) > allowed_failures:
        detail = (
            f"The annotation service failed on {len(failed)} of {len(eligible)} readable "
            "pages. No partial PDF was returned; please try again."
        )
        raise DocumentProcessingError(503, detail, metadata)

    annotations: list[dict[str, Any]] = []
    diagram_seen = False
    for page_result in sorted(page_results, key=lambda result: result.page_number):
        if page_result.status not in {"success", "valid_empty"}:
            continue
        for annotation in page_result.annotations:
            if annotation["type"] == "diagram":
                if diagram_seen:
                    continue
                diagram_seen = True
            annotations.append({"page": page_result.page_number, **annotation})

    if progress:
        await progress({"stage": "scribbling"})
    rendered, render_report = await asyncio.to_thread(annotate_bytes, pdf_bytes, annotations)
    metadata["render"] = render_report.metadata()
    return ProcessResult(rendered, metadata)


async def _process_book(
    pdf_bytes: bytes,
    access_key: str,
    token_id: str,
    progress: ProgressCallback,
) -> ProcessResult:
    total_pages, plans = await asyncio.to_thread(inspect_book, pdf_bytes)
    await progress(
        {
            "stage": "book_plan",
            "total_pages": total_pages,
            "chunks": [plan.metadata() for plan in plans],
        }
    )
    rendered_chunks: list[bytes] = []
    chapter_metadata: list[dict[str, Any]] = []
    for plan in plans:
        await progress({"stage": "chapter_start", "chunk": plan.metadata()})
        chunk_bytes = await asyncio.to_thread(extract_chunk, pdf_bytes, plan)

        async def chunk_progress(event: ProgressEvent, current: BookChunk = plan) -> None:
            await progress({**event, "chunk": current.metadata()})

        result = await _process_pdf(
            chunk_bytes,
            progress=chunk_progress,
            max_pages=plan.end_page - plan.start_page + 1,
        )
        rendered_chunks.append(result.pdf_bytes)
        chapter_metadata.append({"chunk": plan.metadata(), "metadata": result.metadata})
        await progress({"stage": "chapter_done", "chunk": plan.metadata()})

    await progress({"stage": "stitching", "detail": "Binding the annotated chapters"})
    toc = await asyncio.to_thread(original_toc, pdf_bytes)
    stitched = await asyncio.to_thread(stitch_chunks, rendered_chunks, toc)
    result_id, expires_at = await asyncio.to_thread(save_encrypted_result, stitched, access_key)
    callback_ok = await _notify_book_success(access_key, result_id, expires_at)
    metadata = {
        "result_id": result_id,
        "expires_at": expires_at,
        "total_pages": total_pages,
        "chapters": chapter_metadata,
        "credit_consumed": callback_ok,
        "download_path": f"/book-result/{result_id}",
    }
    return ProcessResult(b"", metadata)


async def _notify_book_success(access_key: str, result_id: str, expires_at: int) -> bool:
    callback_url = os.getenv("HB_BOOK_CALLBACK_URL")
    shared_secret = os.getenv("HB_SHARED_SECRET")
    if not callback_url or not shared_secret:
        # Local harness mode has no production KV. The successful result is still valid.
        return False
    body = json.dumps(
        {"access_key": access_key, "result_id": result_id, "expires_at": expires_at}
    ).encode("utf-8")

    def notify() -> bool:
        request = urllib.request.Request(callback_url, data=body, method="POST")
        request.add_header("Content-Type", "application/json")
        request.add_header("X-HB-Auth", shared_secret)
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return 200 <= response.status < 300
        except (urllib.error.URLError, TimeoutError):
            return False

    for attempt in range(5):
        if await asyncio.to_thread(notify):
            return True
        if attempt < 4:
            await asyncio.sleep(min(2 ** attempt, 8))
    return False


def _verify_book_token(token: str | None, access_key: str) -> str:
    if not token or not access_key:
        raise HTTPException(status_code=401, detail="Authorize this Professor's Pass on the site first.")
    try:
        encoded, signature = token.split(".", 1)
        padding = "=" * (-len(encoded) % 4)
        payload_bytes = base64.urlsafe_b64decode(encoded + padding)
        payload = json.loads(payload_bytes)
    except (ValueError, json.JSONDecodeError, TypeError) as exc:
        raise HTTPException(status_code=401, detail="Book authorization is not valid.") from exc
    secret = os.getenv("HB_SHARED_SECRET")
    if not secret:
        raise HTTPException(status_code=503, detail="Book authorization is not configured.")
    expected = hmac.new(secret.encode(), payload_bytes, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise HTTPException(status_code=401, detail="Book authorization is not valid.")
    if int(payload.get("exp", 0)) <= int(time.time()):
        raise HTTPException(status_code=401, detail="Book authorization expired. Start the upload again.")
    access_hash = hashlib.sha256(access_key.encode()).hexdigest()
    if not hmac.compare_digest(str(payload.get("key_hash", "")), access_hash):
        raise HTTPException(status_code=403, detail="That Professor's Pass does not match this upload.")
    token_id = str(payload.get("jti", ""))
    if len(token_id) < 16:
        raise HTTPException(status_code=401, detail="Book authorization is not valid.")
    return token_id


async def _page_job(page_number: int, page_text: str, deadline: float) -> PageResult:
    if len(page_text) < MIN_PAGE_CHARS:
        return PageResult(page_number=page_number, status="skipped")
    inference = await _annotations_for_page(
        page_text[:MAX_PAGE_TEXT_CHARS], deadline, page_number
    )
    return PageResult(
        page_number=page_number,
        status=inference.status,
        annotations=inference.annotations,
        error_category=inference.error_category,
        attempts=inference.attempts,
        cache_hit=inference.cache_hit,
        usage=inference.usage,
    )


async def _annotations_for_page(
    page_text: str, deadline: float, page_number: int
) -> InferenceResult:
    model = os.getenv("HB_MODEL")
    if not model:
        raise HTTPException(status_code=503, detail="HB_MODEL is not configured.")
    cache_key = hashlib.sha256(
        f"{model}\0{PROMPT_VERSION}\0{page_text}".encode("utf-8")
    ).hexdigest()

    cached = _memory_cache.get(cache_key)
    if cached is not None:
        return _cached_result(cached)

    lock = _cache_locks.setdefault(cache_key, asyncio.Lock())
    async with lock:
        cached = _memory_cache.get(cache_key)
        if cached is not None:
            return _cached_result(cached)

        cached = await _kv_get(cache_key)
        if cached is not None:
            _memory_cache[cache_key] = cached
            return _cached_result(cached)

        generated = await _call_openai(model, page_text, deadline, page_number)
        if generated.status in {"success", "valid_empty"}:
            _memory_cache[cache_key] = generated.annotations
            await _kv_put(cache_key, generated.annotations)
        return generated


def _get_client() -> AsyncOpenAI:
    global _client
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=503, detail="OPENAI_API_KEY is not configured.")
    if _client is None:
        _client = AsyncOpenAI(api_key=api_key)
    return _client


async def _call_openai(
    model: str, page_text: str, deadline: float, page_number: int
) -> InferenceResult:
    client = _get_client()
    for attempt in range(2):
        attempts = attempt + 1
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            _log_llm_failure(page_number, "document_deadline", attempts)
            return InferenceResult(
                status="timed_out",
                error_category="document_deadline",
                attempts=attempts - 1,
            )
        try:
            timeout = min(MAX_PAGE_CALL_SECONDS, remaining)
            response = await asyncio.wait_for(
                _create_response(client, model, page_text), timeout=timeout
            )
            payload = json.loads(response.output_text)
            annotations = _sanitize_annotations(payload)
            return InferenceResult(
                status="success" if annotations else "valid_empty",
                annotations=annotations,
                attempts=attempts,
                usage=_response_usage(response),
            )
        except Exception as exc:
            category, timed_out = _llm_error_category(exc)
            retryable = _is_retryable(exc) or category == "parse_error"
            if attempt == 0 and retryable:
                delay = _retry_rng.uniform(0.2, 0.8)
                retry_budget = deadline - asyncio.get_running_loop().time()
                if retry_budget > delay + MIN_RETRY_BUDGET_SECONDS:
                    await asyncio.sleep(delay)
                    continue
                category = "document_deadline"
                timed_out = True
            _log_llm_failure(page_number, category, attempts)
            return InferenceResult(
                status="timed_out" if timed_out else "failed",
                error_category=category,
                attempts=attempts,
            )
    return InferenceResult(status="failed", error_category="unknown", attempts=2)


async def _create_response(client: AsyncOpenAI, model: str, page_text: str):
    async with _llm_semaphore:
        return await client.responses.create(
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


def _is_retryable(exc: Exception) -> bool:
    if isinstance(
        exc,
        (RateLimitError, APIConnectionError, APITimeoutError, asyncio.TimeoutError),
    ):
        return True
    return isinstance(exc, APIStatusError) and exc.status_code >= 500


def _sanitize_annotations(payload: Any) -> list[dict[str, Any]]:
    return sanitize_annotations(payload)


def _cached_result(annotations: list[dict[str, Any]]) -> InferenceResult:
    return InferenceResult(
        status="success" if annotations else "valid_empty",
        annotations=annotations,
        cache_hit=True,
    )


def _llm_error_category(exc: Exception) -> tuple[str, bool]:
    if isinstance(exc, (asyncio.TimeoutError, APITimeoutError)):
        return "timeout", True
    if isinstance(exc, RateLimitError):
        return "rate_limit", False
    if isinstance(exc, APIConnectionError):
        return "connection_error", False
    if isinstance(exc, APIStatusError):
        if exc.status_code in {401, 403}:
            return "authentication_error", False
        if exc.status_code == 429:
            return "rate_limit", False
        if exc.status_code >= 500:
            return "upstream_server_error", False
        return "upstream_request_error", False
    if isinstance(
        exc,
        (json.JSONDecodeError, AttributeError, KeyError, TypeError, ValueError),
    ):
        return "parse_error", False
    return "operational_error", False


def _log_llm_failure(page_number: int, category: str, attempts: int) -> None:
    logger.warning(
        "llm_page_failed page=%s category=%s attempts=%s",
        page_number,
        category,
        attempts,
    )


def _page_metadata(page_results: list[PageResult], total_pages: int) -> dict[str, Any]:
    failures = [
        {
            "page": result.page_number,
            "status": result.status,
            "category": result.error_category,
            "attempts": result.attempts,
        }
        for result in page_results
        if result.status in {"failed", "timed_out"}
    ]
    usage = {
        "input_tokens": sum(result.usage.get("input_tokens", 0) for result in page_results),
        "cached_input_tokens": sum(
            result.usage.get("cached_input_tokens", 0) for result in page_results
        ),
        "output_tokens": sum(result.usage.get("output_tokens", 0) for result in page_results),
        "reasoning_tokens": sum(
            result.usage.get("reasoning_tokens", 0) for result in page_results
        ),
    }
    return {
        "model": os.getenv("HB_MODEL", ""),
        "total_pages": total_pages,
        "eligible_pages": sum(result.status != "skipped" for result in page_results),
        "annotated_pages": sum(result.status == "success" for result in page_results),
        "valid_empty_pages": [
            result.page_number for result in page_results if result.status == "valid_empty"
        ],
        "skipped_pages": [
            result.page_number for result in page_results if result.status == "skipped"
        ],
        "failed_pages": failures,
        "cache_hit_pages": [
            result.page_number for result in page_results if result.cache_hit
        ],
        "retries": sum(max(0, result.attempts - 1) for result in page_results),
        "usage": usage,
    }


def _response_usage(response: Any) -> dict[str, int]:
    usage = getattr(response, "usage", None)
    input_details = getattr(usage, "input_tokens_details", None)
    output_details = getattr(usage, "output_tokens_details", None)
    return {
        "input_tokens": int(getattr(usage, "input_tokens", 0) or 0),
        "cached_input_tokens": int(getattr(input_details, "cached_tokens", 0) or 0),
        "output_tokens": int(getattr(usage, "output_tokens", 0) or 0),
        "reasoning_tokens": int(getattr(output_details, "reasoning_tokens", 0) or 0),
    }


def _document_deadline_seconds() -> float:
    raw = os.getenv("HB_DOCUMENT_DEADLINE_SECONDS")
    if raw:
        try:
            value = float(raw)
            if value > 0:
                return value
        except ValueError:
            pass
    return DEFAULT_DOCUMENT_DEADLINE_SECONDS


def _mb(value: int) -> int:
    return value // (1024 * 1024)


def _metadata_header(metadata: dict[str, Any]) -> str:
    compact = dict(metadata)
    render = compact.get("render")
    if isinstance(render, dict):
        compact["render"] = {
            "dropped_count": render.get("dropped_count", 0),
            "error_count": render.get("error_count", 0),
        }
    return json.dumps(compact, ensure_ascii=True, separators=(",", ":"))


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
        return sanitize_annotations(json.loads(raw), enforce_contract=False)
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
