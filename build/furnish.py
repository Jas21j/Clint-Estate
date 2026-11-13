"""Furniture rules: which pieces go in which room, and where.

Pieces come from the Omereta home kit (home_models.blend). In that file every piece is a
collection named HM_<id>, measured in studs, standing on the floor with its front facing -Y
and its back (headboard, sofa back) on +Y.

Placement is rule based: push a piece against a wall, keep it out of walls, counters,
fixtures and door swings, and score the options. Tune ROOM_PLANS or the scoring to taste.
"""
import math

import bpy
from mathutils import Matrix, Vector

STUD = 0.28                 # metres per stud
DOOR_CLEAR = 0.85           # keep this much floor free either side of a doorway
FLOOR_LIFT = 0.014

# What each kind of room gets. The engine skips anything that does not fit.
ROOM_PLANS = {
    "LIVING": ["sofa", "coffee", "rug", "tv", "armchair", "dining", "fridge", "palm"],
    "BEDROOM": ["bed", "nightstands", "dresser", "plant"],
    "BEDROOM 2": ["bed", "nightstands", "dresser", "plant"],
    "BALCONY": ["bench", "plant"],
    "ENTRY": ["plant"],
}


# ------------------------------------------------------------------ geometry
def _seg_dist(p, a, b):
    ax, ay, bx, by = a[0], a[1], b[0], b[1]
    dx, dy = bx - ax, by - ay
    l2 = dx * dx + dy * dy
    t = 0 if l2 == 0 else max(0, min(1, ((p[0] - ax) * dx + (p[1] - ay) * dy) / l2))
    return math.hypot(p[0] - ax - t * dx, p[1] - ay - t * dy)


def _inside(poly, p):
    x, y, hit = p[0], p[1], False
    n = len(poly)
    for i in range(n):
        (x1, y1), (x2, y2) = poly[i], poly[(i + 1) % n]
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            hit = not hit
    return hit


def wall_distance(lv, p):
    """Distance from a plan point to the nearest wall face (0 when inside a wall)."""
    best = 1e9
    for loop in lv["walls"]:
        if _inside(loop, p):
            return 0.0
        for i in range(len(loop)):
            best = min(best, _seg_dist(p, loop[i], loop[(i + 1) % len(loop)]))
    return best


def _bbox(pts):
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return (min(xs), min(ys), max(xs), max(ys))


def _overlap(a, b, m=0.0):
    return a[0] < b[2] + m and a[2] > b[0] - m and a[1] < b[3] + m and a[3] > b[1] - m


# ----------------------------------------------------------------------- kit
def load_kit(path):
    with bpy.data.libraries.load(str(path), link=False) as (src, dst):
        dst.collections = [n for n in src.collections if n.startswith("HM_")]
    kit = {"_collections": dst.collections}
    for col in dst.collections:
        objs = [o for o in col.objects if o.type == "MESH"]
        if not objs:
            continue
        origin = objs[0].location.copy()
        lo, hi = Vector((1e9, 1e9, 1e9)), Vector((-1e9, -1e9, -1e9))
        for o in objs:
            for c in o.bound_box:
                w = o.matrix_basis @ Vector(c) - origin
                lo = Vector((min(lo[i], w[i]) for i in range(3)))
                hi = Vector((max(hi[i], w[i]) for i in range(3)))
        kit[col.name[3:]] = {"objs": objs, "origin": origin, "lo": lo * STUD, "hi": hi * STUD}
    return kit


def discard_kit(kit):
    for col in kit["_collections"]:
        for o in list(col.objects):
            bpy.data.objects.remove(o)
        bpy.data.collections.remove(col)


def _spawn(kit, piece_id, x, y, z, rot_deg, parent, label, props):
    piece = kit[piece_id]
    holder = bpy.data.objects.new(label, None)
    bpy.context.scene.collection.objects.link(holder)
    holder.parent = parent
    holder.location = (x, y, z)
    holder.rotation_euler = (0, 0, math.radians(rot_deg))
    holder.scale = (STUD, STUD, STUD)
    for k, v in props.items():
        holder[k] = v
    shift = Matrix.Translation(-piece["origin"])
    for o in piece["objs"]:
        child = bpy.data.objects.new(f"{label}.{o.name.split('__', 1)[-1]}", o.data)   # shares the mesh
        bpy.context.scene.collection.objects.link(child)
        child.parent = holder
        child.matrix_basis = shift @ o.matrix_basis
    return holder


# -------------------------------------------------------------------- engine
SIDES = {                    # wall side: (direction the piece faces, rotation in degrees)
    "S": ((0, 1), 180), "N": ((0, -1), 0), "W": ((1, 0), 90), "E": ((-1, 0), -90),
}


class Level:
    def __init__(self, lv, z, kit, holder):
        self.lv, self.z, self.kit, self.holder, self.count = lv, z, kit, holder, 0
        self.solids = [(loop, _bbox(loop)) for loop in lv["walls"]]
        self.solids += [(o["quad"], _bbox(o["quad"])) for o in lv["openings"]]
        self.blocked = [tuple(r) for r in lv["cabinets"]] + [tuple(f["box"]) for f in lv["fixtures"]]
        self.blocked += [tuple(b) for b in lv["stairs"]]
        self.window_zones, self.doors = [], []
        for o in lv["openings"]:
            x0, y0, x1, y1 = _bbox(o["quad"])
            horizontal = abs(o["b"][0] - o["a"][0]) > abs(o["b"][1] - o["a"][1])
            pad = (0.05, DOOR_CLEAR) if horizontal else (DOOR_CLEAR, 0.05)
            if o["kind"] == "window":
                pad = (0.0, 0.45) if horizontal else (0.45, 0.0)
                self.window_zones.append((x0 - pad[0], y0 - pad[1], x1 + pad[0], y1 + pad[1]))
            else:
                self.blocked.append((x0 - pad[0], y0 - pad[1], x1 + pad[0], y1 + pad[1]))
                self.doors.append(((x0 + x1) / 2, (y0 + y1) / 2))

    def size(self, piece_id, rot):
        p = self.kit[piece_id]
        w, d = p["hi"].x - p["lo"].x, p["hi"].y - p["lo"].y
        return (d, w) if rot in (90, -90) else (w, d)

    def in_wall(self, rect):
        x0, y0, x1, y1 = rect
        pts = [(x0, y0), (x1, y0), (x1, y1), (x0, y1), ((x0 + x1) / 2, (y0 + y1) / 2),
               ((x0 + x1) / 2, y0), ((x0 + x1) / 2, y1), (x0, (y0 + y1) / 2), (x1, (y0 + y1) / 2)]
        for poly, bb in self.solids:
            if _overlap(rect, bb) and any(_inside(poly, p) for p in pts):
                return True
        return False

    def in_room(self, room, rect):
        x0, y0, x1, y1 = rect
        nx, ny = max(2, int((x1 - x0) / 0.25) + 1), max(2, int((y1 - y0) / 0.25) + 1)
        for i in range(nx + 1):
            for j in range(ny + 1):
                px, py = x0 + (x1 - x0) * i / nx, y0 + (y1 - y0) * j / ny
                if not any(r[0] - 1e-6 <= px <= r[2] + 1e-6 and r[1] - 1e-6 <= py <= r[3] + 1e-6 for r in room["rects"]):
                    return False
        return True

    def fits(self, room, rect, tall=False, margin=0.04):
        if not self.in_room(room, rect) or self.in_wall(rect):
            return False
        if any(_overlap(rect, b, margin) for b in self.blocked):
            return False
        return not (tall and any(_overlap(rect, b) for b in self.window_zones))

    def against_walls(self, room, piece_id, tall=False):
        """Every spot where the piece can stand with its back on a wall of this room."""
        bx0, by0, bx1, by1 = room["bbox"]
        out = []
        for side, (front, rot) in SIDES.items():
            w, d = self.size(piece_id, rot)
            horizontal = side in "SN"
            lo, hi = (bx0, bx1) if horizontal else (by0, by1)
            steps = int((hi - lo - w if horizontal else hi - lo - d) / 0.2)
            for k in range(steps + 1):
                along = lo + (w if horizontal else d) / 2 + k * 0.2
                for inset in [0.02 + 0.1 * n for n in range(36)]:
                    if side == "S":
                        cx, cy = along, by0 + inset + d / 2
                    elif side == "N":
                        cx, cy = along, by1 - inset - d / 2
                    elif side == "W":
                        cx, cy = bx0 + inset + w / 2, along
                    else:
                        cx, cy = bx1 - inset - w / 2, along
                    rect = (cx - w / 2, cy - d / 2, cx + w / 2, cy + d / 2)
                    if not self.fits(room, rect, tall):
                        continue
                    back = (rect[0] - front[0] * 0.14, rect[1] - front[1] * 0.14, rect[2] - front[0] * 0.14, rect[3] - front[1] * 0.14)
                    if self.in_wall(back):          # really touching a wall, not floating mid-room
                        out.append({"c": (cx, cy), "rot": rot, "front": front, "rect": rect, "side": side,
                                    "off_centre": abs(along - (lo + hi) / 2), "span": hi - lo,
                                    "window": any(_overlap(rect, z) for z in self.window_zones)})
                    break
        return out

    def door_distance(self, room, p):
        bx0, by0, bx1, by1 = room["bbox"]
        near = [d for d in self.doors if bx0 - 0.4 <= d[0] <= bx1 + 0.4 and by0 - 0.4 <= d[1] <= by1 + 0.4]
        return min((math.dist(p, d) for d in near), default=3.0)

    def put(self, room, piece_id, c, rot, block=True, lift=0.0):
        p = self.kit[piece_id]
        r = math.radians(rot)
        lx, ly = (p["lo"].x + p["hi"].x) / 2, (p["lo"].y + p["hi"].y) / 2    # piece centre vs its origin
        ox, oy = lx * math.cos(r) - ly * math.sin(r), lx * math.sin(r) + ly * math.cos(r)
        self.count += 1
        _spawn(self.kit, piece_id, c[0] - ox, c[1] - oy, self.z + FLOOR_LIFT + lift - p["lo"].z, rot, self.holder,
               f"Furn_{room.get('unit') or 'Common'}_{piece_id}_{self.count}",
               {"kind": "furniture", "piece": piece_id, "unit": room.get("unit") or "", "room": room["name"].title()})
        w, d = self.size(piece_id, rot)
        rect = (c[0] - w / 2, c[1] - d / 2, c[0] + w / 2, c[1] + d / 2)
        if block:
            self.blocked.append(rect)
        return rect

    def try_put(self, room, piece_id, c, rot, tall=False):
        w, d = self.size(piece_id, rot)
        rect = (c[0] - w / 2, c[1] - d / 2, c[0] + w / 2, c[1] + d / 2)
        if self.fits(room, rect, tall):
            return self.put(room, piece_id, c, rot)
        return None


def _rot_facing(v):
    """Rotation that makes a piece's front (-Y) point along v."""
    return round(math.degrees(math.atan2(v[0], -v[1])) / 90) * 90


# --------------------------------------------------------------------- rooms
def furnish_bedroom(L, room):
    big = room["area_m2"] >= 20 and min(room["bbox"][2] - room["bbox"][0], room["bbox"][3] - room["bbox"][1]) >= 3.8
    for bed in (["bed_king", "bed_double"] if big else ["bed_double", "bed_single"]):
        spots = L.against_walls(room, bed)
        if spots:
            break
    else:
        return
    best = max(spots, key=lambda s: -1.2 * s["off_centre"] + 0.12 * s["span"] - 1.0 * s["window"] + 0.3 * L.door_distance(room, s["c"]))
    L.put(room, bed, best["c"], best["rot"])
    fx, fy = best["front"]
    w, d = L.size(bed, best["rot"])
    side_axis = (-fy, fx)                           # along the headboard wall
    bed_w = w if best["side"] in "SN" else d
    bed_d = d if best["side"] in "SN" else w
    nw, nd = L.size("nightstand", best["rot"])
    n_w = nw if best["side"] in "SN" else nd
    n_d = nd if best["side"] in "SN" else nw
    for sgn in (-1, 1):
        off = sgn * (bed_w / 2 + n_w / 2 + 0.06)
        back = -(bed_d / 2 - n_d / 2)
        L.try_put(room, "nightstand", (best["c"][0] + side_axis[0] * off + fx * back, best["c"][1] + side_axis[1] * off + fy * back), best["rot"])
    spots = [s for s in L.against_walls(room, "dresser", tall=False) if s["side"] != best["side"]]
    if spots:
        s = max(spots, key=lambda s: -0.8 * s["off_centre"] - 1.5 * s["window"] + 0.2 * L.door_distance(room, s["c"]))
        L.put(room, "dresser", s["c"], s["rot"])
    _corner(L, room, "plant_pot")


def furnish_living(L, room):
    bx0, by0, bx1, by1 = room["bbox"]
    cabs = [r for r in L.lv["cabinets"] if _overlap(r, room["bbox"])]
    kitchen = ((sum(r[0] + r[2] for r in cabs) / (2 * len(cabs)), sum(r[1] + r[3] for r in cabs) / (2 * len(cabs))) if cabs else None)
    sofa = "sofa3" if min(bx1 - bx0, by1 - by0) >= 3.3 else "sofa2"
    spots = L.against_walls(room, sofa)
    seat = None
    if spots:
        def score(s):
            away = min(math.dist(s["c"], kitchen), 5.0) if kitchen else 0
            return -0.6 * s["off_centre"] + 0.7 * away - 0.6 * s["window"] + 0.15 * L.door_distance(room, s["c"])
        seat = max(spots, key=score)
        L.put(room, sofa, seat["c"], seat["rot"])
        fx, fy = seat["front"]
        sw, sd = L.size(sofa, seat["rot"])
        depth = sd if seat["side"] in "SN" else sw
        cw, cd = L.size("table_coffee", seat["rot"])
        c_depth = cd if seat["side"] in "SN" else cw
        reach = depth / 2 + 0.45 + c_depth / 2
        table_c = (seat["c"][0] + fx * reach, seat["c"][1] + fy * reach)
        rug = "rug_small"
        rw, rd = L.size(rug, seat["rot"] + 90)
        if L.in_room(room, (table_c[0] - rw / 2, table_c[1] - rd / 2, table_c[0] + rw / 2, table_c[1] + rd / 2)):
            L.put(room, rug, table_c, seat["rot"] + 90, block=False, lift=-0.004)
        L.try_put(room, "table_coffee", table_c, seat["rot"])
        for dist in [4.4 - 0.1 * n for n in range(26)]:          # TV on the far side, facing the sofa
            c = (seat["c"][0] + fx * dist, seat["c"][1] + fy * dist)
            rot = _rot_facing((-fx, -fy))
            w, d = L.size("tv_stand", rot)
            rect = (c[0] - w / 2, c[1] - d / 2, c[0] + w / 2, c[1] + d / 2)
            if L.fits(room, rect):
                L.put(room, "tv_stand", c, rot)
                stand_top = L.kit["tv_stand"]["hi"].z
                L.put(room, "tv_wall", c, rot, block=False, lift=stand_top + 0.06)
                break
        side_axis = (-fy, fx)
        for sgn in (1, -1):                         # one armchair, angled in from the side
            c = (table_c[0] + side_axis[0] * sgn * 1.55, table_c[1] + side_axis[1] * sgn * 1.55)
            if L.try_put(room, "armchair", c, _rot_facing((-side_axis[0] * sgn, -side_axis[1] * sgn))):
                break
    if kitchen and room["area_m2"] >= 17:
        _dining(L, room, kitchen)
    if kitchen:
        spots = [s for s in L.against_walls(room, "fridge", tall=True) if math.dist(s["c"], kitchen) < 3.2]
        if spots:
            s = min(spots, key=lambda s: math.dist(s["c"], kitchen))
            L.put(room, "fridge", s["c"], s["rot"])
    _corner(L, room, "plant_palm")


def _dining(L, room, kitchen):
    bx0, by0, bx1, by1 = room["bbox"]
    best = None
    for rot in (0, 90):
        tw, td = L.size("table_dining4", rot)
        fw, fd = (tw, td + 1.2) if rot == 0 else (tw + 1.2, td)     # table plus chairs pulled out
        x = bx0 + fw / 2
        while x <= bx1 - fw / 2:
            y = by0 + fd / 2
            while y <= by1 - fd / 2:
                rect = (x - fw / 2, y - fd / 2, x + fw / 2, y + fd / 2)
                if L.fits(room, rect, margin=0.3):
                    score = -math.dist((x, y), kitchen)
                    if best is None or score > best[0]:
                        best = (score, (x, y), rot)
                y += 0.25
            x += 0.25
    if not best:
        return
    _, c, rot = best
    L.put(room, "table_dining4", c, rot)
    tw, td = L.size("table_dining4", rot)
    for sgn in (-1, 1):
        for k in (-1, 1):
            if rot == 0:
                pos, face = (c[0] + k * tw * 0.24, c[1] + sgn * (td / 2 + 0.18)), (0, -sgn)
            else:
                pos, face = (c[0] + sgn * (tw / 2 + 0.18), c[1] + k * td * 0.24), (-sgn, 0)
            L.put(room, "chair_dining", pos, _rot_facing(face))


def _corner(L, room, piece_id):
    bx0, by0, bx1, by1 = room["bbox"]
    w, d = L.size(piece_id, 0)
    best = None
    for cx, cy in ((bx0, by0), (bx1, by0), (bx1, by1), (bx0, by1)):
        for inset in (0.18, 0.3, 0.45, 0.6):
            c = (cx + (inset + w / 2) * (1 if cx == bx0 else -1), cy + (inset + d / 2) * (1 if cy == by0 else -1))
            rect = (c[0] - w / 2, c[1] - d / 2, c[0] + w / 2, c[1] + d / 2)
            if L.fits(room, rect, tall=True):
                score = L.door_distance(room, c)
                if best is None or score > best[0]:
                    best = (score, c)
                break
    if best:
        L.put(room, piece_id, best[1], 0)


def furnish_outdoor(L, room, bench=True):
    if bench and room["area_m2"] >= 4.5:
        spots = L.against_walls(room, "bench")
        if spots:
            s = max(spots, key=lambda s: -s["off_centre"])
            L.put(room, "bench", s["c"], s["rot"])
    _corner(L, room, "plant_pot")


def furnish_level(lv, z, kit, holder):
    L = Level(lv, z, kit, holder)
    for room in lv["rooms"]:
        if not room.get("unit") or not room["rects"]:
            continue
        if room["name"] in ("BEDROOM", "BEDROOM 2"):
            furnish_bedroom(L, room)
        elif room["name"] == "LIVING":
            furnish_living(L, room)
        elif room["name"] == "BALCONY":
            furnish_outdoor(L, room)
        elif room["name"] == "ENTRY":
            furnish_outdoor(L, room, bench=False)
    return L.count
