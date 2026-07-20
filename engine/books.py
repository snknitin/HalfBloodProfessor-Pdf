"""Whole-book chunk planning and short-lived encrypted result storage."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import fitz
from fastapi import HTTPException


BOOK_MAX_BYTES = 150 * 1024 * 1024
BOOK_MAX_PAGES = 1_000
CHUNK_MAX_PAGES = 50
RESULT_TTL_SECONDS = 24 * 60 * 60


@dataclass(frozen=True)
class BookChunk:
    index: int
    title: str
    start_page: int  # one-based, inclusive
    end_page: int  # one-based, inclusive
    source: str

    def metadata(self) -> dict[str, Any]:
        return asdict(self)


def inspect_book(pdf_bytes: bytes) -> tuple[int, list[BookChunk]]:
    """Validate a book and return chapter-aware chunks without retaining it."""
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception as exc:
        raise HTTPException(status_code=422, detail="The upload is not a valid PDF.") from exc
    try:
        if doc.needs_pass:
            raise HTTPException(status_code=422, detail="Password-protected PDFs are not supported.")
        pages = doc.page_count
        if pages == 0:
            raise HTTPException(status_code=422, detail="The PDF has no pages.")
        if pages > BOOK_MAX_PAGES:
            raise HTTPException(
                status_code=422,
                detail=(
                    "This book is over the 1,000-page Professor's Pass limit. "
                    "Please split it into two passes."
                ),
            )
        if not any(doc[index].get_text("text").strip() for index in range(pages)):
            raise HTTPException(
                status_code=422,
                detail="This looks like a scanned book. Run OCR first, then try again.",
            )
        toc = doc.get_toc(simple=True)
    finally:
        doc.close()
    return pages, _plan_chunks(pages, toc)


def _plan_chunks(page_count: int, toc: list[list[Any]]) -> list[BookChunk]:
    top_level = _usable_top_level_toc(page_count, toc)
    if not top_level:
        return _fixed_parts(page_count)

    sections: list[tuple[str, int, int]] = []
    if top_level[0][1] > 1:
        sections.append(("Front Matter", 1, top_level[0][1] - 1))
    for index, (title, start) in enumerate(top_level):
        end = top_level[index + 1][1] - 1 if index + 1 < len(top_level) else page_count
        if end >= start:
            sections.append((title, start, end))

    raw: list[tuple[str, int, int]] = []
    for title, start, end in sections:
        cursor = start
        part = 1
        while cursor <= end:
            chunk_end = min(end, cursor + CHUNK_MAX_PAGES - 1)
            label = title if cursor == start and chunk_end == end else f"{title} · Part {part}"
            raw.append((label, cursor, chunk_end))
            cursor = chunk_end + 1
            part += 1

    # Merge tiny adjacent chapters when the combined chunk still stays below 50 pages.
    merged: list[tuple[str, int, int]] = []
    for title, start, end in raw:
        if merged and end - start + 1 <= 10:
            previous_title, previous_start, previous_end = merged[-1]
            if end - previous_start + 1 <= CHUNK_MAX_PAGES:
                merged[-1] = (f"{previous_title} / {title}", previous_start, end)
                continue
        merged.append((title, start, end))
    return [
        BookChunk(index + 1, title, start, end, "toc")
        for index, (title, start, end) in enumerate(merged)
    ]


def _usable_top_level_toc(page_count: int, toc: list[list[Any]]) -> list[tuple[str, int]]:
    candidates: list[tuple[str, int]] = []
    for row in toc:
        if len(row) < 3 or row[0] != 1:
            continue
        title = " ".join(str(row[1]).split())[:120]
        try:
            page = int(row[2])
        except (TypeError, ValueError):
            continue
        if title and 1 <= page <= page_count:
            candidates.append((title, page))
    # Deduplicate page destinations while preserving the outline order.
    seen: set[int] = set()
    return [(title, page) for title, page in candidates if not (page in seen or seen.add(page))]


def _fixed_parts(page_count: int) -> list[BookChunk]:
    chunks = []
    total = (page_count + CHUNK_MAX_PAGES - 1) // CHUNK_MAX_PAGES
    for index, start in enumerate(range(1, page_count + 1, CHUNK_MAX_PAGES), 1):
        end = min(page_count, start + CHUNK_MAX_PAGES - 1)
        chunks.append(
            BookChunk(index, f"Part {index} of {total} (pages {start}-{end})", start, end, "pages")
        )
    return chunks


def extract_chunk(pdf_bytes: bytes, chunk: BookChunk) -> bytes:
    source = fitz.open(stream=pdf_bytes, filetype="pdf")
    output = fitz.open()
    try:
        output.insert_pdf(source, from_page=chunk.start_page - 1, to_page=chunk.end_page - 1)
        return output.tobytes(garbage=3, deflate=True, no_new_id=True)
    finally:
        output.close()
        source.close()


def stitch_chunks(chunks: list[bytes], toc: list[list[Any]] | None = None) -> bytes:
    output = fitz.open()
    try:
        for chunk_bytes in chunks:
            chunk = fitz.open(stream=chunk_bytes, filetype="pdf")
            try:
                output.insert_pdf(chunk)
            finally:
                chunk.close()
        if toc:
            try:
                output.set_toc(toc)
            except ValueError:
                pass
        return output.tobytes(garbage=3, deflate=True, no_new_id=True)
    finally:
        output.close()


def original_toc(pdf_bytes: bytes) -> list[list[Any]]:
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        return doc.get_toc(simple=True)
    finally:
        doc.close()


def save_encrypted_result(pdf_bytes: bytes, access_key: str) -> tuple[str, int]:
    secret = _storage_secret()
    result_id = secrets.token_urlsafe(18)
    expires_at = int(time.time()) + RESULT_TTL_SECONDS
    nonce = secrets.token_bytes(16)
    enc_key = hmac.new(secret, b"enc\0" + access_key.encode(), hashlib.sha256).digest()
    mac_key = hmac.new(secret, b"mac\0" + access_key.encode(), hashlib.sha256).digest()
    ciphertext = _xor_stream(pdf_bytes, enc_key, nonce)
    tag = hmac.new(mac_key, nonce + ciphertext, hashlib.sha256).digest()
    payload = b"HBP1" + expires_at.to_bytes(8, "big") + nonce + tag + ciphertext
    path = _result_path(result_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    _latest_path(access_key).write_text(
        json.dumps({"result_id": result_id, "expires_at": expires_at * 1000}),
        encoding="utf-8",
    )
    _cleanup_results()
    return result_id, expires_at * 1000


def load_encrypted_result(result_id: str, access_key: str) -> bytes:
    if not result_id or any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for character in result_id):
        raise HTTPException(status_code=404, detail="That annotated book is no longer available.")
    path = _result_path(result_id)
    try:
        payload = path.read_bytes()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="That annotated book is no longer available.") from exc
    if len(payload) < 60 or payload[:4] != b"HBP1":
        raise HTTPException(status_code=404, detail="That annotated book is no longer available.")
    expires_at = int.from_bytes(payload[4:12], "big")
    if expires_at <= int(time.time()):
        path.unlink(missing_ok=True)
        raise HTTPException(status_code=410, detail="This result expired after 24 hours and was deleted.")
    nonce, tag, ciphertext = payload[12:28], payload[28:60], payload[60:]
    secret = _storage_secret()
    enc_key = hmac.new(secret, b"enc\0" + access_key.encode(), hashlib.sha256).digest()
    mac_key = hmac.new(secret, b"mac\0" + access_key.encode(), hashlib.sha256).digest()
    expected = hmac.new(mac_key, nonce + ciphertext, hashlib.sha256).digest()
    if not hmac.compare_digest(tag, expected):
        raise HTTPException(status_code=403, detail="That access key does not unlock this result.")
    return _xor_stream(ciphertext, enc_key, nonce)


def latest_result(access_key: str) -> dict[str, Any]:
    try:
        value = json.loads(_latest_path(access_key).read_text(encoding="utf-8"))
        result_id = str(value["result_id"])
        expires_at = int(value["expires_at"])
    except (FileNotFoundError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=404, detail="No completed book is available for this pass.") from exc
    if expires_at <= int(time.time() * 1000) or not _result_path(result_id).exists():
        _latest_path(access_key).unlink(missing_ok=True)
        _result_path(result_id).unlink(missing_ok=True)
        raise HTTPException(status_code=410, detail="This result expired after 24 hours and was deleted.")
    return {"result_id": result_id, "expires_at": expires_at}


def _xor_stream(data: bytes, key: bytes, nonce: bytes) -> bytes:
    output = bytearray(len(data))
    for offset in range(0, len(data), 32):
        counter = (offset // 32).to_bytes(8, "big")
        block = hmac.new(key, nonce + counter, hashlib.sha256).digest()
        piece = data[offset : offset + 32]
        for index, value in enumerate(piece):
            output[offset + index] = value ^ block[index]
    return bytes(output)


def _storage_secret() -> bytes:
    value = os.getenv("HB_BOOK_STORAGE_SECRET") or os.getenv("HB_SHARED_SECRET")
    if not value:
        raise HTTPException(status_code=503, detail="Book result encryption is not configured.")
    return value.encode("utf-8")


def _result_path(result_id: str) -> Path:
    directory = Path(os.getenv("HB_BOOK_RESULT_DIR", "/tmp/hb-book-results"))
    return directory / f"{result_id}.hbp"


def _latest_path(access_key: str) -> Path:
    digest = hmac.new(_storage_secret(), b"latest\0" + access_key.encode(), hashlib.sha256).hexdigest()
    return _result_path("placeholder").parent / f"latest-{digest}.json"


def _cleanup_results() -> None:
    directory = _result_path("placeholder").parent
    if not directory.exists():
        return
    cutoff = time.time() - RESULT_TTL_SECONDS - 3600
    for path in directory.glob("*.hbp"):
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink(missing_ok=True)
        except OSError:
            continue
    for path in directory.glob("latest-*.json"):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            if int(value.get("expires_at", 0)) <= int(time.time() * 1000):
                path.unlink(missing_ok=True)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            path.unlink(missing_ok=True)
