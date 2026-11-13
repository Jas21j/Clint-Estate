# Lot 201 Oxford: 3D walkthrough

A scroll-driven 3D model of the proposed residential building, built from the two floor-plan PDFs in this folder. Eight apartments on two floors, with furniture that can be switched off.

## See it

```bash
python3 -m http.server 4173 --bind 127.0.0.1 --directory web
```

Then open http://localhost:4173. It needs an internet connection the first time, because Three.js and the fonts load from public CDNs.

- **Scroll** to take the building apart: exterior, roof off, each first-floor apartment, ground floor, each ground-floor apartment.
- **Furnished / Empty** (top right) shows or clears the furniture.
- **Explore freely** switches to drag-to-orbit, with buttons for each floor and apartment. Esc returns to the story.

## How it is made

Three steps, each one a script. Re-run them in order after changing anything.

| Step | Script | Reads | Writes |
| --- | --- | --- | --- |
| 1. Read the plans | `build/extract_plan.py` | the two PDFs, `build/units.json` | `build/plan.json` |
| 2. Build the model | `build/build_blender.py` (uses `build/furnish.py`) | `build/plan.json`, the furniture kit | `build/clint-building.blend`, `web/assets/clint.glb`, `web/assets/building.json` |
| 3. Show it | `web/index.html`, `web/main.js`, `web/style.css` | the two files in `web/assets` | the page |

```bash
/Applications/Blender.app/Contents/Resources/5.2/python/bin/python3.13 build/extract_plan.py
```

```bash
/Applications/Blender.app/Contents/MacOS/Blender -b --factory-startup --python build/build_blender.py
```

Step 1 uses Blender's bundled Python only because it ships with numpy. `python3 build/debug_plan.py` draws what step 1 found as flat pictures in `build/cache`, which is the quickest way to check a change.

`build/clint-building.blend` is a normal Blender file. Open it to look around, re-colour, or render stills. It is overwritten by every build, so save your own edits under another name.

## What is real and what is assumed

**From the drawings (003 ground plan, 004 first floor plan):** every wall, door, window and sliding door position, kitchen counters, baths, toilets, sinks, stair positions, balcony and deck edges, room names and printed room sizes.

**Assumed, because the drawings do not say:**

| Thing | Value | Where to change it |
| --- | --- | --- |
| Ceiling height | 2.75 m (about 9 ft) | `HEIGHTS` in `build/build_blender.py` |
| Floor plate thickness | 0.20 m | same |
| Window sill and head | 0.90 m and 2.10 m | same |
| Roof parapet | 0.75 m | same |
| Wall, floor and roof colours | plain placeholders | `COLORS` in `build/build_blender.py` |
| Stair shape | U-shaped flights inside the drawn stair box | `build_stair` in `build/build_blender.py` |
| Which rooms form which apartment | read off the drawings | `build/units.json` |
| Furniture choice and position | rule based | `ROOM_PLANS` and the room functions in `build/furnish.py` |

**Not modelled:** the lower ground floor (only a sketch exists), the sloping site, exterior colours and cladding from the designer's render, door leaves, ceiling lights, upper kitchen cabinets.

## Things worth knowing

- **Scale.** The PDFs were plotted "to fit", not at a round scale. 80 drawing units per foot makes every wall exactly 6 in thick and every room match its printed size, so that is the scale used. Footprint comes out at about 119 × 58 ft.
- **Apartment count.** The detailed plans show eight apartments: a two-bedroom at the back of each floor and three one-bedrooms along the front. The earlier colour-coded concept sheets (`combinepdf (1)-1.pdf`) split the ground-floor back wing into a one-bedroom plus a studio; the detailed plan does not show a wall between them.
- **Areas** on the page are measured from the model (inside wall faces), so they differ slightly from width × depth on the room labels.
- **Furniture** comes from `~/Desktop/Omereta/blender/home_models.blend` (collections named `HM_<piece>`, sized in studs, 0.28 m each). The build reads that file and never changes it. Only two of the eight living rooms got a dining table; the placement rule found no clear spot in the other six.
- **If the designer sends a 3D export** (Chief Architect can export DAE, 3DS or 3D DWG), it can replace `clint.glb` as long as it keeps groups named `Roof`, `L1`, `L0`, `L1_Furniture`, `L0_Furniture` and `Site`. The page code does not otherwise care how the model was made.
