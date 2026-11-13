#!/usr/bin/env python3
"""Draw build/plan.json as flat SVG tiles so the extraction can be checked by eye."""
import json, sys, colorsys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "build" / "cache"
plan = json.loads((ROOT / "build" / "plan.json").read_text())
W, H = plan["extent"]
KIND = {"window": "#1e6bff", "door": "#e11", "slider": "#0a8", "cased": "#f90"}
for lv in plan["levels"]:
    body = []
    for i, r in enumerate(lv["rooms"]):
        col = "#%02x%02x%02x" % tuple(int(v * 255) for v in colorsys.hsv_to_rgb((i * 0.137) % 1, 0.35, 1.0))
        for x0, y0, x1, y1 in r["rects"]:
            body.append(f'<rect x="{x0}" y="{y0}" width="{x1-x0}" height="{y1-y0}" fill="{col}"/>')
    for x0, y0, x1, y1 in lv["cabinets"]:
        body.append(f'<rect x="{x0}" y="{y0}" width="{x1-x0}" height="{y1-y0}" fill="#b98" />')
    for f in lv["fixtures"]:
        x0, y0, x1, y1 = f["box"]
        c = {"tub": "#39c", "toilet": "#c3c", "sink": "#333"}[f["kind"]]
        body.append(f'<rect x="{x0}" y="{y0}" width="{x1-x0}" height="{y1-y0}" fill="none" stroke="{c}" stroke-width="0.05"/>')
    for x0, y0, x1, y1 in lv["stairs"]:
        body.append(f'<rect x="{x0}" y="{y0}" width="{x1-x0}" height="{y1-y0}" fill="none" stroke="#f0f" stroke-width="0.06"/>')
    for loop in lv["walls"]:
        body.append('<polygon points="%s" fill="#222"/>' % " ".join(f"{x},{y}" for x, y in loop))
    for o in lv["openings"]:
        body.append('<polygon points="%s" fill="%s"/>' % (" ".join(f"{x},{y}" for x, y in o["quad"]), KIND[o["kind"]]))
    for pts in lv["railings"]:
        body.append('<polyline points="%s" fill="none" stroke="#0c0" stroke-width="0.07"/>' % " ".join(f"{x},{y}" for x, y in pts))
    for pts in lv["deck_edges"]:
        body.append('<polyline points="%s" fill="none" stroke="#80f" stroke-width="0.07"/>' % " ".join(f"{x},{y}" for x, y in pts))
    text = []
    for r in lv["rooms"]:
        x, y = r["label"]
        flag = "" if r["source"] == "flood" else "*"
        unit = r.get("unit", "")
        text.append(f'<text x="{x}" y="{-y}" font-size="0.42" text-anchor="middle" font-family="Helvetica" fill="#000">{r["name"]}{flag} {unit}</text>')
    side = W / 2 + 1.5
    for t, tx in enumerate((-1.0, W / 2 - 0.5)):
        svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{tx} {-(H+1.5)} {side} {side}" width="2000" height="2000">'
               f'<rect x="{tx}" y="{-(H+1.5)}" width="{side}" height="{side}" fill="#fff"/>'
               f'<g transform="scale(1,-1)">{"".join(body)}</g>{"".join(text)}</svg>')
        (out_dir / f"dbg-{lv['name']}-{t}.svg").write_text(svg)
print("wrote debug tiles to", out_dir)
