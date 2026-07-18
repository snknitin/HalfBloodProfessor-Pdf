"""Ink primitives: everything that draws on the page. Pure deterministic geometry + seeded RNG."""
import math
import os

import fitz

FONTS = os.path.join(os.path.dirname(__file__), "fonts")
NOTE_FONT = os.path.join(FONTS, "Caveat.ttf")
SCRAWL_FONT = os.path.join(FONTS, "HomemadeApple-Regular.ttf")

INK = (0.14, 0.12, 0.10)
HIGHLIGHT = (1.0, 0.83, 0.25)

_note_font = fitz.Font(fontfile=NOTE_FONT)
_scrawl_font = fitz.Font(fontfile=SCRAWL_FONT)


def _wavy(p1, p2, rng, amp=0.7, step=9):
    """Points along p1->p2 with sinusoidal + random jitter perpendicular to the line."""
    p1, p2 = fitz.Point(p1), fitz.Point(p2)
    d = p2 - p1
    length = abs(d)
    if length < 1:
        return [p1, p2]
    n = max(2, int(length / step))
    px, py = -d.y / length, d.x / length  # unit perpendicular
    phase = rng.uniform(0, math.tau)
    pts = []
    for i in range(n + 1):
        t = i / n
        base = p1 + d * t
        ease = min(1.0, 3 * t * (1 - t) + 0.2)  # calmer at the ends
        off = (math.sin(t * length / 16 + phase) * amp * 0.6 + rng.uniform(-amp, amp) * 0.5) * ease
        pts.append(fitz.Point(base.x + px * off, base.y + py * off))
    return pts


def _stroke(shape, pts, rng, width=1.1, color=INK, close=False):
    shape.draw_polyline(pts)
    shape.finish(color=color, width=width * rng.uniform(0.9, 1.15),
                 stroke_opacity=rng.uniform(0.82, 0.95), closePath=close)


def strike(shape, rect, rng):
    y = rect.y0 + rect.height * rng.uniform(0.5, 0.6)
    tilt = rng.uniform(-1.2, 1.2)
    _stroke(shape, _wavy((rect.x0 - 2, y - tilt), (rect.x1 + 2, y + tilt), rng, amp=0.9), rng)


def underline(shape, rect, rng, double=False):
    y = rect.y1 + 1.2
    _stroke(shape, _wavy((rect.x0 - 1, y), (rect.x1 + 1, y), rng, amp=0.8), rng)
    if double:
        _stroke(shape, _wavy((rect.x0 + 1, y + 2.2), (rect.x1 - 1, y + 2.2), rng, amp=0.8), rng)


def circle(shape, rect, rng):
    """Two overlapping imperfect ellipse passes = hand-drawn loop."""
    cx, cy = rect.x0 + rect.width / 2, rect.y0 + rect.height / 2
    rx, ry = rect.width / 2 + 5, rect.height / 2 + 4
    for _ in range(2):
        start = rng.uniform(0, math.tau)
        pts = []
        n = 26
        wob_r = rng.uniform(0.9, 1.08)
        for i in range(n + 1):
            a = start + math.tau * (i / n) * rng.uniform(0.99, 1.03)
            w = wob_r + math.sin(a * 2 + start) * 0.06 + rng.uniform(-0.03, 0.03)
            pts.append(fitz.Point(cx + math.cos(a) * rx * w, cy + math.sin(a) * ry * w))
        _stroke(shape, pts, rng, width=1.0)


def arrow(shape, src, dst, rng):
    src, dst = fitz.Point(src), fitz.Point(dst)
    mid = (src + dst) / 2
    d = dst - src
    L = max(abs(d), 1)
    bow = rng.choice([-1, 1]) * rng.uniform(0.14, 0.24) * L
    ctrl = fitz.Point(mid.x - d.y / L * bow, mid.y + d.x / L * bow)
    # approximate quadratic bezier with a fine polyline so we can keep one stroke style
    pts = []
    for i in range(17):
        t = i / 16
        p = src * (1 - t) ** 2 + ctrl * 2 * t * (1 - t) + dst * t ** 2
        pts.append(p)
    _stroke(shape, pts, rng, width=1.0)
    # head: two barbs off the final direction
    fd = pts[-1] - pts[-3]
    fl = max(abs(fd), 0.1)
    ux, uy = fd.x / fl, fd.y / fl
    for sign in (1, -1):
        bx = -ux * 6 + sign * -uy * 3.2
        by = -uy * 6 + sign * ux * 3.2
        _stroke(shape, [dst, fitz.Point(dst.x + bx, dst.y + by)], rng, width=1.0)


def highlight(shape, rect, rng):
    r = rect + (-1.5, -1, 1.5, 1)
    j = lambda: rng.uniform(-1.2, 1.2)
    quad = [fitz.Point(r.x0 + j(), r.y0 + j()), fitz.Point(r.x1 + j(), r.y0 + j()),
            fitz.Point(r.x1 + j(), r.y1 + j()), fitz.Point(r.x0 + j(), r.y1 + j())]
    shape.draw_polyline(quad)
    shape.finish(color=None, fill=HIGHLIGHT, fill_opacity=0.32, closePath=True)


def scribble(shape, rect, rng):
    """Loose zigzag over a passage — dismissive but still legible underneath."""
    for slant in (1, -1):
        pts, x = [], rect.x0
        top, bot = rect.y0 + 1, rect.y1 - 1
        up = slant > 0
        while x < rect.x1:
            pts.append(fitz.Point(x + rng.uniform(-1, 1), (top if up else bot) + rng.uniform(-1, 1)))
            up = not up
            x += rng.uniform(5, 9)
        _stroke(shape, pts, rng, width=0.9)


def doodle(shape, center, rng, symbol="star", size=5.0):
    cx, cy = center
    if symbol == "star":
        pts = []
        rot = rng.uniform(0, math.tau)
        for i in range(11):
            a = rot + math.tau * i / 10
            r = size if i % 2 == 0 else size * 0.45
            pts.append(fitz.Point(cx + math.cos(a) * r, cy + math.sin(a) * r))
        _stroke(shape, pts, rng, width=0.9, close=True)
    elif symbol == "asterisk":
        for k in range(3):
            a = math.pi * k / 3 + rng.uniform(-0.1, 0.1)
            dx, dy = math.cos(a) * size, math.sin(a) * size
            _stroke(shape, _wavy((cx - dx, cy - dy), (cx + dx, cy + dy), rng, amp=0.4, step=4), rng, width=0.9)
    elif symbol == "exclaim":
        _stroke(shape, _wavy((cx, cy - size), (cx, cy + size * 0.5), rng, amp=0.4, step=3), rng, width=1.2)
        shape.draw_circle(fitz.Point(cx, cy + size + 1.5), 0.9)
        shape.finish(color=INK, fill=INK, stroke_opacity=0.9, fill_opacity=0.9)


def _wrap_lines(font, text, fontsize, width):
    lines, cur = [], ""
    for w in text.split():
        trial = (cur + " " + w).strip()
        if font.text_length(trial, fontsize) > width and cur:
            lines.append(cur)
            cur = w
        else:
            cur = trial
    if cur:
        lines.append(cur)
    return lines


def note_height(text, width, fontsize=10.5):
    """Exact height a note will need at this width — used by the placement engine."""
    return len(_wrap_lines(_note_font, text, fontsize, width)) * fontsize * 1.12 + 6


def note_text(page, box, text, rng, fontsize=10.5, fontfile=NOTE_FONT, fontname="Caveat"):
    """Handwritten note wrapped into box, slightly rotated. Returns rect actually used, or None."""
    font = _note_font if fontfile == NOTE_FONT else _scrawl_font
    fs = fontsize
    while fs >= 7:
        lines = _wrap_lines(font, text, fs, box.width)
        h = len(lines) * fs * 1.12 + 4
        if h <= box.height:
            break
        fs -= 0.75
    used = fitz.Rect(box.x0, box.y0, box.x1, min(box.y0 + h, box.y1))
    deg = rng.uniform(-2.5, 2.5)
    m = fitz.Matrix(1, 1)
    m.prerotate(deg)
    pivot = fitz.Point(box.x0, box.y0)
    y = box.y0 + fs
    for ln in lines:
        page.insert_text(fitz.Point(box.x0 + rng.uniform(-0.8, 0.8), y), ln,
                         fontname=fontname, fontfile=fontfile, fontsize=fs,
                         color=INK, morph=(pivot, m))
        y += fs * 1.12
        if y > box.y1:
            break
    return used


def correction_text(page, anchor_rect, text, rng):
    """Scrawled correction just above (or below) a struck-out phrase. Overlapping print is authentic."""
    fs = max(7.5, min(11.0, anchor_rect.height * 0.85))
    w = _scrawl_font.text_length(text, fs) + 6
    x0 = max(20, anchor_rect.x0 - 4)
    y0 = anchor_rect.y0 - fs * 1.45
    if y0 < 36:
        y0 = anchor_rect.y1 + 2
    box = fitz.Rect(x0, y0, x0 + w, y0 + fs * 1.6)
    return note_text(page, box, text, rng, fontsize=fs, fontfile=SCRAWL_FONT, fontname="HomemadeApple")


def diagram_height(labels, title=None, fs=9.5):
    """Height a vertical chain diagram needs."""
    return len(labels) * (fs * 1.9 + 15) + (16 if title else 0)


def chain_diagram(page, shape, area, labels, rng, title=None):
    """Hand-drawn chain of bubbled labels joined by arrows.

    Horizontal row if the area is wide, vertical column (margin marginalia style) if tall.
    """
    if area.width >= area.height:
        fs, gap = 10.0, 24
        while fs >= 6.5:
            widths = [_note_font.text_length(t, fs) + 14 for t in labels]
            total = sum(widths) + gap * (len(labels) - 1)
            if total <= area.width:
                break
            fs -= 0.5
        x = area.x0 + max(0, (area.width - total) / 2)
        cy = area.y0 + area.height * 0.55
        prev_edge = None
        for t, w in zip(labels, widths):
            h = fs * 1.9
            r = fitz.Rect(x, cy - h / 2, x + w, cy + h / 2)
            circle(shape, r + (2, 2, -2, -2), rng)
            note_text(page, fitz.Rect(r.x0 + 6, r.y0 + h * 0.18, r.x1 + 10, r.y1 + 4), t, rng, fontsize=fs)
            if prev_edge is not None:
                arrow(shape, (prev_edge + 3, cy + rng.uniform(-1.5, 1.5)),
                      (r.x0 - 8, cy + rng.uniform(-1.5, 1.5)), rng)
            prev_edge = r.x1 + 4
            x = r.x1 + gap
        if title:
            note_text(page, fitz.Rect(area.x0 + 10, area.y0 - 2, area.x1, area.y0 + 14), title, rng, fontsize=9.5)
    else:
        fs = 9.5
        y = area.y0
        if title:
            note_text(page, fitz.Rect(area.x0, y, area.x1, y + 15), title, rng, fontsize=fs)
            y += 16
        prev_bottom = None
        cx = area.x0 + area.width / 2
        for t in labels:
            h = fs * 1.9
            w = min(area.width - 4, _note_font.text_length(t, fs) + 14)
            r = fitz.Rect(cx - w / 2, y, cx + w / 2, y + h)
            circle(shape, r + (2, 2, -2, -2), rng)
            note_text(page, fitz.Rect(r.x0 + 6, r.y0 + h * 0.18, r.x1 + 10, r.y1 + 4), t, rng, fontsize=fs)
            if prev_bottom is not None:
                arrow(shape, (cx + rng.uniform(-2, 2), prev_bottom + 2),
                      (cx + rng.uniform(-2, 2), r.y0 - 3), rng)
            prev_bottom = r.y1
            y = r.y1 + 15
