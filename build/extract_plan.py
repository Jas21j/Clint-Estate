#!/usr/bin/env python3
"""Read the two AutoCAD floor-plan PDFs and write build/plan.json (all sizes in metres).

The PDFs are vector drawings, so every wall is stored as "line from A to B". This script
turns those lines into data a 3D builder can use:

  walls     closed outlines, traced exactly from the drawing
  openings  gaps between wall ends, labelled window / door / slider / cased
  rooms     floor area found by flood-filling from each room label
  slabs     floor plate, roof plate and parapet as simple rectangles
  cabinets  counter footprints, fixtures (tubs, toilets, sinks), stairs, railings

Run with Blender's bundled Python (it ships numpy):
  /Applications/Blender.app/Contents/Resources/5.2/python/bin/python3.13 build/extract_plan.py
"""
import json
import math
import re
import subprocess
import sys
from collections import defaultdict, deque
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "build" / "cache"
LEVELS = [
    ("ground", ROOT / "003 - CLINT - GROUND PLAN.pdf"),
    ("first", ROOT / "004 - CLINT - FIRST FLOOR PLAN.pdf"),
]

# The PDF stores 600 units per inch and the sheet was plotted "to fit", not at a round scale.
# 80 units per foot makes every wall exactly 6 in thick and every room match its printed size.
U_PER_FT = 80.0
U2M = 0.3048 / U_PER_FT
MAIN = "matrix(0.12, 0, 0, -0.12, 14, 764)"   # drawing units -> page points
PX = 5.0                                      # raster cell, drawing units (about 2 cm)

import os
DEBUG_DIR = os.environ.get("PLAN_DEBUG")

ROOM_NAMES = {"LIVING", "BEDROOM", "BEDROOM 2", "BATH", "BALCONY", "CLOSET", "ENTRY", "STAIRWELL",
              "LAUNDRY", "CAR PORT", "HALL", "OPEN DECK"}
OPEN_AIR = {"BALCONY", "OPEN DECK", "HALL", "ENTRY", "CAR PORT"}


# ---------------------------------------------------------------- svg parsing
def parse_d(d, steps=10):
    """SVG path data -> list of (points, is_curved). Curves are flattened to short lines."""
    toks = re.findall(r"[MLCZ]|-?\d+\.?\d*(?:e-?\d+)?", d)
    subs, cur, curved, i, cmd = [], [], False, 0, None
    while i < len(toks):
        t = toks[i]
        if t in "MLCZ":
            cmd = t
            i += 1
            if t == "Z" and cur:
                cur.append(cur[0])
                subs.append((cur, curved))
                cur, curved = [], False
            continue
        if cmd == "M":
            if cur:
                subs.append((cur, curved))
            cur, curved = [(float(toks[i]), float(toks[i + 1]))], False
            i += 2
            cmd = "L"
        elif cmd == "L":
            cur.append((float(toks[i]), float(toks[i + 1])))
            i += 2
        elif cmd == "C":
            p0 = cur[-1]
            c1 = (float(toks[i]), float(toks[i + 1]))
            c2 = (float(toks[i + 2]), float(toks[i + 3]))
            p3 = (float(toks[i + 4]), float(toks[i + 5]))
            i += 6
            curved = True
            for k in range(1, steps + 1):
                u = k / steps
                v = 1 - u
                cur.append((v ** 3 * p0[0] + 3 * v * v * u * c1[0] + 3 * v * u * u * c2[0] + u ** 3 * p3[0],
                            v ** 3 * p0[1] + 3 * v * v * u * c1[1] + 3 * v * u * u * c2[1] + u ** 3 * p3[1]))
        else:
            i += 1
    if cur:
        subs.append((cur, curved))
    return subs


def style_key(attrs):
    def rgb(name):
        m = re.search(r'\b' + name + r'="rgb\(([^)]*)\)"', attrs)
        return tuple(round(float(x.strip().rstrip("%"))) for x in m.group(1).split(",")) if m else None
    sw = re.search(r'stroke-width="([^"]*)"', attrs)
    return (sw.group(1) if sw else None, rgb("stroke"), rgb("fill"))


def load_layers(svg_path):
    """Sort every path into a layer by its pen style (AutoCAD kept one style per layer)."""
    text = svg_path.read_text()
    layers = defaultdict(list)
    for m in re.finditer(r"<path ([^>]*)/>", text):
        attrs = m.group(1)
        if MAIN not in attrs:
            continue
        sw, stroke, fill = style_key(attrs)
        if sw == "24" and stroke == (0, 0, 0):
            name = "wall"
        elif stroke == (0, 0, 100) and fill is None:
            name = "window"
        elif stroke == (29, 29, 29):
            name = "door"            # doors, railings, dashed overhead lines
        elif fill == (91, 89, 89):
            name = "cabfill"         # countertop fill triangles
        elif stroke == (50, 25, 25):
            name = "fixture"
        elif sw == "6" and stroke == (0, 0, 0):
            name = "stair"
        elif sw == "4" and stroke == (0, 0, 0):
            name = "slab"            # deck edge, balcony outlines
        else:
            continue
        d = re.search(r' d="([^"]*)"', attrs).group(1)
        layers[name] += parse_d(d)
    return layers


def load_labels(pdf_path):
    """Room names and their printed sizes, positioned in drawing units."""
    xml = subprocess.run(["pdftotext", "-bbox-layout", str(pdf_path), "-"], capture_output=True, text=True).stdout
    lines = []
    for lm in re.finditer(r'<line xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">(.*?)</line>', xml, re.S):
        x0, y0, x1, y1 = (float(lm.group(k)) for k in range(1, 5))
        words = re.findall(r"<word[^>]*>(.*?)</word>", lm.group(5))
        txt = " ".join(words).replace("&apos;", "'").replace("&quot;", '"').replace("&amp;", "&")
        lines.append({"text": txt.strip(), "x": (x0 + x1) / 2, "y": (y0 + y1) / 2, "vertical": (y1 - y0) > (x1 - x0)})
    dim_re = re.compile(r"(\d+)'-(\d+)\"")
    names = [l for l in lines if l["text"] in ROOM_NAMES]
    dims = [l for l in lines if len(dim_re.findall(l["text"])) == 2]
    out = []
    for n in names:
        best = min(dims, key=lambda q: math.hypot(q["x"] - n["x"], q["y"] - n["y"]), default=None)
        w = dpt = None
        cx, cy = n["x"], n["y"]
        if best and math.hypot(best["x"] - n["x"], best["y"] - n["y"]) < 26:
            (a, b), (c, e) = dim_re.findall(best["text"])
            w, dpt = int(a) + int(b) / 12, int(c) + int(e) / 12
            if n["vertical"]:
                w, dpt = dpt, w
            cx, cy = (n["x"] + best["x"]) / 2, (n["y"] + best["y"]) / 2
        out.append({"name": n["text"], "w_ft": w, "d_ft": dpt,
                    "u": ((cx - 14) / 0.12, (764 - cy) / 0.12)})
    return out


# ------------------------------------------------------------------ geometry
def sub(a, b): return (a[0] - b[0], a[1] - b[1])
def add(a, b): return (a[0] + b[0], a[1] + b[1])
def mul(a, s): return (a[0] * s, a[1] * s)
def dot(a, b): return a[0] * b[0] + a[1] * b[1]
def cross(a, b): return a[0] * b[1] - a[1] * b[0]
def norm(a):
    n = math.hypot(a[0], a[1])
    return (a[0] / n, a[1] / n) if n else (0.0, 0.0)


def outer_boundary(comp, adj):
    """Outline of one connected clump of wall lines, even where lines cross or overlap.

    Walks the outside face of the line network (always taking the next line clockwise),
    which is the standard way to get the silhouette of a planar drawing."""
    edges = {frozenset((a, b)) for a in comp for b in adj[a]}
    changed = True
    while changed:                                  # split a line where another line's end lands on it
        changed = False
        for e in list(edges):
            a, b = tuple(e)
            ab = sub(b, a)
            l2 = dot(ab, ab)
            if l2 < 1e-9:
                edges.discard(e)
                continue
            for v in comp:
                if v == a or v == b:
                    continue
                t = dot(sub(v, a), ab) / l2
                if 0.02 < t < 0.98 and abs(cross(sub(v, a), ab)) / math.sqrt(l2) < 1.6:
                    edges.discard(e)
                    edges.add(frozenset((a, v)))
                    edges.add(frozenset((v, b)))
                    changed = True
                    break
            if changed:
                break
    nbr = defaultdict(list)
    for e in edges:
        if len(e) == 2:
            a, b = tuple(e)
            nbr[a].append(b)
            nbr[b].append(a)
    pruned = True
    while pruned:                                   # trim dangling stubs
        pruned = False
        for v in [v for v, n in nbr.items() if len(n) <= 1]:
            for o in nbr.pop(v):
                nbr[o].remove(v)
            pruned = True
    if len(nbr) < 3:
        return None
    for v in nbr:
        nbr[v].sort(key=lambda w: math.atan2(w[1] - v[1], w[0] - v[0]))
    visited, faces = set(), []
    for u in nbr:
        for v in nbr[u]:
            if (u, v) in visited:
                continue
            face, a, b = [], u, v
            while (a, b) not in visited:
                visited.add((a, b))
                face.append(a)
                ring = nbr[b]
                a, b = b, ring[(ring.index(a) - 1) % len(ring)]
            faces.append(face)
    area = lambda f: abs(sum(cross(f[i], f[(i + 1) % len(f)]) for i in range(len(f)))) / 2
    return max(faces, key=area)


def wall_loops(polys):
    """Chain loose wall lines into closed outlines. Returns (loops, leftover_point_groups)."""
    segs = [(p, q) for pts, _ in polys for p, q in zip(pts, pts[1:])]
    key = lambda p: (round(p[0]), round(p[1]))
    keys = {key(p) for s in segs for p in s}
    parent = {k: k for k in keys}

    def find(k):
        while parent[k] != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k

    grid = defaultdict(list)
    for k in keys:
        grid[(k[0] // 3, k[1] // 3)].append(k)
    for k in keys:                                  # weld points that are within 2 units
        cx, cy = k[0] // 3, k[1] // 3
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for o in grid.get((cx + dx, cy + dy), ()):
                    if o != k and abs(o[0] - k[0]) <= 2 and abs(o[1] - k[1]) <= 2:
                        parent[find(o)] = find(k)
    adj = defaultdict(set)
    for p, q in segs:
        a, b = find(key(p)), find(key(q))
        if a != b:
            adj[a].add(b)
            adj[b].add(a)
    loops, bad, seen = [], [], set()
    for v in list(adj):
        if v in seen:
            continue
        comp, stack = [], [v]
        seen.add(v)
        while stack:
            x = stack.pop()
            comp.append(x)
            for y in adj[x]:
                if y not in seen:
                    seen.add(y)
                    stack.append(y)
        outline = outer_boundary(comp, adj)
        if outline and len(outline) >= 3:
            loops.append(outline)
        else:
            bad.append(comp)
    clean = []
    for loop in loops:
        pts = [tuple(map(float, p)) for p in loop]
        out = []
        n = len(pts)
        for i in range(n):                          # drop points that sit on a straight run
            a, b, c = pts[i - 1], pts[i], pts[(i + 1) % n]
            if abs(cross(sub(b, a), sub(c, b))) > 2.0:
                out.append(b)
        if len(out) >= 3:
            area = sum(cross(out[i], out[(i + 1) % len(out)]) for i in range(len(out))) / 2
            if area < 0:
                out.reverse()
            clean.append(out)
    return clean, bad


def convex_hull(points):
    pts = sorted(set(points))
    if len(pts) < 3:
        return pts
    def half(seq):
        h = []
        for p in seq:
            while len(h) >= 2 and cross(sub(h[-1], h[-2]), sub(p, h[-1])) <= 0:
                h.pop()
            h.append(p)
        return h
    lo, hi = half(pts), half(reversed(pts))
    return lo[:-1] + hi[:-1]


def find_gaps(loops, layers):
    """A gap is the space in front of a wall end. Drawn evidence decides what kind it is."""
    edges = []
    for li, loop in enumerate(loops):
        n = len(loop)
        for i in range(n):
            edges.append((loop[i], loop[(i + 1) % n], li, i))
    ea = np.array([[e[0][0], e[0][1], e[1][0], e[1][1]] for e in edges])

    def ray(o, d, skip):
        ax, ay, bx, by = ea[:, 0], ea[:, 1], ea[:, 2], ea[:, 3]
        ex, ey = bx - ax, by - ay
        den = d[0] * ey - d[1] * ex
        with np.errstate(divide="ignore", invalid="ignore"):
            t = ((ax - o[0]) * ey - (ay - o[1]) * ex) / den
            s = ((ax - o[0]) * d[1] - (ay - o[1]) * d[0]) / den
        ok = (np.abs(den) > 1e-9) & (t > 1.0) & (s >= -0.02) & (s <= 1.02)
        ok[list(skip)] = False
        if not ok.any():
            return None
        return float(t[ok].min())

    win_pts = np.array([p for pts, _ in layers["window"] for p in pts] or [(1e9, 1e9)])
    door_pts, long_solid, arc_ends = [], [], []
    for pts, curved in layers["door"]:
        door_pts += pts
        if curved:
            arc_ends += [pts[0], pts[-1]]
        else:
            for p, q in zip(pts, pts[1:]):
                if math.dist(p, q) > 110:
                    long_solid.append(((p[0] + q[0]) / 2, (p[1] + q[1]) / 2))
    door_pts = np.array(door_pts or [(1e9, 1e9)])
    long_solid = np.array(long_solid or [(1e9, 1e9)])
    arc_ends = np.array(arc_ends or [(1e9, 1e9)])

    def inside(pts, o, out, capdir, t, half, pad_s, pad_c):
        rel = pts - np.array(o)
        s = rel @ np.array(out)
        c = rel @ np.array(capdir)
        return int(((s > -pad_s) & (s < t + pad_s) & (np.abs(c) < half + pad_c)).sum())

    gaps = []
    eidx = 0
    for li, loop in enumerate(loops):
        n = len(loop)
        for i in range(n):
            a, b = loop[i], loop[(i + 1) % n]
            p, nx = loop[i - 1], loop[(i + 2) % n]
            this = eidx
            eidx += 1
            clen = math.dist(a, b)
            if not 18 <= clen <= 75:
                continue
            dp, dn, de = norm(sub(a, p)), norm(sub(nx, b)), norm(sub(b, a))
            if dot(dp, dn) > -0.9 or abs(dot(dp, de)) > 0.35:
                continue
            if math.dist(a, p) < 8 or math.dist(nx, b) < 8:
                continue
            out = dp
            mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
            skip = {this, this - 1 if i > 0 else this + n - 1, this + 1 if i < n - 1 else this - n + 1}
            ts = [ray(add(add(mid, mul(de, k * clen * 0.35)), mul(out, 0.5)), out, skip) for k in (-1, 0, 1)]
            if any(t is None for t in ts):
                continue
            t = ts[1]
            if max(ts) - min(ts) > 14 or not 110 <= t <= 1320:
                continue
            half = clen / 2
            n_win = inside(win_pts, mid, out, de, t, half, 4, 10)
            n_door = inside(door_pts, mid, out, de, t, half, 8, 12)
            n_long = inside(long_solid, mid, out, de, t, half, 0, 14)
            n_arc = inside(arc_ends, mid, out, de, t, half, 30, 34)
            if n_win >= 4:
                kind = "window"
            elif n_arc >= 1:
                kind = "door"
            elif n_long >= 2 and t > 300:
                kind = "slider"
            elif n_door >= max(4, t / 25):          # dashed header lines run the whole width
                kind = "cased"
            else:
                continue
            c = add(mid, mul(out, t / 2))
            if any(math.dist(c, g["c"]) < 30 for g in gaps):
                continue
            quad = [a, b, add(b, mul(out, t)), add(a, mul(out, t))]
            pa, pb = add(add(a, mul(out, -4)), mul(de, -2)), add(add(b, mul(out, -4)), mul(de, 2))
            seal = [pa, pb, add(pb, mul(out, t + 8)), add(pa, mul(out, t + 8))]   # overlaps both wall ends
            gaps.append({"kind": kind, "c": c, "quad": quad, "seal": seal, "width": t, "thick": clen,
                         "a": mid, "b": add(mid, mul(out, t))})
    return gaps


# -------------------------------------------------------------------- raster
class Grid:
    def __init__(self, x0, y0, x1, y1):
        self.ox, self.oy = x0, y0
        self.w = int(math.ceil((x1 - x0) / PX))
        self.h = int(math.ceil((y1 - y0) / PX))

    def blank(self, dtype=bool):
        return np.zeros((self.h, self.w), dtype=dtype)

    def cell(self, p):
        return int((p[1] - self.oy) / PX), int((p[0] - self.ox) / PX)

    def fill_poly(self, mask, pts):
        P = [((x - self.ox) / PX, (y - self.oy) / PX) for x, y in pts]
        ys = [p[1] for p in P]
        r0, r1 = max(0, int(math.floor(min(ys)))), min(self.h - 1, int(math.ceil(max(ys))))
        n = len(P)
        for row in range(r0, r1 + 1):
            yc = row + 0.5
            xs = []
            for i in range(n):
                (xa, ya), (xb, yb) = P[i], P[(i + 1) % n]
                if (ya <= yc < yb) or (yb <= yc < ya):
                    xs.append(xa + (yc - ya) * (xb - xa) / (yb - ya))
            xs.sort()
            for a, b in zip(xs[0::2], xs[1::2]):
                c0, c1 = max(0, int(math.ceil(a - 0.5))), min(self.w - 1, int(math.floor(b - 0.5)))
                if c1 >= c0:
                    mask[row, c0:c1 + 1] = True

    def draw_line(self, mask, a, b, radius=1):
        steps = max(2, int(math.dist(a, b) / (PX * 0.5)))
        for k in range(steps + 1):
            u = k / steps
            r, c = self.cell((a[0] + (b[0] - a[0]) * u, a[1] + (b[1] - a[1]) * u))
            mask[max(0, r - radius):r + radius + 1, max(0, c - radius):c + radius + 1] = True

    def rect_m(self, r0, c0, r1, c1, origin):
        """Raster rectangle -> metres, relative to the shared plan origin."""
        return [round((self.ox + c0 * PX - origin[0]) * U2M, 4), round((self.oy + r0 * PX - origin[1]) * U2M, 4),
                round((self.ox + c1 * PX - origin[0]) * U2M, 4), round((self.oy + r1 * PX - origin[1]) * U2M, 4)]


def greedy_rects(mask):
    """Cover a pixel mask with as few rectangles as a simple sweep can manage."""
    m = mask.copy()
    out = []
    for r in range(m.shape[0]):
        cols = np.flatnonzero(m[r])
        while cols.size:
            c0 = int(cols[0])
            c1 = c0
            row = m[r]
            while c1 < m.shape[1] and row[c1]:
                c1 += 1
            r1 = r + 1
            while r1 < m.shape[0] and m[r1, c0:c1].all():
                r1 += 1
            m[r:r1, c0:c1] = False
            out.append((r, c0, r1, c1))
            cols = np.flatnonzero(m[r])
    return out


def shift(a, dr, dc):
    out = np.zeros_like(a)
    h, w = a.shape
    out[max(0, dr):h + min(0, dr), max(0, dc):w + min(0, dc)] = a[max(0, -dr):h + min(0, -dr), max(0, -dc):w + min(0, -dc)]
    return out


def dilate(mask, n):
    m = mask.copy()
    for _ in range(n):
        m = m | shift(m, 1, 0) | shift(m, -1, 0) | shift(m, 0, 1) | shift(m, 0, -1)
    return m


def erode(mask, n):
    return ~dilate(~mask, n)


def grow_square(mask, n):
    """Grow by n cells in every direction, corners included, so right angles stay sharp."""
    m = mask.copy()
    for _ in range(n):
        m = m | shift(m, 0, 1) | shift(m, 0, -1)
        m = m | shift(m, 1, 0) | shift(m, -1, 0)
    return m


def close_square(mask, n):
    """Fill pockets and slots narrower than 2n cells without rounding the outline."""
    return ~grow_square(~grow_square(mask, n), n) | mask


def flood(free, seed, limit):
    h, w = free.shape
    r, c = seed
    if not (0 <= r < h and 0 <= c < w):
        return None
    if not free[r, c]:                              # label sits on a line: look nearby
        found = False
        for rad in range(1, 14):
            for dr in range(-rad, rad + 1):
                for dc in range(-rad, rad + 1):
                    rr, cc = r + dr, c + dc
                    if 0 <= rr < h and 0 <= cc < w and free[rr, cc]:
                        r, c, found = rr, cc, True
                        break
                if found:
                    break
            if found:
                break
        if not found:
            return None
    region = np.zeros_like(free)
    region[r, c] = True
    q = deque([(r, c)])
    count = 1
    while q:
        r, c = q.popleft()
        for rr, cc in ((r + 1, c), (r - 1, c), (r, c + 1), (r, c - 1)):
            if rr < 0 or cc < 0 or rr >= h or cc >= w:
                flood.why = "reached page edge"
                return None
            if free[rr, cc] and not region[rr, cc]:
                region[rr, cc] = True
                count += 1
                if count > limit:
                    rs, cs = np.nonzero(region)
                    flood.why = f"too big; spread rows {rs.min()}-{rs.max()} cols {cs.min()}-{cs.max()} from seed {seed}"
                    return None
                q.append((rr, cc))
    return region


def write_png(path, rgb):
    """Tiny PNG writer so masks can be checked by eye without extra libraries."""
    import struct, zlib
    h, w, _ = rgb.shape
    raw = b"".join(b"\x00" + rgb[r].tobytes() for r in range(h - 1, -1, -1))
    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    Path(path).write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                           + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


def clusters(polys, pad):
    """Group line-work that touches into objects; return each group's bounding box."""
    boxes = []
    for pts, _ in polys:
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        boxes.append([min(xs), min(ys), max(xs), max(ys)])
    parent = list(range(len(boxes)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    order = sorted(range(len(boxes)), key=lambda i: boxes[i][0])
    for ii, i in enumerate(order):
        for j in order[ii + 1:]:
            if boxes[j][0] > boxes[i][2] + pad:
                break
            if boxes[j][1] <= boxes[i][3] + pad and boxes[j][3] >= boxes[i][1] - pad:
                parent[find(j)] = find(i)
    groups = defaultdict(list)
    for i in range(len(boxes)):
        groups[find(i)].append(boxes[i])
    return [[min(b[0] for b in g), min(b[1] for b in g), max(b[2] for b in g), max(b[3] for b in g)] for g in groups.values()]


# ---------------------------------------------------------------------- main
def best_offset(base_pts, other_pts, span=70):
    """Both sheets show the same building, slightly shifted on the page. Find the shift."""
    base = {(round(x), round(y)) for x, y in base_pts}
    other = [(round(x), round(y)) for x, y in other_pts]
    best = (0, 0, -1)
    for dx in range(-span, span + 1):
        hits_x = [(x - dx, y) for x, y in other]
        for dy in range(-span, span + 1):
            n = sum(1 for x, y in hits_x if (x, y - dy) in base)
            if n > best[2]:
                best = (dx, dy, n)
    return best


def process(name, layers, labels, origin, grid):
    def M(p):
        return [round((p[0] - origin[0]) * U2M, 4), round((p[1] - origin[1]) * U2M, 4)]

    loops, bad = wall_loops(layers["wall"])
    gaps = find_gaps(loops, layers)

    wall_mask, gap_mask, rail_mask = grid.blank(), grid.blank(), grid.blank()
    for loop in loops:
        grid.fill_poly(wall_mask, loop)
    for g in gaps:
        grid.fill_poly(gap_mask, g["seal"])

    railings = []                                   # long solid lines on the door layer = balcony rails
    for pts, curved in layers["door"]:
        length = sum(math.dist(p, q) for p, q in zip(pts, pts[1:]))
        if curved:
            if length > 420:                        # big arcs are porch rails; small ones are door swings
                railings.append(pts)
            continue
        for p, q in zip(pts, pts[1:]):
            if math.dist(p, q) >= 300:
                r, c = grid.cell(((p[0] + q[0]) / 2, (p[1] + q[1]) / 2))
                if not gap_mask[r, c] and not wall_mask[r, c]:
                    railings.append([p, q])
    deck_edges = [pts for pts, _ in layers["slab"] if sum(math.dist(p, q) for p, q in zip(pts, pts[1:])) > 600]
    for pts in railings + deck_edges:
        for p, q in zip(pts, pts[1:]):
            grid.draw_line(rail_mask, p, q)
    stair_boxes = [b for b in clusters(layers["stair"], 10) if (b[2] - b[0]) * (b[3] - b[1]) > 200 * 200]

    solid = wall_mask | gap_mask
    barrier = grow_square(solid | rail_mask, 1)     # one extra cell seals diagonal pinholes
    free = ~barrier
    claimed = grid.blank(np.int16)
    rooms = []
    order = sorted(labels, key=lambda l: (l["name"] in ("OPEN DECK", "HALL"), l["name"] == "STAIRWELL"))
    for lab in order:
        cx, cy = lab["u"]
        expect = (lab["w_ft"] * lab["d_ft"] * U_PER_FT ** 2 / PX ** 2) if lab["w_ft"] and lab["d_ft"] else None
        region, how = None, "flood"
        if lab["name"] == "STAIRWELL" and stair_boxes:
            b = min(stair_boxes, key=lambda b: math.hypot((b[0] + b[2]) / 2 - cx, (b[1] + b[3]) / 2 - cy))
            region = grid.blank()
            grid.fill_poly(region, [(b[0], b[1]), (b[2], b[1]), (b[2], b[3]), (b[0], b[3])])
            how = "stair drawing"
        elif lab["name"] == "OPEN DECK" and deck_edges:
            half = (lab["w_ft"] or 60) * U_PER_FT / 2 + 4 / U2M
            front = sorted(p for pts in deck_edges if all(q[1] < cy + 4 / U2M for q in pts) and max(q[0] for q in pts) > cx - half
                           for p in pts)
            if len(front) >= 2:
                top = cy + 3.2 / U2M
                region = grid.blank()
                grid.fill_poly(region, front + [(front[-1][0], top), (front[0][0], top)])
                how = "deck edge"
        if region is None:
            limit = int(expect * 1.9) if expect else int(40 * U_PER_FT ** 2 / PX ** 2 * 10)
            region = flood(free & (claimed == 0), grid.cell(lab["u"]), limit)
            if region is None or (expect and region.sum() < expect * 0.45):
                print(f"   leak: {name} {lab['name']} at {M(lab['u'])} -> using printed size")
                region = grid.blank()
                w = (lab["w_ft"] or 6) * U_PER_FT / 2
                d = (lab["d_ft"] or 6) * U_PER_FT / 2
                grid.fill_poly(region, [(cx - w, cy - d), (cx + w, cy - d), (cx + w, cy + d), (cx - w, cy + d)])
                how = "printed size"
        region &= ~solid & (claimed == 0)
        claimed[region] = len(rooms) + 1
        rooms.append({"name": lab["name"], "w_ft": lab["w_ft"], "d_ft": lab["d_ft"], "label": M(lab["u"]), "source": how})

    net = [float((claimed == i + 1).sum()) * (PX * U2M) ** 2 for i in range(len(rooms))]
    allowed = grow_square(solid, 1)
    for _ in range(6):                              # let each floor tuck under its walls
        for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            sh = shift(claimed, dr, dc)
            grow = (claimed == 0) & allowed & (sh > 0)
            claimed[grow] = sh[grow]

    for i, room in enumerate(rooms):
        mask = claimed == i + 1
        rr, cc = np.nonzero(mask)
        room["area_m2"] = round(net[i], 2)
        if rr.size == 0:
            room.update(rects=[], bbox=[0, 0, 0, 0])
            continue
        r0, r1, c0, c1 = rr.min(), rr.max() + 1, cc.min(), cc.max() + 1
        room["rects"] = [grid.rect_m(r0 + a, c0 + b, r0 + c, c0 + d, origin) for a, b, c, d in greedy_rects(mask[r0:r1, c0:c1])]
        room["bbox"] = grid.rect_m(r0, c0, r1, c1, origin)

    footprint = (claimed > 0) | solid
    enclosed, stair = grid.blank(), grid.blank()
    for i, room in enumerate(rooms):
        if room["name"] not in OPEN_AIR:
            enclosed |= claimed == i + 1
    for b in stair_boxes:
        grid.fill_poly(stair, [(b[0], b[1]), (b[2], b[1]), (b[2], b[3]), (b[0], b[3])])

    cab = grid.blank()
    for pts, _ in layers["cabfill"]:
        if len(pts) >= 3:
            grid.fill_poly(cab, pts[:-1] if pts[0] == pts[-1] else pts)
    cab &= ~solid
    fixtures = []
    for box in clusters(layers["fixture"], 6):
        w, h = box[2] - box[0], box[3] - box[1]
        if max(w, h) < 60:
            continue
        r, c = grid.cell(((box[0] + box[2]) / 2, (box[1] + box[3]) / 2))
        on_counter = bool(cab[max(0, r - 2):r + 3, max(0, c - 2):c + 3].any())
        kind = "sink" if on_counter else ("tub" if max(w, h) > 255 else "toilet")
        fixtures.append({"kind": kind, "box": M(box[:2]) + M(box[2:])})

    if DEBUG_DIR:
        img = np.full(claimed.shape + (3,), 255, np.uint8)
        pal = np.array([[(37 * i) % 120 + 135, (91 * i) % 120 + 135, (53 * i) % 120 + 135] for i in range(64)], np.uint8)
        img[claimed > 0] = pal[claimed[claimed > 0] % 64]
        img[rail_mask] = (0, 170, 0)
        img[gap_mask] = (255, 120, 0)
        img[wall_mask] = (0, 0, 0)
        write_png(Path(DEBUG_DIR) / f"mask-{name}.png", img)

    return {
        "name": name,
        "walls": [[M(p) for p in loop] for loop in loops],
        "openings": [{"kind": g["kind"], "quad": [M(p) for p in g["quad"]], "a": M(g["a"]), "b": M(g["b"]),
                      "width": round(g["width"] * U2M, 3), "thick": round(g["thick"] * U2M, 3)} for g in gaps],
        "rooms": rooms,
        "cabinets": [grid.rect_m(*r, origin) for r in greedy_rects(cab)],
        "fixtures": fixtures,
        "stairs": [M(b[:2]) + M(b[2:]) for b in stair_boxes],
        "railings": [[M(p) for p in pts] for pts in railings],
        "deck_edges": [[M(p) for p in pts] for pts in deck_edges],
        "_masks": {"footprint": footprint, "enclosed": enclosed, "stair": stair, "solid": solid, "claimed": claimed > 0},
    }


def main():
    CACHE.mkdir(parents=True, exist_ok=True)
    raw = {}
    for name, pdf in LEVELS:
        svg = CACHE / f"{name}.svg"
        subprocess.run(["pdftocairo", "-svg", str(pdf), str(svg)], check=True)
        raw[name] = (load_layers(svg), load_labels(pdf))

    g_pts = [p for pts, _ in raw["ground"][0]["wall"] for p in pts]
    f_pts = [p for pts, _ in raw["first"][0]["wall"] for p in pts]
    dx, dy, hits = best_offset(g_pts, f_pts)
    print(f"first floor sits ({dx}, {dy}) units off the ground sheet; {hits} wall points line up")
    layers_f, labels_f = raw["first"]
    for key in layers_f:
        layers_f[key] = [([(x - dx, y - dy) for x, y in pts], c) for pts, c in layers_f[key]]
    for lab in labels_f:
        lab["u"] = (lab["u"][0] - dx, lab["u"][1] - dy)

    allp = g_pts + [(x - dx, y - dy) for x, y in f_pts]
    xs, ys = [p[0] for p in allp], [p[1] for p in allp]
    origin = (min(xs), min(ys))
    grid = Grid(min(xs) - 500, min(ys) - 900, max(xs) + 500, max(ys) + 700)

    levels = {name: process(name, raw[name][0], raw[name][1], origin, grid) for name, _ in LEVELS}
    g, f = levels["ground"]["_masks"], levels["first"]["_masks"]
    rects = lambda mask: [grid.rect_m(*r, origin) for r in greedy_rects(mask)]

    # Floor plates. The first-floor plate also roofs the ground floor, minus the stair openings.
    plate_g = close_square(grow_square(g["footprint"], 3), 30)
    plate_f = close_square(grow_square(f["footprint"] | g["footprint"], 3), 30) & ~erode(f["stair"], 3)
    levels["ground"]["slab"] = rects(plate_g)
    levels["first"]["slab"] = rects(plate_f)
    # Whatever the plate covers that no labelled room claimed is shared circulation.
    for lv, plate, m in ((levels["ground"], plate_g, g), (levels["first"], plate_f, f)):
        spare = erode(plate & ~m["claimed"] & ~m["solid"] & ~m["stair"], 2)
        spare = grow_square(spare, 2) & plate & ~m["claimed"] & ~m["stair"]
        area = float((spare & ~m["solid"]).sum()) * (PX * U2M) ** 2
        if area > 1.0:
            rr, cc = np.nonzero(spare)
            lv["rooms"].append({"name": "WALKWAY", "w_ft": None, "d_ft": None, "source": "leftover floor", "area_m2": round(area, 2),
                                "label": [round(float((grid.ox + cc.mean() * PX - origin[0]) * U2M), 3),
                                          round(float((grid.oy + rr.mean() * PX - origin[1]) * U2M), 3)],
                                "rects": rects(spare), "bbox": grid.rect_m(rr.min(), cc.min(), rr.max() + 1, cc.max() + 1, origin)})
    roof = grow_square(f["enclosed"], 12)
    levels["first"]["roof"] = rects(roof)
    levels["first"]["parapet"] = rects(roof & ~grow_square(~roof, 9))
    levels["ground"]["roof"], levels["ground"]["parapet"] = [], []

    units = json.loads((ROOT / "build" / "units.json").read_text())["units"]
    for lv in levels.values():
        lv.pop("_masks")
        lv["rooms"] = [r for r in lv["rooms"] if r["area_m2"] >= 0.6]
        for r in lv["rooms"]:
            x, y = r["label"]
            r["unit"] = next((u["id"] for u in units if u["level"] == lv["name"] and r["name"] not in ("STAIRWELL", "WALKWAY")
                              and any(b[0] <= x <= b[2] and b[1] <= y <= b[3] for b in u["boxes"])), None)
        kinds = defaultdict(int)
        for o in lv["openings"]:
            kinds[o["kind"]] += 1
        print(f"{lv['name']}: {len(lv['walls'])} wall outlines, openings {dict(kinds)}, {len(lv['rooms'])} rooms, "
              f"{len(lv['cabinets'])} counter rects, {len(lv['fixtures'])} fixtures, {len(lv['stairs'])} stairs, "
              f"{len(lv['railings'])} railings, slab {len(lv['slab'])} rects")
        for r in lv["rooms"]:
            want = (r["w_ft"] * r["d_ft"] * 0.0929) if r["w_ft"] else 0
            note = "" if r["source"] == "flood" else f"  <- {r['source']}"
            print(f"   {r['unit'] or '--':3s} {r['name']:10s} at {r['label']}  drawn {want:6.1f} m2  found {r['area_m2']:6.1f} m2{note}")

    extent = [round((max(xs) - origin[0]) * U2M, 3), round((max(ys) - origin[1]) * U2M, 3)]
    for u in units:
        mine = [r for lv in levels.values() if lv["name"] == u["level"] for r in lv["rooms"] if r["unit"] == u["id"]]
        u["area_m2"] = round(sum(r["area_m2"] for r in mine), 1)
        u["rooms"] = [r["name"].title() for r in mine]
        print(f"{u['id']} {u['name']} ({u['type']}): {u['area_m2']} m2 = {round(u['area_m2'] * 10.764)} sq ft; {', '.join(u['rooms'])}")
    out = {"units": "metres", "extent": extent, "apartments": units, "levels": [levels[n] for n, _ in LEVELS]}
    (ROOT / "build" / "plan.json").write_text(json.dumps(out))
    print("extent (m)", extent, "->", ROOT / "build" / "plan.json")


if __name__ == "__main__":
    main()
