"""In-memory adapter for Track A's deterministic annotation renderer."""

from __future__ import annotations

import hashlib
import logging
import math
import random
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

import fitz

from app import scribe
from app.pipeline import Margins, find_quote
from engine.validation import sanitize_annotation

logger = logging.getLogger(__name__)


@dataclass
class RenderReport:
    """Content-free diagnostics safe to expose in request metadata."""

    dropped: list[dict[str, Any]] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)
    annotations_received: int = 0
    quote_annotations: int = 0
    quotes_matched: int = 0
    blank_page_doodles: int = 0

    def metadata(self) -> dict[str, Any]:
        quote_match_percent = (
            round(self.quotes_matched * 100 / self.quote_annotations, 2)
            if self.quote_annotations
            else 100.0
        )
        return {
            "annotations_received": self.annotations_received,
            "quote_annotations": self.quote_annotations,
            "quotes_matched": self.quotes_matched,
            "quote_match_percent": quote_match_percent,
            "dropped_count": len(self.dropped),
            "dropped": self.dropped,
            "drop_reasons": dict(Counter(item["reason"] for item in self.dropped)),
            "error_count": len(self.errors),
            "errors": self.errors,
            "blank_page_doodles": self.blank_page_doodles,
        }


def annotate_bytes(
    pdf_bytes: bytes, annotations: list[dict[str, Any]]
) -> tuple[bytes, RenderReport]:
    """Render safely without writing the uploaded PDF or result to disk.

    Cached/model annotations are validated again here.  Every annotation uses a
    fresh Shape and is exception-isolated; page setup is isolated as well.  A
    malformed mark can therefore be dropped, but cannot fail the document.
    """
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    rng = random.Random(hashlib.sha256(pdf_bytes).hexdigest())
    report = RenderReport()

    try:
        by_page: dict[int, list[dict[str, Any]]] = {}
        for candidate in annotations:
            page = candidate.get("page") if isinstance(candidate, dict) else None
            clean = sanitize_annotation(candidate, enforce_quote_words=False)
            if (
                clean is None
                or not isinstance(page, int)
                or isinstance(page, bool)
                or not 1 <= page <= doc.page_count
            ):
                _render_error(report, page, _kind(candidate), "validation_error")
                continue
            clean["page"] = page
            report.annotations_received += 1
            if clean["type"] != "diagram":
                report.quote_annotations += 1
            by_page.setdefault(page - 1, []).append(clean)

        for page_number, page_annotations in sorted(by_page.items()):
            try:
                _render_page(doc[page_number], page_number + 1, page_annotations, rng, report)
            except Exception as exc:  # page-level safety net
                category = _error_category(exc)
                _render_error(report, page_number + 1, "page", category)

        _decorate_blank_interior_pages(doc, rng, report)

        rendered = doc.tobytes(garbage=3, deflate=True, no_new_id=True)
        return rendered, report
    finally:
        doc.close()


def _render_page(page, page_number, annotations, rng, report):
    bounds = fitz.Rect(page.rect)
    margins = Margins(page)
    _clamp_margins(margins, bounds)

    resolved = []
    for annotation in annotations:
        kind = annotation["type"]
        try:
            if kind == "diagram":
                # Reserve scarce margin/bottom space before notes consume it.
                resolved.append((float("-inf"), annotation, None))
                continue
            rects = [
                rect
                for found in find_quote(page, annotation["quote"])
                if (rect := _clamp_rect(found, bounds, _mark_padding(kind))) is not None
            ]
            if not rects:
                _drop(report, page_number, kind, "unmatched_quote")
                continue
            if kind == "bracket":
                start = rects[0]
                end_quote = annotation.get("end_quote")
                if end_quote:
                    endings = [
                        rect
                        for found in find_quote(page, end_quote)
                        if (rect := _clamp_rect(found, bounds, _mark_padding(kind)))
                        is not None
                        and rect.y1 >= start.y0
                    ]
                    if not endings:
                        _drop(report, page_number, kind, "unmatched_end_quote")
                        continue
                    rects = [start, endings[-1]]
                else:
                    rects = [start]
            report.quotes_matched += 1
            resolved.append((rects[0].y0, annotation, rects))
        except Exception as exc:
            _render_error(report, page_number, kind, _error_category(exc))

    for _, annotation, rects in sorted(resolved, key=lambda item: item[0]):
        try:
            _render_one(page, bounds, margins, annotation, rects, rng, report)
        except Exception as exc:  # per-annotation isolation
            _render_error(
                report, page_number, annotation.get("type", "unknown"), _error_category(exc)
            )


def _render_one(page, bounds, margins, annotation, rects, rng, report):
    page_number = page.number + 1
    kind = annotation["type"]
    color = _annotation_color(annotation, rng)
    shape = page.new_shape()  # never share partially-built drawing commands

    if kind == "diagram":
        diagram_layout, diagram_title = _diagram_layout(annotation.get("title"))
        area = _clamp_rect(margins.bottom, bounds, 10)
        diagram_side = "bottom"
        if area is None or area.height < 55:
            side, side_box = margins.side_box()
            diagram_side = side
            box = _clamp_rect(side_box, bounds, 10)
            needed = scribe.diagram_height(
                annotation["labels"], diagram_title, diagram_layout, width=box.width - 4
            )
            if box is None:
                _drop(report, page_number, kind, "no_space")
                return
            y0 = max(margins.cursor[side], box.y1 - needed)
            area = _clamp_rect(fitz.Rect(box.x0 + 2, y0, box.x1 - 2, box.y1), bounds, 10)
            if box.width < 48 or area is None or area.height < needed:
                _drop(report, page_number, kind, "no_space")
                return
            margins.commit(side, area.y1)
        if not _diagram_fits(area, annotation["labels"], diagram_title, diagram_layout):
            _drop(report, page_number, kind, "unsafe_geometry")
            return
        diagram_renderer = {
            "tree": scribe.tree_diagram,
            "math": scribe.equation_diagram,
        }.get(diagram_layout, scribe.chain_diagram)
        diagram_renderer(
            page,
            shape,
            area,
            annotation["labels"],
            rng,
            diagram_title,
            color=color,
            text_color=scribe.INK,
        )
        if diagram_side == "bottom":
            margins.commit("bottom", area.y1)
        shape.commit()
        return

    first = rects[0]
    if kind == "strike":
        for rect in rects:
            scribe.strike(shape, rect, rng, color=color)
        correction = scribe.correction_text(
            page, first, annotation["correction"], rng, page_rect=bounds, color=scribe.INK
        )
        if correction is None:
            _drop(report, page_number, "correction", "no_space")
    elif kind == "underline":
        for rect in rects:
            scribe.underline(shape, rect, rng, double=annotation.get("double", False), color=color)
    elif kind == "circle":
        scribe.circle(shape, first, rng, color=color)
    elif kind == "highlight":
        for rect in rects:
            scribe.highlight(shape, rect, rng, color=color)
    elif kind == "scribble":
        for rect in rects:
            scribe.strike(shape, rect, rng, color=color)
    elif kind == "doodle":
        center = _clamp_point(
            (margins.gutter_x(first), first.y0 + first.height / 2), bounds, 8
        )
        scribe.doodle(shape, center, rng, annotation["symbol"], color=color)
    elif kind == "margin":
        scribe.underline(shape, first, rng, color=color)
    elif kind == "bracket":
        span = fitz.Rect(first)
        for rect in rects[1:]:
            span.include_rect(rect)
        bracket_side = "left" if margins.left.width >= margins.right.width else "right"
        scribe.bracket(shape, span, rng, side=bracket_side, color=color)
    elif kind == "list":
        center = _clamp_point(
            (margins.gutter_x(first), first.y0 + first.height / 2), bounds, 8
        )
        scribe.list_marker(shape, center, rng, color=color)
    elif kind == "checkmark":
        center = _clamp_point(
            (margins.gutter_x(first), first.y0 + first.height / 2), bounds, 8
        )
        scribe.checkmark(shape, center, rng, color=color)
    elif kind == "callout":
        center = _clamp_point(
            (margins.gutter_x(first), first.y0 + first.height / 2), bounds, 8
        )
        scribe.callout_icon(shape, center, rng, annotation["icon"], color=color)

    note = annotation.get("note")
    if kind == "list":
        parts = list(annotation["items"])
        if annotation.get("title"):
            parts.insert(0, annotation["title"])
        note = " | ".join(parts)
    elif kind == "checkmark":
        note = annotation.get("counter")
    if note:
        box, side = margins.place(first.y0, note, rng=rng)
        box = _clamp_rect(box, bounds, 8) if box is not None else None
        if box is None or box.width < 12 or box.height < 8:
            _drop(report, page_number, "note", "no_space")
        else:
            used = scribe.note_text(page, box, note, rng, color=scribe.INK)
            if used is not None:
                used = _clamp_rect(used, bounds, 3)
            if used is None:
                _drop(report, page_number, "note", "unsafe_geometry")
            else:
                margins.commit(side, used.y1)
                if kind in {"circle", "margin", "bracket", "list", "callout"} or len(note.split()) >= 14:
                    if side == "left":
                        src = (used.x1 - 2, used.y0 + 6)
                        dst = (first.x0 - 7, first.y0 + first.height / 2)
                    elif side == "right":
                        src = (used.x0 + 2, used.y0 + 6)
                        dst = (first.x1 + 7, first.y0 + first.height / 2)
                    elif side == "bottom":
                        src = (used.x0 + used.width / 2, used.y0 + 1)
                        dst = (first.x0 + first.width / 2, first.y1 + 5)
                    else:  # top
                        src = (used.x0 + used.width / 2, used.y1 - 1)
                        dst = (first.x0 + first.width / 2, first.y0 - 5)
                    src = _clamp_point(src, bounds, 3)
                    dst = _clamp_point(dst, bounds, 3)
                    if abs(dst[0] - src[0]) < 300 and abs(dst[1] - src[1]) < 220:
                        scribe.arrow(shape, src, dst, rng, color=color)
    shape.commit()


def _annotation_color(annotation: dict[str, Any], rng):
    kind = annotation["type"]
    if kind == "strike":
        return scribe.INK_RED
    if kind == "highlight":
        return {
            "key": scribe.HIGHLIGHT,
            "theory": scribe.HIGHLIGHT_ORANGE,
            "example": scribe.HIGHLIGHT_ORANGE,
            "definition": scribe.HIGHLIGHT_BLUE,
            "evidence": scribe.HIGHLIGHT_GREEN,
            "caution": scribe.HIGHLIGHT_RED,
        }.get(annotation.get("meaning", "key"), scribe.HIGHLIGHT)
    if kind == "diagram":
        return scribe.INK_BLUE
    if kind == "checkmark":
        return scribe.INK_GREEN
    if kind in {"circle", "doodle", "bracket", "list", "callout"}:
        return rng.choice([scribe.INK_BLUE, scribe.INK_GREEN, scribe.INK_PURPLE])
    if kind in {"underline", "margin"}:
        return rng.choice([scribe.INK, scribe.INK_BLUE, scribe.INK_PURPLE])
    return scribe.INK


def _decorate_blank_interior_pages(doc, rng, report: RenderReport) -> None:
    for index in range(1, max(1, doc.page_count - 1)):
        page = doc[index]
        if page.get_text("text").strip():
            continue
        if page.get_images(full=True) or page.get_drawings():
            continue
        shape = page.new_shape()
        scribe.blank_page_doodle(page, shape, fitz.Rect(page.rect), rng)
        shape.commit()
        report.blank_page_doodles += 1


def _clamp_margins(margins: Margins, bounds: fitz.Rect) -> None:
    for name in ("left", "right", "top", "bottom"):
        rect = _clamp_rect(getattr(margins, name), bounds, 8)
        setattr(margins, name, rect or fitz.Rect(bounds.x0, bounds.y0, bounds.x0, bounds.y0))
    margins.cursor["left"] = margins.left.y0
    margins.cursor["right"] = margins.right.y0
    margins.cursor["top"] = margins.top.y0
    margins.cursor["bottom"] = margins.bottom.y0


def _clamp_rect(rect, bounds: fitz.Rect, padding: float = 0) -> fitz.Rect | None:
    if rect is None:
        return None
    candidate = fitz.Rect(rect)
    values = (candidate.x0, candidate.y0, candidate.x1, candidate.y1)
    if not all(math.isfinite(value) for value in values):
        return None
    inner = fitz.Rect(
        bounds.x0 + padding,
        bounds.y0 + padding,
        bounds.x1 - padding,
        bounds.y1 - padding,
    )
    if inner.width <= 0 or inner.height <= 0:
        return None
    clamped = fitz.Rect(
        max(min(candidate.x0, candidate.x1), inner.x0),
        max(min(candidate.y0, candidate.y1), inner.y0),
        min(max(candidate.x0, candidate.x1), inner.x1),
        min(max(candidate.y0, candidate.y1), inner.y1),
    )
    if clamped.width < 0.5 or clamped.height < 0.5:
        return None
    return clamped


def _clamp_point(point, bounds: fitz.Rect, padding: float) -> tuple[float, float]:
    return (
        min(max(float(point[0]), bounds.x0 + padding), bounds.x1 - padding),
        min(max(float(point[1]), bounds.y0 + padding), bounds.y1 - padding),
    )


def _mark_padding(kind: str) -> float:
    return {
        "circle": 24,
        "bracket": 10,
        "doodle": 8,
        "list": 8,
        "checkmark": 8,
        "callout": 8,
        "underline": 4,
        "highlight": 3,
    }.get(kind, 3)


def _diagram_layout(title: str | None) -> tuple[str, str | None]:
    if title:
        for prefix, layout in (("TREE:", "tree"), ("MATH:", "math")):
            if title.upper().startswith(prefix):
                clean_title = title[len(prefix):].strip()
                return layout, clean_title or None
    return "chain", title


def _diagram_fits(
    area: fitz.Rect,
    labels: list[str],
    title: str | None = None,
    layout: str = "chain",
) -> bool:
    if area.width < 48 or area.height < 30:
        return False
    if area.width >= area.height:
        if layout in {"tree", "math"}:
            return area.width >= 150 and area.height >= 48
        widths = [scribe._note_font.text_length(label, 6.5) + 14 for label in labels]
        return sum(widths) + 24 * (len(labels) - 1) <= area.width
    return scribe.diagram_height(labels, title, layout, width=area.width) <= area.height


def _drop(report: RenderReport, page: int, kind: str, reason: str) -> None:
    report.dropped.append({"page": page, "type": kind, "reason": reason})


def _render_error(report: RenderReport, page, kind: str, category: str) -> None:
    safe_page = page if isinstance(page, int) and not isinstance(page, bool) else None
    safe_kind = kind if kind in {
        "underline", "strike", "circle", "highlight", "scribble", "doodle",
        "margin", "diagram", "correction", "note", "page",
    } else "unknown"
    issue = {"page": safe_page, "type": safe_kind, "category": category}
    report.errors.append(issue)
    logger.warning(
        "renderer_annotation_failed page=%s type=%s category=%s",
        safe_page,
        safe_kind,
        category,
    )


def _kind(candidate: Any) -> str:
    if isinstance(candidate, dict) and isinstance(candidate.get("type"), str):
        return candidate["type"]
    return "unknown"


def _error_category(exc: Exception) -> str:
    if isinstance(exc, (TypeError, ValueError, KeyError, IndexError)):
        return "validation_error"
    if isinstance(exc, (MemoryError, OverflowError)):
        return "resource_error"
    return "renderer_error"
