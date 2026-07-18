"""Smoke check: one of each mark on a sample page; fails loudly if the ink pipeline breaks.

Run: python tests/test_smoke.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import fitz

from app.pipeline import annotate

SAMPLE = os.path.join(ROOT, "samples", "Ch1 - Introductions.pdf")


def main():
    anns = [
        {"page": 2, "type": "underline", "quote": "human history", "note": "smoke note"},
        {"page": 2, "type": "strike", "quote": "transformative forces", "correction": "test"},
        {"page": 2, "type": "circle", "quote": "systems invisibly shape our world", "note": "circled"},
        {"page": 2, "type": "highlight", "quote": "medical images"},
        {"page": 2, "type": "doodle", "quote": "In hospitals", "symbol": "star"},
        {"page": 2, "type": "scribble", "quote": "manage traffic flows"},  # exercises ligature fallback
    ]
    out = os.path.join(ROOT, "outputs", "_smoke.pdf")
    dropped = annotate(SAMPLE, anns, out, keep_pages=[2])
    assert not dropped, f"annotations dropped: {dropped}"
    doc = fitz.open(out)
    assert doc.page_count == 1
    strokes = doc[0].get_drawings()
    assert len(strokes) >= 6, f"expected ink on page, found {len(strokes)} drawings"
    text = doc[0].get_text()
    assert "smoke note" in text, "margin note text missing"
    doc.close()
    os.remove(out)
    print(f"smoke ok: {len(strokes)} ink strokes, notes rendered, ligature quote matched")


if __name__ == "__main__":
    main()
