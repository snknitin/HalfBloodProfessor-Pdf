"""Validation shared by model ingestion and the deterministic renderer.

The model-facing JSON schema is the first boundary.  This module is the second:
cached values and direct renderer calls must be safe even when they did not come
from Structured Outputs.
"""

from __future__ import annotations

from typing import Any

MAX_QUOTE_CHARS = 240
MAX_NOTE_CHARS = 180
MAX_CORRECTION_CHARS = 80
MAX_DIAGRAM_TITLE_CHARS = 80
MAX_DIAGRAM_LABEL_CHARS = 60
MAX_ANNOTATIONS_PER_PAGE = 6

QUOTE_KINDS = {
    "underline",
    "strike",
    "circle",
    "highlight",
    "scribble",
    "doodle",
    "margin",
}

_CONTRACT_KEYS = {
    "underline": {"type", "quote", "note", "double"},
    "strike": {"type", "quote", "correction", "note"},
    "circle": {"type", "quote", "note"},
    "highlight": {"type", "quote"},
    "scribble": {"type", "quote", "note"},
    "doodle": {"type", "quote", "symbol"},
    "margin": {"type", "quote", "note"},
    "diagram": {"type", "title", "labels"},
}


def sanitize_annotations(
    payload: Any, *, enforce_contract: bool = True
) -> list[dict[str, Any]]:
    """Return only renderer-safe annotations from a model/cache payload."""
    if (
        not isinstance(payload, dict)
        or set(payload) != {"annotations"}
        or not isinstance(payload.get("annotations"), list)
    ):
        raise ValueError("Invalid annotation payload")

    candidates = payload["annotations"]
    if len(candidates) > MAX_ANNOTATIONS_PER_PAGE:
        raise ValueError("Too many annotations")

    result: list[dict[str, Any]] = []
    for candidate in candidates:
        if enforce_contract and (
            not isinstance(candidate, dict)
            or candidate.get("type") not in _CONTRACT_KEYS
            or set(candidate) != _CONTRACT_KEYS[candidate["type"]]
        ):
            raise ValueError("Invalid annotation contract")
        clean = sanitize_annotation(candidate)
        if clean is None:
            # A non-empty invalid array is not an intentional empty result.  It
            # must take the parse-failure path and must never enter either cache.
            raise ValueError("Invalid annotation")
        result.append(clean)
    return result


def sanitize_annotation(
    candidate: Any, *, enforce_quote_words: bool = True
) -> dict[str, Any] | None:
    """Validate and length-bound one annotation without retaining extra fields.

    Model/cache ingestion enforces the 3-8 word prompt contract.  The renderer
    can also safely consume the shorter anchors in Track A's proven hand-authored
    fixture; character bounds and structural checks still apply there.
    """
    if not isinstance(candidate, dict):
        return None
    kind = candidate.get("type")

    if kind == "diagram":
        labels = candidate.get("labels")
        if not isinstance(labels, list) or not 2 <= len(labels) <= 5:
            return None
        clean_labels = []
        for label in labels:
            value = _bounded_string(label, MAX_DIAGRAM_LABEL_CHARS)
            if not value:
                return None
            clean_labels.append(value)
        clean: dict[str, Any] = {"type": "diagram", "labels": clean_labels}
        title = _bounded_string(candidate.get("title"), MAX_DIAGRAM_TITLE_CHARS)
        if title:
            clean["title"] = title
        return clean

    if kind not in QUOTE_KINDS:
        return None
    quote = _bounded_string(candidate.get("quote"), MAX_QUOTE_CHARS)
    if not quote or (enforce_quote_words and not 3 <= len(quote.split()) <= 8):
        return None

    clean = {"type": kind, "quote": quote}
    note = _bounded_words(candidate.get("note"), 14, MAX_NOTE_CHARS)
    correction = _bounded_words(candidate.get("correction"), 5, MAX_CORRECTION_CHARS)

    if kind == "underline":
        clean["double"] = bool(candidate.get("double", False))
        if note:
            clean["note"] = note
    elif kind == "strike":
        if not correction:
            return None
        clean["correction"] = correction
        if note:
            clean["note"] = note
    elif kind in {"circle", "scribble", "margin"}:
        if not note:
            return None
        clean["note"] = note
    elif kind == "doodle":
        symbol = candidate.get("symbol")
        if symbol not in {"star", "asterisk", "exclaim"}:
            return None
        clean["symbol"] = symbol
    return clean


def _bounded_string(value: Any, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value:
        return None
    return value[:limit].rstrip()


def _bounded_words(value: Any, words: int, chars: int) -> str | None:
    text = _bounded_string(value, chars)
    if not text:
        return None
    return " ".join(text.split()[:words])[:chars].rstrip()
