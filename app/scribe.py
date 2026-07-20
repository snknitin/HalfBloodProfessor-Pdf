"""Ink primitives: everything that draws on the page. Pure deterministic geometry + seeded RNG."""
import math
import os

import fitz

FONTS = os.path.join(os.path.dirname(__file__), "fonts")
NOTE_FONT = os.path.join(FONTS, "Caveat.ttf")
SCRAWL_FONT = os.path.join(FONTS, "HomemadeApple-Regular.ttf")

INK = (0.14, 0.12, 0.10)
INK_BLUE = (0.08, 0.24, 0.48)
INK_RED = (0.62, 0.10, 0.12)
INK_GREEN = (0.08, 0.38, 0.28)
INK_PURPLE = (0.36, 0.16, 0.48)
HIGHLIGHT = (1.0, 0.83, 0.25)
HIGHLIGHT_ORANGE = (1.0, 0.55, 0.16)
HIGHLIGHT_BLUE = (0.42, 0.72, 0.95)
HIGHLIGHT_GREEN = (0.55, 0.82, 0.52)
HIGHLIGHT_ROSE = (0.96, 0.58, 0.63)
HIGHLIGHT_RED = (0.95, 0.34, 0.34)

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


def strike(shape, rect, rng, color=INK):
    y = rect.y0 + rect.height * rng.uniform(0.5, 0.6)
    tilt = rng.uniform(-0.6, 0.6)
    _stroke(
        shape,
        _wavy(
            (rect.x0 - 2, y - tilt),
            (rect.x1 + 2, y + tilt),
            rng,
            amp=0.28,
            step=15,
        ),
        rng,
        color=color,
    )


def underline(shape, rect, rng, double=False, color=INK):
    y = rect.y1 + 1.2
    _stroke(shape, _wavy((rect.x0 - 1, y), (rect.x1 + 1, y), rng, amp=0.8), rng, color=color)
    if double:
        _stroke(shape, _wavy((rect.x0 + 1, y + 2.2), (rect.x1 - 1, y + 2.2), rng, amp=0.8), rng, color=color)


def circle(shape, rect, rng, color=INK):
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
        _stroke(shape, pts, rng, width=1.0, color=color)


def arrow(shape, src, dst, rng, color=INK):
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
    _stroke(shape, pts, rng, width=1.0, color=color)
    # head: two barbs off the final direction
    fd = pts[-1] - pts[-3]
    fl = max(abs(fd), 0.1)
    ux, uy = fd.x / fl, fd.y / fl
    for sign in (1, -1):
        bx = -ux * 6 + sign * -uy * 3.2
        by = -uy * 6 + sign * ux * 3.2
        _stroke(shape, [dst, fitz.Point(dst.x + bx, dst.y + by)], rng, width=1.0, color=color)


def highlight(shape, rect, rng, color=HIGHLIGHT):
    r = rect + (-1.5, -1, 1.5, 1)
    j = lambda: rng.uniform(-1.2, 1.2)
    quad = [fitz.Point(r.x0 + j(), r.y0 + j()), fitz.Point(r.x1 + j(), r.y0 + j()),
            fitz.Point(r.x1 + j(), r.y1 + j()), fitz.Point(r.x0 + j(), r.y1 + j())]
    shape.draw_polyline(quad)
    shape.finish(color=None, fill=color, fill_opacity=0.30, closePath=True)


def scribble(shape, rect, rng, color=INK):
    """Backward-compatible alias rendered as one clean handwritten strike."""
    strike(shape, rect, rng, color=color)


def doodle(shape, center, rng, symbol="star", size=5.0, color=INK):
    cx, cy = center
    if symbol == "star":
        pts = []
        rot = rng.uniform(0, math.tau)
        for i in range(11):
            a = rot + math.tau * i / 10
            r = size if i % 2 == 0 else size * 0.45
            pts.append(fitz.Point(cx + math.cos(a) * r, cy + math.sin(a) * r))
        _stroke(shape, pts, rng, width=0.9, color=color, close=True)
    elif symbol == "asterisk":
        for k in range(3):
            a = math.pi * k / 3 + rng.uniform(-0.1, 0.1)
            dx, dy = math.cos(a) * size, math.sin(a) * size
            _stroke(shape, _wavy((cx - dx, cy - dy), (cx + dx, cy + dy), rng, amp=0.4, step=4), rng, width=0.9, color=color)
    elif symbol == "exclaim":
        _stroke(shape, _wavy((cx, cy - size), (cx, cy + size * 0.5), rng, amp=0.4, step=3), rng, width=1.2, color=color)
        shape.draw_circle(fitz.Point(cx, cy + size + 1.5), 0.9)
        shape.finish(color=color, fill=color, stroke_opacity=0.9, fill_opacity=0.9)


def bracket(shape, rect, rng, side="left", color=INK_BLUE):
    """A restrained hand-drawn bracket grouping a phrase or paragraph span."""
    pad = 3.5
    y0, y1 = rect.y0 - 1, rect.y1 + 1
    if side == "right":
        x = rect.x1 + pad
        points = [(x - 4, y0), (x, y0), (x, y1), (x - 4, y1)]
    else:
        x = rect.x0 - pad
        points = [(x + 4, y0), (x, y0), (x, y1), (x + 4, y1)]
    _stroke(shape, _wavy(points[0], points[1], rng, amp=0.2, step=3), rng, color=color)
    _stroke(shape, _wavy(points[1], points[2], rng, amp=0.32, step=12), rng, color=color)
    _stroke(shape, _wavy(points[2], points[3], rng, amp=0.2, step=3), rng, color=color)


def checkmark(shape, center, rng, size=6.0, color=INK_GREEN):
    """Small evidence-approved tick."""
    cx, cy = center
    points = [
        fitz.Point(cx - size, cy),
        fitz.Point(cx - size * 0.25, cy + size * 0.65),
        fitz.Point(cx + size, cy - size * 0.8),
    ]
    _stroke(shape, points, rng, width=1.5, color=color)


def list_marker(shape, center, rng, color=INK_BLUE):
    """Three tiny bullet strokes introducing a narrative-side list."""
    cx, cy = center
    for offset in (-4.5, 0, 4.5):
        y = cy + offset
        shape.draw_circle(fitz.Point(cx - 4, y), 0.75)
        shape.finish(color=color, fill=color, stroke_opacity=0.9, fill_opacity=0.9)
        _stroke(
            shape,
            _wavy((cx - 1, y), (cx + 6, y), rng, amp=0.16, step=3),
            rng,
            width=0.85,
            color=color,
        )


def callout_icon(shape, center, rng, icon, size=5.5, color=INK_BLUE):
    """Compact expert symbols for assumptions, hazards, practice, and definitions."""
    cx, cy = center
    if icon == "question":
        points = [
            fitz.Point(cx - size * 0.65, cy - size * 0.55),
            fitz.Point(cx, cy - size),
            fitz.Point(cx + size * 0.7, cy - size * 0.35),
            fitz.Point(cx + size * 0.15, cy + size * 0.15),
            fitz.Point(cx, cy + size * 0.45),
        ]
        _stroke(shape, points, rng, width=1.1, color=color)
        shape.draw_circle(fitz.Point(cx, cy + size), 0.8)
        shape.finish(color=color, fill=color, stroke_opacity=0.9, fill_opacity=0.9)
    elif icon == "warning":
        points = [
            fitz.Point(cx, cy - size),
            fitz.Point(cx + size, cy + size * 0.8),
            fitz.Point(cx - size, cy + size * 0.8),
            fitz.Point(cx, cy - size),
        ]
        _stroke(shape, points, rng, width=1.0, color=color)
        doodle(shape, (cx, cy + 0.5), rng, "exclaim", size=2.7, color=color)
    elif icon == "practice":
        _stroke(shape, [(cx - size, cy - size), (cx + size, cy + size)], rng, color=color)
        _stroke(shape, [(cx + size, cy - size), (cx - size, cy + size)], rng, color=color)
        shape.draw_circle(fitz.Point(cx - size, cy - size), 1.5)
        shape.finish(color=color, stroke_opacity=0.9)
    else:  # definition
        box = fitz.Rect(cx - size, cy - size, cx + size, cy + size)
        shape.draw_rect(box)
        shape.finish(color=color, width=0.9, stroke_opacity=0.9)
        _stroke(shape, [(cx - 2.8, cy - 1.8), (cx + 2.8, cy - 1.8)], rng, width=0.75, color=color)
        _stroke(shape, [(cx - 2.8, cy + 1.8), (cx + 1.4, cy + 1.8)], rng, width=0.75, color=color)


def _wrap_lines(font, text, fontsize, width):
    lines = []
    segments = [segment.strip() for segment in text.split("|") if segment.strip()]
    for segment in segments:
        cur = "-" if len(segments) > 1 else ""
        for word in segment.split():
            trial = (cur + " " + word).strip()
            if font.text_length(trial, fontsize) > width and cur not in {"", "-"}:
                lines.append(cur)
                cur = word
            else:
                cur = trial
        if cur and cur != "-":
            lines.append(cur)
    return lines


def note_height(text, width, fontsize=11.5):
    """Exact height a note will need at this width — used by the placement engine."""
    return len(_wrap_lines(_note_font, text, fontsize, width)) * fontsize * 1.12 + 6


def note_text(page, box, text, rng, fontsize=11.5, fontfile=NOTE_FONT, fontname="Caveat", color=INK):
    """Handwritten note wrapped into box, slightly rotated. Returns rect actually used, or None."""
    font = _note_font if fontfile == NOTE_FONT else _scrawl_font
    fs = fontsize
    min_fs = min(8.5, fs)
    while True:
        lines = _wrap_lines(font, text, fs, box.width)
        h = len(lines) * fs * 1.12 + 4
        if h <= box.height or fs <= min_fs:
            break
        fs = max(min_fs, fs - 0.75)
    used = fitz.Rect(box.x0, box.y0, box.x1, min(box.y0 + h, box.y1))
    deg = rng.uniform(-2.5, 2.5)
    m = fitz.Matrix(1, 1)
    m.prerotate(deg)
    pivot = fitz.Point(box.x0, box.y0)
    y = box.y0 + fs
    for ln in lines:
        page.insert_text(fitz.Point(box.x0 + rng.uniform(-0.8, 0.8), y), ln,
                         fontname=fontname, fontfile=fontfile, fontsize=fs,
                         color=color, morph=(pivot, m))
        y += fs * 1.12
        if y > box.y1:
            break
    return used


def correction_text(page, anchor_rect, text, rng, page_rect=None, color=INK):
    """Scrawl a correction near its strike.

    ``page_rect`` is optional so the original Track A call remains unchanged.  The
    service supplies it to constrain model-generated corrections to the page.
    """
    fs = max(7.5, min(11.0, anchor_rect.height * 0.85))
    w = _scrawl_font.text_length(text, fs) + 6
    x0 = max(20, anchor_rect.x0 - 4)
    y0 = anchor_rect.y0 - fs * 1.45
    if y0 < 36:
        y0 = anchor_rect.y1 + 2
    box = fitz.Rect(x0, y0, x0 + w, y0 + fs * 1.6)

    if page_rect is not None:
        bounds = fitz.Rect(page_rect)
        # Rotation can move the far edge by ~22 pt on a full-width page.  Keep
        # enough inset that a clamped box remains clamped after the hand tilt.
        inset = fitz.Rect(bounds.x0 + 24, bounds.y0 + 24, bounds.x1 - 24, bounds.y1 - 24)
        if inset.width < 36 or inset.height < fs * 1.6:
            return None
        x0 = min(max(anchor_rect.x0 - 4, inset.x0), inset.x1 - 36)
        width = min(max(36, w), inset.x1 - x0)
        lines = _wrap_lines(_scrawl_font, text, fs, width)
        height = max(fs * 1.6, len(lines) * fs * 1.12 + 4)
        above = anchor_rect.y0 - height - 2
        below = anchor_rect.y1 + 2
        if above >= inset.y0:
            y0 = above
        elif below + height <= inset.y1:
            y0 = below
        else:
            return None
        box = fitz.Rect(x0, y0, x0 + width, y0 + height)
    return note_text(page, box, text, rng, fontsize=fs, fontfile=SCRAWL_FONT, fontname="HomemadeApple", color=color)


def diagram_height(labels, title=None, fs=9.5):
    """Height a vertical chain diagram needs."""
    return len(labels) * (fs * 1.9 + 15) + (16 if title else 0)


def chain_diagram(
    page, shape, area, labels, rng, title=None, color=INK_BLUE, text_color=INK
):
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
            circle(shape, r + (2, 2, -2, -2), rng, color=color)
            note_text(page, fitz.Rect(r.x0 + 6, r.y0 + h * 0.18, r.x1 + 10, r.y1 + 4), t, rng, fontsize=fs, color=text_color)
            if prev_edge is not None:
                arrow(shape, (prev_edge + 3, cy + rng.uniform(-1.5, 1.5)),
                      (r.x0 - 8, cy + rng.uniform(-1.5, 1.5)), rng, color=color)
            prev_edge = r.x1 + 4
            x = r.x1 + gap
        if title:
            note_text(page, fitz.Rect(area.x0 + 10, area.y0 - 2, area.x1, area.y0 + 14), title, rng, fontsize=9.5, color=text_color)
    else:
        fs = 9.5
        y = area.y0
        if title:
            note_text(page, fitz.Rect(area.x0, y, area.x1, y + 15), title, rng, fontsize=fs, color=text_color)
            y += 16
        prev_bottom = None
        cx = area.x0 + area.width / 2
        for t in labels:
            h = fs * 1.9
            w = min(area.width - 4, _note_font.text_length(t, fs) + 14)
            r = fitz.Rect(cx - w / 2, y, cx + w / 2, y + h)
            circle(shape, r + (2, 2, -2, -2), rng, color=color)
            note_text(page, fitz.Rect(r.x0 + 6, r.y0 + h * 0.18, r.x1 + 10, r.y1 + 4), t, rng, fontsize=fs, color=text_color)
            if prev_bottom is not None:
                arrow(shape, (cx + rng.uniform(-2, 2), prev_bottom + 2),
                      (cx + rng.uniform(-2, 2), r.y0 - 3), rng, color=color)
            prev_bottom = r.y1
            y = r.y1 + 15


def blank_page_doodle(page, shape, bounds, rng, color=INK_BLUE):
    """A tiny zero-token easter egg for genuinely blank interior pages."""
    size = min(54.0, max(34.0, bounds.width * 0.09))
    x1 = bounds.x1 - 24
    y1 = bounds.y1 - 28
    x0 = x1 - size
    y0 = y1 - size * 0.55
    mid = (x0 + x1) / 2
    # Open book: two imperfect page leaves and a central spine.
    left = [
        fitz.Point(x0, y0 + 5),
        fitz.Point(mid - 2, y0),
        fitz.Point(mid - 2, y1),
        fitz.Point(x0, y1 - 5),
        fitz.Point(x0, y0 + 5),
    ]
    right = [
        fitz.Point(mid + 2, y0),
        fitz.Point(x1, y0 + 5),
        fitz.Point(x1, y1 - 5),
        fitz.Point(mid + 2, y1),
        fitz.Point(mid + 2, y0),
    ]
    _stroke(shape, left, rng, width=0.9, color=color)
    _stroke(shape, right, rng, width=0.9, color=color)
    _stroke(shape, _wavy((mid, y0 + 1), (mid, y1 - 1), rng, amp=0.35, step=4), rng, width=0.8, color=color)
    doodle(shape, (x0 - 8, y0 - 5), rng, "star", size=4.0, color=color)
