"""In-memory adapter for Track A's deterministic annotation renderer."""

import hashlib
import random

import fitz

from app import scribe
from app.pipeline import Margins, find_quote


def annotate_bytes(pdf_bytes: bytes, annotations: list[dict]) -> tuple[bytes, list[tuple]]:
    """Render annotations without writing the uploaded PDF or result to disk."""
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    rng = random.Random(hashlib.sha256(pdf_bytes).hexdigest())
    dropped = []

    by_page = {}
    for annotation in annotations:
        by_page.setdefault(annotation["page"] - 1, []).append(annotation)

    for page_number, page_annotations in sorted(by_page.items()):
        if page_number < 0 or page_number >= doc.page_count:
            continue
        page = doc[page_number]
        margins = Margins(page)
        shape = page.new_shape()

        resolved = []
        for annotation in page_annotations:
            if annotation["type"] == "diagram":
                resolved.append((float("inf"), annotation, None))
                continue
            rects = find_quote(page, annotation["quote"])
            if not rects:
                dropped.append(
                    (page_number + 1, annotation["type"], annotation["quote"][:40])
                )
                continue
            resolved.append((rects[0].y0, annotation, rects))

        for _, annotation, rects in sorted(resolved, key=lambda item: item[0]):
            kind = annotation["type"]
            if kind == "diagram":
                area = margins.bottom
                if area.height < 55:
                    side, box = margins.side_box()
                    needed = scribe.diagram_height(
                        annotation["labels"], annotation.get("title")
                    )
                    y0 = max(margins.cursor[side], box.y1 - needed)
                    if box.width < 48 or y0 + needed > box.y1:
                        dropped.append((page_number + 1, kind, "no space"))
                        continue
                    area = fitz.Rect(box.x0 + 2, y0, box.x1 - 2, box.y1)
                    margins.commit(side, box.y1)
                scribe.chain_diagram(
                    page,
                    shape,
                    area,
                    annotation["labels"],
                    rng,
                    annotation.get("title"),
                )
                continue

            first = rects[0]
            if kind == "strike":
                for rect in rects:
                    scribe.strike(shape, rect, rng)
                if annotation.get("correction"):
                    scribe.correction_text(page, first, annotation["correction"], rng)
            elif kind == "underline":
                for rect in rects:
                    scribe.underline(
                        shape, rect, rng, double=annotation.get("double", False)
                    )
            elif kind == "circle":
                scribe.circle(shape, first, rng)
            elif kind == "highlight":
                for rect in rects:
                    scribe.highlight(shape, rect, rng)
            elif kind == "scribble":
                for rect in rects:
                    scribe.scribble(shape, rect, rng)
            elif kind == "doodle":
                scribe.doodle(
                    shape,
                    (margins.gutter_x(first), first.y0 + first.height / 2),
                    rng,
                    annotation.get("symbol", "star"),
                )
            elif kind == "margin":
                scribe.underline(shape, first, rng)

            note = annotation.get("note")
            if note:
                box, side = margins.place(first.y0, note)
                if box is None:
                    dropped.append((page_number + 1, "note", note[:40]))
                    continue
                used = scribe.note_text(page, box, note, rng)
                margins.commit(side, used.y1)
                if kind == "circle":
                    if side == "left":
                        src = (used.x1 - 2, used.y0 + 6)
                        dst = (first.x0 - 7, first.y0 + first.height / 2)
                    else:
                        src = (used.x0 + 2, used.y0 + 6)
                        dst = (first.x1 + 7, first.y0 + first.height / 2)
                    if abs(dst[0] - src[0]) < 300:
                        scribe.arrow(shape, src, dst, rng)
        shape.commit()

    rendered = doc.tobytes(garbage=3, deflate=True, no_new_id=True)
    doc.close()
    return rendered, dropped
