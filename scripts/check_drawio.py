#!/usr/bin/env python3
"""Check a draw.io diagram against the drawing rules used in this repo.

Usage:
    python3 scripts/check_drawio.py <file.drawio> [--preview DIR]

For every page it checks that:
  1. the XML parses, cell ids are unique and every connector's ends exist
  2. the only colours are black, white or 'none'
  3. every attached connector pins its exit and entry points, so routing is fixed
  4. every connector segment is horizontal or vertical
  5. no two connectors cross, touch or run along each other
  6. no connector runs through a shape (dashed boundary frames are exempt)
  7. no two shapes partly overlap (one shape fully inside another is fine)
  8. text fits its shape, and connector labels sit on empty space

--preview DIR also writes a rough SVG of each page, for a quick visual check.
It is an approximation of draw.io's rendering, not a replacement for it.
Exit status is 1 if any check fails.
"""

from __future__ import annotations

import argparse
import base64
import html
import math
import re
import sys
import urllib.parse
import zlib
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from itertools import combinations
from pathlib import Path

ALLOWED_COLOURS = {"#000000", "#ffffff", "none"}
COLOUR_KEYS = {"fillColor", "strokeColor", "fontColor", "labelBackgroundColor", "labelBorderColor",
               "gradientColor", "swimlaneFillColor", "imageBackground", "imageBorder"}
EPS = 1e-6
LINE_HEIGHT = 1.2  # draw.io default

# Helvetica advance widths in 1/1000 em (regular weight); unknown characters count as 556.
_WIDTHS = {191: "'", 222: "ijl‘’", 260: "|", 278: " !,./:;I[\\]ft·", 333: "()-`r", 334: "{}", 355: '"',
           389: "*", 469: "^", 500: "Jckvxyzs", 556: "0123456789abdeghnopqu#$?_L–", 584: "+<=>~",
           611: "FTZ", 667: "&ABEKPSVXY", 722: "CDHNRUw", 778: "GOQ", 833: "Mm", 889: "%", 944: "W",
           1000: "→—…", 1015: "@"}
CHAR_WIDTH = {ch: w for w, chars in _WIDTHS.items() for ch in chars}


def text_width(text: str, size: float, bold: bool) -> float:
    return sum(CHAR_WIDTH.get(ch, 556) for ch in text) / 1000 * size * (1.08 if bold else 1.0)


def parse_style(style: str | None) -> dict[str, str]:
    out: dict[str, str] = {}
    for part in (style or "").split(";"):
        if not part:
            continue
        key, _, value = part.partition("=")
        out[key] = value if _ else "1"   # a bare name such as 'text' is a named style
    return out


def label_lines(value: str) -> list[tuple[str, bool]]:
    """Split an HTML label into (plain text, is_bold) lines."""
    lines = []
    for raw in re.split(r"<br\s*/?>|\n", value or "", flags=re.I):
        bold = bool(re.fullmatch(r"\s*<b>.*</b>\s*", raw, flags=re.I))
        lines.append((html.unescape(re.sub(r"<[^>]+>", "", raw)), bold))
    return lines


@dataclass
class Shape:
    id: str
    value: str
    style: dict[str, str]
    x: float
    y: float
    w: float
    h: float

    @property
    def rect(self) -> tuple[float, float, float, float]:
        return (self.x, self.y, self.x + self.w, self.y + self.h)

    @property
    def is_boundary(self) -> bool:
        return self.style.get("dashed") == "1" and self.style.get("fillColor", "").lower() == "none"


@dataclass
class Connector:
    id: str
    value: str
    style: dict[str, str]
    source: str | None
    target: str | None
    waypoints: list[tuple[float, float]]
    source_point: tuple[float, float] | None
    target_point: tuple[float, float] | None
    label_at: float
    path: list[tuple[float, float]] = field(default_factory=list)

    def segments(self):
        return list(zip(self.path, self.path[1:]))


# ------------------------------------------------------------------ parsing
def load_pages(path: Path) -> list[tuple[str, ET.Element]]:
    root = ET.parse(path).getroot()          # raises ParseError on malformed XML
    if root.tag != "mxfile":
        raise ValueError(f"root element is <{root.tag}>, expected <mxfile>")
    pages = []
    for diagram in root.findall("diagram"):
        model = diagram.find("mxGraphModel")
        if model is None:                    # compressed page: base64 + raw deflate + URL-encoding
            data = zlib.decompress(base64.b64decode((diagram.text or "").strip()), -15)
            model = ET.fromstring(urllib.parse.unquote(data.decode("utf-8")))
        pages.append((diagram.get("name", diagram.get("id", "?")), model))
    return pages


def read_page(model: ET.Element, problems: list[str]):
    shapes: dict[str, Shape] = {}
    connectors: list[Connector] = []
    order: list[object] = []
    parents: dict[str, str | None] = {}
    seen: set[str] = set()
    for element in model.find("root"):
        if element.tag in ("object", "UserObject"):      # cell wrapped to carry custom data
            cell, cid, value = element.find("mxCell"), element.get("id"), element.get("label", "")
        else:
            cell, cid, value = element, element.get("id"), element.get("value", "")
        if cid in seen:
            problems.append(f"duplicate cell id '{cid}'")
        seen.add(cid)
        style = parse_style(cell.get("style"))
        geo = cell.find("mxGeometry")
        if cell.get("vertex") == "1":
            shape = Shape(cid, value, style, float(geo.get("x", 0)), float(geo.get("y", 0)),
                          float(geo.get("width", 0)), float(geo.get("height", 0)))
            shapes[cid] = shape
            parents[cid] = cell.get("parent")
            order.append(shape)
        elif cell.get("edge") == "1":
            waypoints, sp, tp = [], None, None
            if geo is not None:
                arr = geo.find("Array[@as='points']")
                if arr is not None:
                    waypoints = [(float(p.get("x", 0)), float(p.get("y", 0))) for p in arr.findall("mxPoint")]
                for p in geo.findall("mxPoint"):
                    if p.get("as") == "sourcePoint":
                        sp = (float(p.get("x", 0)), float(p.get("y", 0)))
                    elif p.get("as") == "targetPoint":
                        tp = (float(p.get("x", 0)), float(p.get("y", 0)))
            conn = Connector(cid, value, style, cell.get("source"), cell.get("target"), waypoints, sp, tp,
                             float(geo.get("x", 0)) if geo is not None else 0.0)
            parents[cid] = cell.get("parent")
            connectors.append(conn)
            order.append(conn)

    def offset(parent_id: str | None) -> tuple[float, float]:
        if parent_id in shapes:
            px, py = offset(parents.get(parent_id))
            return px + shapes[parent_id].x, py + shapes[parent_id].y
        return 0.0, 0.0

    # Turn child coordinates into page coordinates (shapes nested in containers).
    absolute = {cid: offset(parents[cid]) for cid in shapes}
    for cid, (dx, dy) in absolute.items():
        shapes[cid].x += dx
        shapes[cid].y += dy
    for conn in connectors:
        dx, dy = offset(parents.get(conn.id))
        conn.waypoints = [(x + dx, y + dy) for x, y in conn.waypoints]
        conn.path = connector_path(conn, shapes, problems)
    return shapes, connectors, order


def connector_path(conn: Connector, shapes: dict[str, Shape], problems: list[str]):
    st = conn.style

    def end(shape_id, point, fx_key, fy_key, dx_key, dy_key):
        if shape_id is None:
            if point is None:
                problems.append(f"connector '{conn.id}' has a loose end with no point")
                return (0.0, 0.0)
            return point
        shape = shapes.get(shape_id)
        if shape is None:
            problems.append(f"connector '{conn.id}' points at missing shape '{shape_id}'")
            return (0.0, 0.0)
        if fx_key in st and fy_key in st:
            fx, fy = float(st[fx_key]), float(st[fy_key])
        else:
            fx, fy = 0.5, 0.5
        return (shape.x + fx * shape.w + float(st.get(dx_key, 0)), shape.y + fy * shape.h + float(st.get(dy_key, 0)))

    start = end(conn.source, conn.source_point, "exitX", "exitY", "exitDx", "exitDy")
    finish = end(conn.target, conn.target_point, "entryX", "entryY", "entryDx", "entryDy")
    return [start, *conn.waypoints, finish]


# ------------------------------------------------------------------ geometry
def orient(a, b, c) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def on_segment(a, b, p) -> bool:
    return (min(a[0], b[0]) - EPS <= p[0] <= max(a[0], b[0]) + EPS
            and min(a[1], b[1]) - EPS <= p[1] <= max(a[1], b[1]) + EPS)


def segments_meet(s1, s2) -> bool:
    """True if two segments cross, touch or overlap."""
    (p1, p2), (p3, p4) = s1, s2
    d1, d2, d3, d4 = orient(p3, p4, p1), orient(p3, p4, p2), orient(p1, p2, p3), orient(p1, p2, p4)
    if ((d1 > EPS and d2 < -EPS) or (d1 < -EPS and d2 > EPS)) and \
       ((d3 > EPS and d4 < -EPS) or (d3 < -EPS and d4 > EPS)):
        return True
    return ((abs(d1) <= EPS and on_segment(p3, p4, p1)) or (abs(d2) <= EPS and on_segment(p3, p4, p2))
            or (abs(d3) <= EPS and on_segment(p1, p2, p3)) or (abs(d4) <= EPS and on_segment(p1, p2, p4)))


def meeting_point(s1, s2):
    """A representative point where two meeting segments touch (for messages)."""
    for p in (*s1, *s2):
        if on_segment(*s1, p) and on_segment(*s2, p):
            return p
    (x1, y1), (x2, y2) = s1
    (x3, y3), (x4, y4) = s2
    den = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
    t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / den
    return (x1 + t * (x2 - x1), y1 + t * (y2 - y1))


def inside(p, r) -> bool:
    return r[0] - EPS <= p[0] <= r[2] + EPS and r[1] - EPS <= p[1] <= r[3] + EPS


def rect_edges(r):
    a, b, c, d = (r[0], r[1]), (r[2], r[1]), (r[2], r[3]), (r[0], r[3])
    return [(a, b), (b, c), (c, d), (d, a)]


def segment_hits_rect(seg, r) -> bool:
    if r[2] - r[0] <= 0 or r[3] - r[1] <= 0:
        return False
    return inside(seg[0], r) or inside(seg[1], r) or any(segments_meet(seg, e) for e in rect_edges(r))


def shrink(r, by):
    return (r[0] + by, r[1] + by, r[2] - by, r[3] - by)


def overlap_area(a, b) -> float:
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    return w * h if w > EPS and h > EPS else 0.0


def contains(outer, inner) -> bool:
    return (outer[0] - EPS <= inner[0] and outer[1] - EPS <= inner[1]
            and outer[2] + EPS >= inner[2] and outer[3] + EPS >= inner[3])


def point_along(path, fraction):
    lengths = [math.dist(a, b) for a, b in zip(path, path[1:])]
    remaining = fraction * sum(lengths)
    for (a, b), length in zip(zip(path, path[1:]), lengths):
        if remaining <= length or length == 0:
            t = remaining / length if length else 0
            return (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]))
        remaining -= length
    return path[-1]


# ------------------------------------------------------------------ text
def label_area(shape: Shape):
    """(x0, y0, x1, y1) of the area draw.io lays the label out in, for shapes with inside labels."""
    st = shape.style
    spacing = float(st.get("spacing", 2))
    x0 = shape.x + spacing + float(st.get("spacingLeft", 0))
    x1 = shape.x + shape.w - spacing - float(st.get("spacingRight", 0))
    y0 = shape.y + spacing + float(st.get("spacingTop", 0))
    y1 = shape.y + shape.h - spacing - float(st.get("spacingBottom", 0))
    if st.get("boundedLbl") == "1":
        if st.get("shape") == "cylinder3":
            size = float(st.get("size", 15))
            y0 += 2 * size
            y1 -= 0.3 * size
        elif st.get("shape") == "document":
            y1 -= float(st.get("size", 0.3)) * shape.h
    return x0, y0, x1, y1


def font(style: dict[str, str]) -> tuple[float, bool]:
    return float(style.get("fontSize", 11)), bool(int(style.get("fontStyle", "0") or 0) & 1)


def check_text(shape: Shape, errors: list[str], warnings: list[str]) -> None:
    if not shape.value or shape.style.get("labelPosition") == "right":
        return
    size, bold_all = font(shape.style)
    x0, y0, x1, y1 = label_area(shape)
    width, height = x1 - x0, y1 - y0
    lines = label_lines(shape.value)
    total = 0
    for text, bold in lines:
        w = text_width(text, size, bold or bold_all)
        if w > width + 0.5:
            warnings.append(f"'{shape.id}': \"{text}\" is about {w:.0f}px wide; the box allows {width:.0f}px, "
                            "so draw.io will wrap it")
        total += max(1, math.ceil(w / width)) if width > 0 else 1
    if shape.is_boundary:                     # frame title only; the frame is far taller than one line
        return
    needed = total * size * LINE_HEIGHT
    if needed > height + 0.5:
        errors.append(f"'{shape.id}': text needs about {needed:.0f}px of height; the box allows {height:.0f}px")


def connector_label_box(conn: Connector):
    if not conn.value:
        return None
    size, bold_all = font(conn.style)
    lines = label_lines(conn.value)
    w = max(text_width(t, size, b or bold_all) for t, b in lines) + 4
    h = len(lines) * size * LINE_HEIGHT + 2
    cx, cy = point_along(conn.path, (conn.label_at + 1) / 2)
    return (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)


# ------------------------------------------------------------------ checks
def check_page(model: ET.Element):
    errors: list[str] = []
    warnings: list[str] = []
    shapes, connectors, _ = read_page(model, errors)

    # 2. colours
    background = (model.get("background") or "none").lower()
    if background not in ALLOWED_COLOURS:
        errors.append(f"page background {background} is not black, white or none")
    for item in [*shapes.values(), *connectors]:
        for key in COLOUR_KEYS & item.style.keys():
            if item.style[key].lower() not in ALLOWED_COLOURS:
                errors.append(f"'{item.id}': {key}={item.style[key]} is not black, white or none")
        if re.search(r"color\s*[:=]", item.value or "", flags=re.I):
            errors.append(f"'{item.id}': the label sets its own colour")

    for conn in connectors:
        # 3. pinned ends
        if conn.source and conn.target:
            missing = [k for k in ("exitX", "exitY", "entryX", "entryY") if k not in conn.style]
            if missing:
                errors.append(f"'{conn.id}': routing is not fixed, missing {', '.join(missing)}")
        # 4. horizontal or vertical only
        for (ax, ay), (bx, by) in conn.segments():
            if abs(ax - bx) > EPS and abs(ay - by) > EPS:
                errors.append(f"'{conn.id}': segment ({ax:g},{ay:g})→({bx:g},{by:g}) is diagonal")

    # 5. connectors never meet
    for a, b in combinations(connectors, 2):
        for sa in a.segments():
            hit = next((sb for sb in b.segments() if segments_meet(sa, sb)), None)
            if hit:
                x, y = meeting_point(sa, hit)
                errors.append(f"connectors '{a.id}' and '{b.id}' meet at ({x:.0f},{y:.0f})")
                break

    # 6. connectors never run through shapes
    holders = {a.id for a in shapes.values() for b in shapes.values()
               if a is not b and contains(a.rect, b.rect)}      # frames such as the legend box
    for conn in connectors:
        ends = (conn.source, conn.target)
        for shape in shapes.values():
            if shape.is_boundary:
                continue                       # connectors may cross a dashed boundary
            if shape.id in holders and shape.id not in ends and all(inside(p, shape.rect) for p in conn.path):
                continue                       # a frame that holds the whole connector, e.g. a legend sample
            area = shrink(shape.rect, 1) if shape.id in ends else shape.rect
            if any(segment_hits_rect(seg, area) for seg in conn.segments()):
                errors.append(f"connector '{conn.id}' runs through shape '{shape.id}'")

    # 7a. everything, including labels drawn beside a shape, stays on the page
    page_w, page_h = float(model.get("pageWidth", 0)), float(model.get("pageHeight", 0))
    if page_w and page_h:
        for shape in shapes.values():
            x0, y0, x1, y1 = shape.rect
            if shape.style.get("labelPosition") == "right" and shape.value:
                size, bold_all = font(shape.style)
                widest = max(text_width(t, size, b or bold_all) for t, b in label_lines(shape.value))
                x1 += float(shape.style.get("spacingLeft", 0)) + 2 + widest
            if x0 < 0 or y0 < 0 or x1 > page_w or y1 > page_h:
                errors.append(f"'{shape.id}' extends past the page edge ({x1:.0f} × {y1:.0f} "
                              f"on a {page_w:.0f} × {page_h:.0f} page)")

    # 7b. no partial overlaps between shapes
    for a, b in combinations(shapes.values(), 2):
        if overlap_area(a.rect, b.rect) > 0 and not contains(a.rect, b.rect) and not contains(b.rect, a.rect):
            errors.append(f"shapes '{a.id}' and '{b.id}' partly overlap")

    # 8. text fits, connector labels sit on empty space
    for shape in shapes.values():
        check_text(shape, errors, warnings)
    boxes = {c.id: connector_label_box(c) for c in connectors}
    for conn in connectors:
        box = boxes[conn.id]
        if box is None:
            continue
        for shape in shapes.values():
            if shape.is_boundary:
                if any(segment_hits_rect(edge, box) for edge in rect_edges(shape.rect)):
                    errors.append(f"label of '{conn.id}' sits on the frame line of '{shape.id}'")
            elif overlap_area(box, shape.rect) > 0:
                errors.append(f"label of '{conn.id}' sits on shape '{shape.id}'")
        for other in connectors:
            if other is not conn and any(segment_hits_rect(seg, box) for seg in other.segments()):
                errors.append(f"label of '{conn.id}' covers connector '{other.id}'")
            other_box = boxes[other.id]
            if other is not conn and other_box is not None and overlap_area(box, other_box) > 0 and conn.id < other.id:
                errors.append(f"labels of '{conn.id}' and '{other.id}' overlap")
    return errors, warnings, shapes, connectors


# ------------------------------------------------------------------ preview
def svg_text_lines(lines, x, y_first, anchor, size, bold_all):
    out = []
    for i, (text, bold) in enumerate(lines):
        weight = "bold" if bold or bold_all else "normal"
        out.append(f'<text x="{x:.1f}" y="{y_first + i * size * LINE_HEIGHT:.1f}" font-size="{size}" '
                   f'font-weight="{weight}" text-anchor="{anchor}" fill="#000">{html.escape(text)}</text>')
    return out


def svg_shape(shape: Shape) -> list[str]:
    st, (x, y, w, h) = shape.style, (shape.x, shape.y, shape.w, shape.h)
    dash = ' stroke-dasharray="6 4"' if st.get("dashed") == "1" else ""
    fill = "none" if st.get("fillColor", "#FFFFFF").lower() == "none" else "#FFFFFF"
    stroke = "none" if st.get("strokeColor", "#000000").lower() == "none" else "#000"
    attrs = f'fill="{fill}" stroke="{stroke}" stroke-width="1"{dash}'
    kind = st.get("shape")
    out = []
    if "text" in st:
        pass
    elif kind == "cylinder3":
        s = float(st.get("size", 15))
        out.append(f'<path d="M{x},{y + s} L{x},{y + h - s} A{w / 2},{s} 0 0 0 {x + w},{y + h - s} '
                   f'L{x + w},{y + s}" {attrs}/>')
        out.append(f'<ellipse cx="{x + w / 2}" cy="{y + s}" rx="{w / 2}" ry="{s}" {attrs}/>')
    elif kind == "document":
        d = float(st.get("size", 0.3)) * h
        out.append(f'<path d="M{x},{y} L{x + w},{y} L{x + w},{y + h - d / 2} '
                   f'C{x + w * 0.75},{y + h - d * 1.4} {x + w * 0.25},{y + h + d * 0.4} {x},{y + h - d / 2} Z" {attrs}/>')
    elif kind == "umlActor":
        r = min(w / 2, h / 4) / 2
        hx, hy = x + w / 2, y + r
        out.append(f'<circle cx="{hx}" cy="{hy}" r="{r}" {attrs}/>')
        out.append(f'<path d="M{hx},{y + 2 * r} L{hx},{y + h * 2 / 3} M{x},{y + h / 3} L{x + w},{y + h / 3} '
                   f'M{hx},{y + h * 2 / 3} L{x},{y + h} M{hx},{y + h * 2 / 3} L{x + w},{y + h}" '
                   f'fill="none" stroke="#000" stroke-width="1"/>')
    else:
        rx = min(w, h) * float(st.get("arcSize", 10)) / 100 if st.get("rounded") == "1" else 0
        out.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" {attrs}/>')
    if shape.value:
        size, bold_all = font(st)
        lines = label_lines(shape.value)
        block = len(lines) * size * LINE_HEIGHT
        if st.get("labelPosition") == "right":
            lx = x + w + float(st.get("spacingLeft", 0)) + 2
            out += svg_text_lines(lines, lx, y + h / 2 - block / 2 + size * 0.85, "start", size, bold_all)
        else:
            x0, y0, x1, y1 = label_area(shape)
            align = st.get("align", "center")
            lx, anchor = ((x0, "start") if align == "left" else (x1, "end") if align == "right"
                          else ((x0 + x1) / 2, "middle"))
            valign = st.get("verticalAlign", "middle")
            top = y0 if valign == "top" else (y1 - block if valign == "bottom" else (y0 + y1) / 2 - block / 2)
            out += svg_text_lines(lines, lx, top + size * 0.85, anchor, size, bold_all)
    return out


def svg_connector(conn: Connector, box) -> list[str]:
    st = conn.style
    dash = ' stroke-dasharray="4 3"' if st.get("dashed") == "1" else ""
    end = "open" if st.get("endArrow") == "open" else "block" if st.get("endArrow", "classic") != "none" else None
    start = "block" if st.get("startArrow") == "block" else None
    points = " ".join(f"{x:.1f},{y:.1f}" for x, y in conn.path)
    markers = (f' marker-end="url(#{end})"' if end else "") + (' marker-start="url(#block)"' if start else "")
    out = [f'<polyline points="{points}" fill="none" stroke="#000" stroke-width="1"{dash}{markers}/>']
    if box:
        size, bold_all = font(st)
        lines = label_lines(conn.value)
        out.append(f'<rect x="{box[0]:.1f}" y="{box[1]:.1f}" width="{box[2] - box[0]:.1f}" '
                   f'height="{box[3] - box[1]:.1f}" fill="#FFFFFF"/>')
        out += svg_text_lines(lines, (box[0] + box[2]) / 2, box[1] + 1 + size * 0.85, "middle", size, bold_all)
    return out


def write_preview(model: ET.Element, out: Path) -> None:
    problems: list[str] = []
    shapes, connectors, order = read_page(model, problems)
    width, height = int(float(model.get("pageWidth", 1654))), int(float(model.get("pageHeight", 1169)))
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
             f'viewBox="0 0 {width} {height}" font-family="Helvetica, Arial, sans-serif">',
             '<defs>'
             '<marker id="block" viewBox="0 0 10 10" refX="10" refY="5" markerWidth="8" markerHeight="8" '
             'orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="#000"/></marker>'
             '<marker id="open" viewBox="0 0 10 10" refX="10" refY="5" markerWidth="8" markerHeight="8" '
             'orient="auto"><path d="M0,0 L10,5 L0,10" fill="none" stroke="#000"/></marker>'
             '</defs>',
             f'<rect width="{width}" height="{height}" fill="#FFFFFF"/>']
    for item in order:
        if isinstance(item, Shape):
            parts += svg_shape(item)
        else:
            parts += svg_connector(item, connector_label_box(item))
    parts.append("</svg>")
    out.write_text("\n".join(parts), encoding="utf-8")


# ------------------------------------------------------------------ main
def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("diagram", type=Path)
    parser.add_argument("--preview", type=Path, help="folder to write one rough SVG per page into")
    args = parser.parse_args()

    try:
        pages = load_pages(args.diagram)
    except (ET.ParseError, ValueError, zlib.error) as exc:
        print(f"FAIL  {args.diagram}: cannot read diagram: {exc}")
        return 1

    failed = False
    for index, (name, model) in enumerate(pages, start=1):
        errors, warnings, shapes, connectors = check_page(model)
        status = "FAIL" if errors else "ok  "
        print(f"{status}  page {index} '{name}': {len(shapes)} shapes, {len(connectors)} connectors, "
              f"{len(errors)} errors, {len(warnings)} warnings")
        for message in errors:
            print(f"      error:   {message}")
        for message in warnings:
            print(f"      warning: {message}")
        failed |= bool(errors)
        if args.preview:
            args.preview.mkdir(parents=True, exist_ok=True)
            target = args.preview / f"page{index}.svg"
            write_preview(model, target)
            print(f"      preview: {target}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
