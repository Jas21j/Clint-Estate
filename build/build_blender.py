"""Build the 3D building from build/plan.json and export it for the web viewer.

Run headless:
  /Applications/Blender.app/Contents/MacOS/Blender -b --factory-startup --python build/build_blender.py

Writes:
  build/clint-building.blend   editable Blender scene (one group per floor)
  web/assets/clint.glb         the same model for the browser
  build/cache/preview-*.png    quick check renders

Everything vertical is an assumption (the plans carry no heights). Change HEIGHTS and re-run.
"""
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "build"))
import furnish  # noqa: E402  (furniture rules live in build/furnish.py)

PLAN = json.loads((ROOT / "build" / "plan.json").read_text())
FURNITURE_BLEND = Path.home() / "Desktop/Omereta/blender/home_models.blend"

HEIGHTS = {
    "ceiling": 2.75,      # floor to underside of the slab above (about 9 ft)
    "slab": 0.20,         # floor plate thickness
    "sill": 0.90,         # window sill
    "sill_small": 1.35,   # narrow (bathroom) windows sit higher
    "head": 2.10,         # top of windows and doors
    "parapet": 0.75,      # roof edge upstand
    "counter": 0.90,
    "rail": 1.05,
}
STOREY = HEIGHTS["ceiling"] + HEIGHTS["slab"]
LEVEL_Z = {"ground": 0.0, "first": STOREY}

COLORS = {                 # name: (r, g, b, alpha, roughness, metallic)
    "Wall": (0.93, 0.91, 0.87, 1, 0.9, 0),
    "WallTop": (0.16, 0.17, 0.19, 1, 0.9, 0),
    "Slab": (0.74, 0.73, 0.70, 1, 0.9, 0),
    "Roof": (0.62, 0.62, 0.60, 1, 0.9, 0),
    "Glass": (0.62, 0.80, 0.86, 0.28, 0.08, 0),
    "Frame": (0.13, 0.14, 0.16, 1, 0.5, 0.6),
    "FloorWood": (0.66, 0.50, 0.35, 1, 0.6, 0),
    "FloorTile": (0.84, 0.85, 0.84, 1, 0.35, 0),
    "FloorStone": (0.70, 0.68, 0.63, 1, 0.85, 0),
    "FloorConcrete": (0.60, 0.60, 0.59, 1, 0.9, 0),
    "Cabinet": (0.20, 0.25, 0.30, 1, 0.55, 0),
    "Counter": (0.90, 0.89, 0.86, 1, 0.3, 0),
    "Porcelain": (0.97, 0.97, 0.96, 1, 0.15, 0),
    "Basin": (0.30, 0.34, 0.38, 1, 0.2, 0.3),
    "Stair": (0.55, 0.55, 0.54, 1, 0.8, 0),
    "Lawn": (0.36, 0.47, 0.27, 1, 1.0, 0),
    "Paving": (0.66, 0.64, 0.60, 1, 0.9, 0),
}
FLOOR_FOR = {"LIVING": "FloorWood", "BEDROOM": "FloorWood", "BEDROOM 2": "FloorWood", "CLOSET": "FloorWood",
             "BATH": "FloorTile", "LAUNDRY": "FloorTile", "BALCONY": "FloorStone", "ENTRY": "FloorStone",
             "OPEN DECK": "FloorStone", "HALL": "FloorStone", "WALKWAY": "FloorStone", "CAR PORT": "FloorConcrete",
             "STAIRWELL": "FloorConcrete"}


# ------------------------------------------------------------------ helpers
def material(name):
    mat = bpy.data.materials.get(name)
    if mat:
        return mat
    r, g, b, a, rough, metal = COLORS[name]
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (r, g, b, 1)
    bsdf.inputs["Roughness"].default_value = rough
    bsdf.inputs["Metallic"].default_value = metal
    bsdf.inputs["Alpha"].default_value = a
    mat.diffuse_color = (r, g, b, a)
    if a < 1:
        mat.blend_method = "BLEND"
    return mat


class Mesh:
    """Collects boxes and extruded outlines, then becomes one Blender object."""

    def __init__(self, name):
        self.name, self.verts, self.faces, self.face_mats, self.mats = name, [], [], [], []

    def _mat(self, name):
        if name not in self.mats:
            self.mats.append(name)
        return self.mats.index(name)

    def prism(self, pts, z0, z1, mat, top=None):
        """Extrude a flat outline (counter-clockwise, may be L or T shaped) from z0 up to z1."""
        n, base = len(pts), len(self.verts)
        self.verts += [(x, y, z0) for x, y in pts] + [(x, y, z1) for x, y in pts]
        self.faces.append([base + i for i in reversed(range(n))])
        self.face_mats.append(self._mat(mat))
        self.faces.append([base + n + i for i in range(n)])
        self.face_mats.append(self._mat(top or mat))
        for i in range(n):
            j = (i + 1) % n
            self.faces.append([base + i, base + j, base + n + j, base + n + i])
            self.face_mats.append(self._mat(mat))

    def box(self, x0, y0, x1, y1, z0, z1, mat, top=None):
        self.prism([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], z0, z1, mat, top)

    def flat(self, x0, y0, x1, y1, z, mat):
        base = len(self.verts)
        self.verts += [(x0, y0, z), (x1, y0, z), (x1, y1, z), (x0, y1, z)]
        self.faces.append([base, base + 1, base + 2, base + 3])
        self.face_mats.append(self._mat(mat))

    def build(self, parent, props=None):
        if not self.faces:
            return None
        me = bpy.data.meshes.new(self.name)
        me.from_pydata(self.verts, [], self.faces)
        for name in self.mats:
            me.materials.append(material(name))
        me.polygons.foreach_set("material_index", self.face_mats)
        me.update()
        ob = bpy.data.objects.new(self.name, me)
        bpy.context.scene.collection.objects.link(ob)
        ob.parent = parent
        for k, v in (props or {}).items():
            ob[k] = v
        return ob


def empty(name, parent=None, props=None):
    ob = bpy.data.objects.new(name, None)
    bpy.context.scene.collection.objects.link(ob)
    ob.parent = parent
    for k, v in (props or {}).items():
        ob[k] = v
    return ob


def ccw(pts):
    area = sum(pts[i][0] * pts[(i + 1) % len(pts)][1] - pts[(i + 1) % len(pts)][0] * pts[i][1] for i in range(len(pts)))
    return pts if area > 0 else pts[::-1]


def strip(a, b, thick):
    """A thin rectangle in plan running from a to b."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    n = math.hypot(dx, dy) or 1
    px, py = -dy / n * thick / 2, dx / n * thick / 2
    return ccw([(a[0] + px, a[1] + py), (b[0] + px, b[1] + py), (b[0] - px, b[1] - py), (a[0] - px, a[1] - py)])


# ------------------------------------------------------------------- floors
def build_level(lv, root):
    z = LEVEL_Z[lv["name"]]
    tag = "L0" if lv["name"] == "ground" else "L1"
    H = HEIGHTS
    group = empty(tag, root, {"kind": "level", "level": lv["name"]})

    slab = Mesh(f"{tag}_Slab")
    for x0, y0, x1, y1 in lv["slab"]:
        slab.box(x0, y0, x1, y1, z - H["slab"], z, "Slab")
    slab.build(group)

    walls = Mesh(f"{tag}_Walls")
    for loop in lv["walls"]:
        walls.prism(ccw([tuple(p) for p in loop]), z, z + H["ceiling"], "Wall", top="WallTop")
    glass, frames = Mesh(f"{tag}_Glass"), Mesh(f"{tag}_Frames")
    for o in lv["openings"]:
        quad = ccw([tuple(p) for p in o["quad"]])
        a, b = o["a"], o["b"]
        if o["kind"] == "window":
            sill = H["sill_small"] if o["width"] < 0.8 else H["sill"]
            walls.prism(quad, z, z + sill, "Wall")
            walls.prism(quad, z + H["head"], z + H["ceiling"], "Wall", top="WallTop")
            glass.prism(strip(a, b, 0.03), z + sill, z + H["head"], "Glass")
            frames.prism(strip(a, b, 0.07), z + sill, z + sill + 0.05, "Frame")
            frames.prism(strip(a, b, 0.07), z + H["head"] - 0.05, z + H["head"], "Frame")
        else:
            walls.prism(quad, z + H["head"], z + H["ceiling"], "Wall", top="WallTop")
            if o["kind"] == "slider":
                glass.prism(strip(a, b, 0.03), z, z + H["head"], "Glass")
                frames.prism(strip(a, b, 0.07), z + H["head"] - 0.05, z + H["head"], "Frame")
    walls.build(group)
    glass.build(group)
    frames.build(group)

    for i, room in enumerate(lv["rooms"]):
        name = room["name"].title().replace(" ", "")
        floor = Mesh(f"{tag}_Floor_{room.get('unit') or 'Common'}_{name}_{i}")
        mat = FLOOR_FOR.get(room["name"], "FloorConcrete")
        for x0, y0, x1, y1 in room["rects"]:
            floor.flat(x0, y0, x1, y1, z + 0.012, mat)
        floor.build(group, {"kind": "room", "room": room["name"].title(), "unit": room.get("unit") or "",
                            "area_m2": room["area_m2"], "level": lv["name"],
                            "size": f"{room['w_ft']:.1f} x {room['d_ft']:.1f} ft" if room.get("w_ft") else ""})

    fit = Mesh(f"{tag}_Fittings")
    for x0, y0, x1, y1 in lv["cabinets"]:
        fit.box(x0, y0, x1, y1, z + 0.1, z + H["counter"] - 0.04, "Cabinet")
        fit.box(x0, y0, x1, y1, z + H["counter"] - 0.04, z + H["counter"], "Counter")
    for f in lv["fixtures"]:
        x0, y0, x1, y1 = f["box"]
        if f["kind"] == "sink":
            fit.flat(x0 + 0.03, y0 + 0.03, x1 - 0.03, y1 - 0.03, z + H["counter"] + 0.004, "Basin")
        elif f["kind"] == "tub":
            fit.box(x0, y0, x1, y1, z, z + 0.52, "Porcelain")
            fit.flat(x0 + 0.08, y0 + 0.08, x1 - 0.08, y1 - 0.08, z + 0.524, "Basin")
        else:                                       # toilet: bowl plus a tank at the wall end
            long_x = (x1 - x0) > (y1 - y0)
            near_lo = furnish.wall_distance(lv, (x0 - 0.1, (y0 + y1) / 2) if long_x else ((x0 + x1) / 2, y0 - 0.1))
            near_hi = furnish.wall_distance(lv, (x1 + 0.1, (y0 + y1) / 2) if long_x else ((x0 + x1) / 2, y1 + 0.1))
            fit.box(x0, y0, x1, y1, z, z + 0.40, "Porcelain")
            t = 0.2
            if long_x:
                tx0, tx1 = (x0, x0 + t) if near_lo < near_hi else (x1 - t, x1)
                fit.box(tx0, y0, tx1, y1, z + 0.40, z + 0.78, "Porcelain")
            else:
                ty0, ty1 = (y0, y0 + t) if near_lo < near_hi else (y1 - t, y1)
                fit.box(x0, ty0, x1, ty1, z + 0.40, z + 0.78, "Porcelain")
    fit.build(group)

    rails, caps = Mesh(f"{tag}_RailGlass"), Mesh(f"{tag}_RailCaps")
    for pts in lv["railings"] + lv["deck_edges"]:
        for a, b in zip(pts, pts[1:]):
            if math.dist(a, b) < 0.02:
                continue
            rails.prism(strip(a, b, 0.02), z, z + H["rail"], "Glass")
            caps.prism(strip(a, b, 0.05), z + H["rail"], z + H["rail"] + 0.04, "Frame")
    rails.build(group)
    caps.build(group)

    if lv["name"] == "ground":                      # stairs rise from the ground floor to the first
        stairs = Mesh(f"{tag}_Stairs")
        for box in lv["stairs"]:
            build_stair(stairs, box, z)
        stairs.build(group)
    return group


def build_stair(mesh, box, z):
    """U-shaped stair filling the drawn stair box: up one side, landing, back along the other."""
    x0, y0, x1, y1 = box
    along_x = (x1 - x0) >= (y1 - y0)
    length, width = ((x1 - x0), (y1 - y0)) if along_x else ((y1 - y0), (x1 - x0))
    landing = min(width / 2, 1.1)
    run = length - landing
    risers = round(STOREY / 0.175)
    first = risers // 2
    rise = STOREY / risers

    def put(u0, u1, v0, v1, top):
        # u runs along the stair, v across it; map back to plan x, y
        if along_x:
            mesh.box(x0 + u0, y0 + v0, x0 + u1, y0 + v1, top - 0.18, top, "Stair")
        else:
            mesh.box(x1 - v1, y0 + u0, x1 - v0, y0 + u1, top - 0.18, top, "Stair")

    going = run / first
    for i in range(first):                          # flight one, rising away from the start
        put(i * going, (i + 1) * going, 0, width / 2 - 0.03, z + (i + 1) * rise)
    put(run, length, 0, width, z + first * rise)    # landing
    going = run / (risers - first)
    for i in range(risers - first):                 # flight two, coming back
        put(run - (i + 1) * going, run - i * going, width / 2 + 0.03, width, z + (first + i + 1) * rise)


def build_roof(lv, root):
    z = LEVEL_Z["first"] + HEIGHTS["ceiling"]
    group = empty("Roof", root, {"kind": "roof"})
    roof = Mesh("Roof_Slab")
    for x0, y0, x1, y1 in lv["roof"]:
        roof.box(x0, y0, x1, y1, z, z + HEIGHTS["slab"], "Roof")
    for x0, y0, x1, y1 in lv["parapet"]:
        roof.box(x0, y0, x1, y1, z + HEIGHTS["slab"], z + HEIGHTS["slab"] + HEIGHTS["parapet"], "Wall", top="WallTop")
    roof.build(group)
    return group


def build_site(root):
    w, d = PLAN["extent"]
    site = Mesh("Site_Ground")
    site.flat(-14, -16, w + 14, d + 12, -HEIGHTS["slab"] - 0.02, "Lawn")
    site.flat(-1.2, -7.5, w + 1.2, 0.2, -HEIGHTS["slab"] - 0.01, "Paving")
    site.build(empty("Site", root, {"kind": "site"}))


# ----------------------------------------------------------------- previews
def render_previews(roof, first):
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.display.shading.light = "STUDIO"
    scene.display.shading.color_type = "MATERIAL"
    scene.display.shading.show_shadows = True
    scene.display.shading.show_cavity = True
    scene.render.resolution_x, scene.render.resolution_y = 1600, 1000
    scene.render.film_transparent = False
    cam_data = bpy.data.cameras.new("PreviewCam")
    cam = bpy.data.objects.new("PreviewCam", cam_data)
    scene.collection.objects.link(cam)
    scene.camera = cam
    w, d = PLAN["extent"]
    target = Vector((w / 2, d / 2, 2.0))

    def shoot(name, pos, hide=()):
        for ob in bpy.data.objects:
            top = ob
            while top.parent and top.parent.name != "Clint_Building":
                top = top.parent
            ob.hide_render = top in hide
        cam.location = pos
        cam.rotation_euler = (target - Vector(pos)).to_track_quat("-Z", "Y").to_euler()
        cam_data.lens = 32
        scene.render.filepath = str(ROOT / "build" / "cache" / f"preview-{name}.png")
        bpy.ops.render.render(write_still=True)

    shoot("exterior", (w / 2 + 16, -34, 20))
    shoot("first-open", (w / 2 + 6, -20, 34), hide=(roof,))
    shoot("ground-open", (w / 2 + 6, -20, 34), hide=(roof, first))
    for ob in bpy.data.objects:
        ob.hide_render = False
    bpy.data.objects.remove(cam)


def feet(v):
    whole = int(v + 1e-6)
    return f"{whole}'-{round((v - whole) * 12)}\""


def write_building_json(placed):
    """Facts the web page prints beside the model: apartments, rooms, sizes."""
    levels = {lv["name"]: lv for lv in PLAN["levels"]}
    apartments = []
    for u in PLAN["apartments"]:
        rooms = [r for r in levels[u["level"]]["rooms"] if r.get("unit") == u["id"]]
        boxes = [r["bbox"] for r in rooms]
        apartments.append({
            "id": u["id"], "name": u["name"], "type": u["type"], "level": u["level"], "color": u["color"],
            "area_m2": u["area_m2"], "area_sqft": round(u["area_m2"] * 10.7639),
            "bbox": [min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)],
            "rooms": [{"name": r["name"].title(), "size": f"{feet(r['w_ft'])} x {feet(r['d_ft'])}" if r.get("w_ft") else "",
                       "area_m2": r["area_m2"], "at": r["label"]} for r in rooms],
        })
    out = {"extent": PLAN["extent"], "storey": STOREY, "level_z": LEVEL_Z, "heights": HEIGHTS,
           "apartments": apartments, "furniture_pieces": placed}
    (ROOT / "web" / "assets" / "building.json").write_text(json.dumps(out, indent=1))


# --------------------------------------------------------------------- main
def main():
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob)
    root = empty("Clint_Building", None, {"kind": "building"})
    build_site(root)
    levels = {lv["name"]: lv for lv in PLAN["levels"]}
    ground = build_level(levels["ground"], root)
    first = build_level(levels["first"], root)
    roof = build_roof(levels["first"], root)

    placed = 0
    if "--no-furniture" not in sys.argv and FURNITURE_BLEND.exists():
        kit = furnish.load_kit(FURNITURE_BLEND)
        for lv, group in ((levels["ground"], ground), (levels["first"], first)):
            holder = empty(group.name + "_Furniture", group, {"kind": "furniture", "level": lv["name"]})
            placed += furnish.furnish_level(lv, LEVEL_Z[lv["name"]], kit, holder)
        furnish.discard_kit(kit)
    print(f"placed {placed} furniture pieces")

    (ROOT / "web" / "assets").mkdir(parents=True, exist_ok=True)
    (ROOT / "build" / "cache").mkdir(parents=True, exist_ok=True)
    if "--no-render" not in sys.argv:
        render_previews(roof, first)
    bpy.ops.wm.save_as_mainfile(filepath=str(ROOT / "build" / "clint-building.blend"))
    bpy.ops.export_scene.gltf(filepath=str(ROOT / "web" / "assets" / "clint.glb"), export_format="GLB",
                              export_extras=True, export_apply=True, export_yup=True, export_cameras=False,
                              export_lights=False)
    write_building_json(placed)
    tris = sum(len(p.vertices) - 2 for ob in bpy.data.objects if ob.type == "MESH" for p in ob.data.polygons)
    size = (ROOT / "web" / "assets" / "clint.glb").stat().st_size
    print(f"exported {len(bpy.data.objects)} objects, about {tris} triangles, {size / 1e6:.2f} MB")


main()
