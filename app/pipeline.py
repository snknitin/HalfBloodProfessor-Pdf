"""Extract -> (LLM or JSON file) -> match quotes to coordinates -> scribe ink -> save.

CLI:  python -m app.pipeline input.pdf annotations.json out.pdf [--pages 2-6] [--previews dir]
"""
import argparse
import hashlib
import json
import random

import fitz

from . import scribe

# this book's PDF maps ligatures to CJK codepoints; substitute before searching
LIGS = [("ffi", "昀케"), ("ff", "昀昀"), ("fl", "昀氀"), ("fi", "昀椀")]


def find_quote(page, quote):
    for q in (quote, _lig(quote)):
        rects = page.search_for(q)
        if rects:
            return rects
    return []


def _lig(q):
    for a, b in LIGS:
        q = q.replace(a, b)
    return q


class Margins:
    """Free margin space per page + greedy top-down note placement."""

    def __init__(self, page):
        pr = page.rect
        blocks = [fitz.Rect(b[:4]) for b in page.get_text("blocks")
                  if b[4].strip() and b[1] > 50]  # ignore running header
        if not blocks:
            blocks = [fitz.Rect(pr.width * 0.2, 50, pr.width * 0.8, pr.height - 50)]
        self.minx = min(b.x0 for b in blocks)
        self.maxx = max(b.x1 for b in blocks)
        maxy = max(b.y1 for b in blocks)
        self.left = fitz.Rect(10, 52, self.minx - 8, pr.height - 30)
        self.right = fitz.Rect(self.maxx + 8, 52, pr.width - 10, pr.height - 30)
        self.bottom = fitz.Rect(self.minx, maxy + 12, self.maxx, pr.height - 24)
        self.cursor = {
            "left": self.left.y0,
            "right": self.right.y0,
            "bottom": self.bottom.y0,
        }

    def side_box(self):
        side = "left" if self.left.width >= self.right.width else "right"
        return side, (self.left if side == "left" else self.right)

    def place(self, y, text, rng=None):
        """Reserve a rect for `text` near anchor y. Caller must commit() the rect actually used."""
        if rng is not None:
            y += rng.uniform(-12, 16)
        candidates = []
        for side, box in (("left", self.left), ("right", self.right)):
            if box.width < 48:
                continue
            h = scribe.note_height(text, box.width - 4)
            y0 = max(y - 4, self.cursor[side])
            if y0 + h <= box.y1:
                tie_break = rng.uniform(0, 8) if rng is not None else 0
                candidates.append((abs(y0 - y) + tie_break, -box.width, side, box, y0, h))
        if candidates:
            _, _, side, box, y0, h = min(candidates)
            return fitz.Rect(box.x0 + 2, y0, box.x1 - 2, y0 + h + 4), side

        box = self.bottom
        if box.width >= 96 and box.height >= 18:
            h = scribe.note_height(text, box.width - 8)
            y0 = self.cursor["bottom"]
            if y0 + h <= box.y1:
                return fitz.Rect(box.x0 + 4, y0, box.x1 - 4, y0 + h + 4), "bottom"
        return None, "left"

    def commit(self, side, y1):
        self.cursor[side] = max(self.cursor[side], y1 + 9)

    def gutter_x(self, quote_rect):
        """x for a doodle: the strip between margin and text, nearest usable side."""
        if self.left.width >= 22 and self.left.width >= self.right.width:
            return self.minx - 11
        return self.maxx + 11


def annotate(pdf_path, annotations, out_path, keep_pages=None):
    doc = fitz.open(pdf_path)
    rng = random.Random(hashlib.sha256(open(pdf_path, "rb").read()).hexdigest())
    dropped = []

    by_page = {}
    for a in annotations:
        by_page.setdefault(a["page"] - 1, []).append(a)

    for pno, anns in sorted(by_page.items()):
        page = doc[pno]
        margins = Margins(page)
        shape = page.new_shape()

        # resolve quotes up front, then render top-to-bottom so notes land near their anchors
        resolved = []
        for a in anns:
            if a["type"] == "diagram":
                resolved.append((float("inf"), a, None))
                continue
            rects = find_quote(page, a["quote"])
            if not rects:
                dropped.append((pno + 1, a["type"], a["quote"][:40]))
                continue
            resolved.append((rects[0].y0, a, rects))

        for _, a, rects in sorted(resolved, key=lambda t: t[0]):
            kind = a["type"]
            if kind == "diagram":
                area = margins.bottom
                if area.height < 55:  # no room under the text: run it down the wider margin
                    side, box = margins.side_box()
                    need = scribe.diagram_height(a["labels"], a.get("title"))
                    y0 = max(margins.cursor[side], box.y1 - need)
                    if box.width < 48 or y0 + need > box.y1:
                        dropped.append((pno + 1, kind, "no space"))
                        continue
                    area = fitz.Rect(box.x0 + 2, y0, box.x1 - 2, box.y1)
                    margins.commit(side, box.y1)
                scribe.chain_diagram(page, shape, area, a["labels"], rng, a.get("title"))
                continue
            first = rects[0]

            if kind == "strike":
                for r in rects:
                    scribe.strike(shape, r, rng)
                if a.get("correction"):
                    scribe.correction_text(page, first, a["correction"], rng)
            elif kind == "underline":
                for r in rects:
                    scribe.underline(shape, r, rng, double=a.get("double", False))
            elif kind == "circle":
                scribe.circle(shape, first, rng)
            elif kind == "highlight":
                for r in rects:
                    scribe.highlight(shape, r, rng)
            elif kind == "scribble":
                for r in rects:
                    scribe.scribble(shape, r, rng)
            elif kind == "doodle":
                scribe.doodle(shape, (margins.gutter_x(first), first.y0 + first.height / 2),
                              rng, a.get("symbol", "star"))
            elif kind == "margin":
                scribe.underline(shape, first, rng)

            note = a.get("note")
            if note:
                box, side = margins.place(first.y0, note)
                if box is None:
                    dropped.append((pno + 1, "note", note[:40]))
                    continue
                used = scribe.note_text(page, box, note, rng)
                margins.commit(side, used.y1)
                if kind == "circle":  # arrow from note to the circled phrase
                    if side == "left":
                        src = (used.x1 - 2, used.y0 + 6)
                        dst = (first.x0 - 7, first.y0 + first.height / 2)
                    elif side == "right":
                        src = (used.x0 + 2, used.y0 + 6)
                        dst = (first.x1 + 7, first.y0 + first.height / 2)
                    else:
                        src = (used.x0 + used.width / 2, used.y0 + 1)
                        dst = (first.x0 + first.width / 2, first.y1 + 5)
                    if abs(dst[0] - src[0]) < 300:  # a page-crossing arrow reads as a strike
                        scribe.arrow(shape, src, dst, rng)
        shape.commit()

    if keep_pages:
        doc.select([p - 1 for p in keep_pages])
    doc.save(out_path, garbage=3, deflate=True)
    doc.close()
    return dropped


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("annotations")
    ap.add_argument("out")
    ap.add_argument("--pages", help="1-based range like 2-6: annotate and keep only these")
    ap.add_argument("--previews", help="directory to write per-page PNG previews")
    args = ap.parse_args()

    anns = json.load(open(args.annotations, encoding="utf-8"))
    keep = None
    if args.pages:
        a, b = args.pages.split("-")
        keep = list(range(int(a), int(b) + 1))
        anns = [x for x in anns if x["page"] in keep]

    dropped = annotate(args.pdf, anns, args.out, keep_pages=keep)
    print(f"wrote {args.out}; dropped {len(dropped)}: {dropped}")

    if args.previews:
        import os
        os.makedirs(args.previews, exist_ok=True)
        doc = fitz.open(args.out)
        for i, page in enumerate(doc):
            page.get_pixmap(dpi=110).save(os.path.join(args.previews, f"page{i + 1}.png"))
        print(f"previews in {args.previews}")


if __name__ == "__main__":
    main()
