# Virtual home websites: how Casa and Astra are built

Reviewed 12 November 2026. Both projects were read from source in `~/Downloads`. Neither was run locally, so everything below comes from the code, the bundled docs and the bundled screenshots.

| | Casa | Astra |
| --- | --- | --- |
| Folder | `~/Downloads/casa-serra-main` | `~/Downloads/Astra Website Build Tutorial /clearline-plumbing` |
| Real name | Lintel · Casa Serra (architecture studio concept) | Clearline Plumbing (fictional plumber site, tutorial pack) |
| Live demo | https://sam1983aing.github.io/casa-serra/ | https://clearline-plumbing-demo.nico-510.workers.dev/ |

## The short answer

- **Neither house was made in Blender.** There is no model file (`.glb`, `.gltf`, `.blend`, `.fbx`, `.obj`) anywhere in either project. Both use only a texture loader, never a model loader.
- **Both houses are built by code.** The code is a recipe: "put a box this big, here, with this material." The browser follows the recipe and builds the house fresh every time the page loads. Think LEGO from written instructions rather than a finished sculpture shipped in a box.
- **Both use the same three ingredients:** Three.js (draws 3D in the browser), GSAP ScrollTrigger (ties scroll position to animation), and free CC0 surface photos from Poly Haven (wood, stone, marble, plaster).
- **Both move the camera the same way:** a short list of camera stops. Scrolling slides the camera from one stop to the next.
- **Both have reusable parts.** In each one, the scroll and camera engine is separate from the house. The house itself is custom to that project.

## Casa Serra

### What you see

The page opens on what looks like a flat architect's floor plan on paper. As you scroll, the walls rise out of the drawing, the camera drops to the front door and walks through seven rooms at eye height. Each room stays a black ink drawing until the camera arrives, then real materials sweep across it.

### How it is built

**Plain files, no build step.** One `index.html` loads Three.js 0.160, GSAP 3.13 and Lenis (smooth scrolling) from public CDNs, then nine script files. You can host it anywhere static.

**The house is a list of rectangles.** `scene.js` starts with two data lists:

- 19 zones (16 rooms plus patio, garden and yard), each a rectangle in metres. Example: the kitchen is `[9, 0, 25, 8]`, meaning a room from x 9 to 25 and z 0 to 8.
- 36 openings (doors, glass walls, open passages), each a position along a wall line.

Code reads those lists and generates walls, floors, ceilings and door gaps. Furniture is added by `staging.js`, also in code, using boxes with softened edges, flat planes, and lumpy spheres for rocks.

**The floor plan is not a picture.** It is the real 3D house, with two tricks applied:

1. The camera looks almost straight down (89.4°) through an extreme zoom lens (3° field of view). That removes perspective, so the model looks like a flat drawing.
2. The whole model is sliced at about 1.2 m, like cutting the top off a cake. Scrolling raises the slice height, and that is the walls "growing."

**The ink-to-real sweep is a custom shader.** Every material passes through one wrapper that adds extra drawing instructions. For each pixel it asks "which room rectangle am I in, and has that room been revealed yet?" and paints either ink on paper or the real surface.

**The camera is a list of stops.** Each stop has a target point, direction, lens, and two scroll lengths: how long to dwell and how long to travel. The engine draws a smooth curve through them.

**Looks.** 13 Poly Haven texture sets, shipped in two sizes (36 MB for laptops, 11 MB for phones), plus one sky image that supplies lighting and reflections. Two finishing passes add soft contact shadows, bloom, grain, and the paper and ink look.

**Safety net.** `gate.js` checks the device. If it cannot draw 3D, runs out of memory, or loads too slowly, the visitor gets a still image and a 13 MB video of the walk instead.

### Reusable parts

| Part | Files | Reusable? |
| --- | --- | --- |
| Engine: scroll, camera path, loading, helpers, finishing passes | `shared/fx-core.js`, `fx-experience.js`, `fx-post.js`, `fx-paint.js`, `fx-ui.css` | Yes. Written to be shared. It accepts camera stops, room info cards and a "build the scene" function. |
| Device fallback | `gate.js` | Yes, with new text and media. |
| House layout and reveal shader | `scene.js` | Pattern is reusable (swap the room and opening lists). The code is specific to this house. |
| Furniture | `staging.js` | No. Hand-placed for this house. |
| Font and lighting variants | `hero-options.js`, `light-options.js` | Partly. They are design switches the author left in, driven by URL options. |

**Catch:** this download is the published copy, so every script is minified (squeezed onto one line with one-letter names). It runs fine but is painful to edit. The author's readable starting point is the sibling project at https://github.com/Sam1983Aing/casa-larga, plus the starter prompt in `starter-prompt.md`.

### How it was made

Per its README: about 70 prompts over two weeks and four full versions, using Claude Code. The README states plainly, "No Blender on this one."

## Astra (Clearline Plumbing)

"Astra" appears to be the AI coding agent the tutorial uses. The website it produced is Clearline Plumbing, a complete fictional business site. The pack contains the finished source plus two prompts for rebuilding it. Those prompts were read as documentation only and not acted on.

### What you see

The homepage opens on a finished two-storey stone house. As you scroll, the front wall and side wall slide away, the roof lifts off, and the camera visits four stops: upstairs bathroom, kitchen, hot-water cupboard, then a dark "x-ray" view where the walls fade and the pipes show. Each stop has real text and a link to a service page beside it.

### How it is built

**A full website with a build step.** Astro 7 produces the pages, Sanity is the content editor, Cloudflare hosts it. It includes service pages, area pages, a blog, team page, contact form, SEO checks and automated tests. The 3D house is one feature on the homepage. You need `npm install` and a build to run it.

**The house is one readable file.** `src/scripts/house-model.ts` is 426 lines. It defines a handful of helpers, then calls them with hand-typed sizes and positions:

- `box` 86 times (walls, floors, cabinets, steps)
- `pipe` 26 times (plumbing, plant stems, branches)
- `cylinder` 18 times (taps, tank, posts)
- Spun profiles for the bath, basin and plant pots
- 420 copies of one small sphere per olive tree for the leaves

**The house is sorted into seven named groups:** downstairs, upstairs, roof, pipes, garden, front exterior, side exterior. Each group can fade or slide on its own. That is the whole "dollhouse opening" effect.

**The camera is five stops.** Each stop stores a camera position, a look-at point, and five dials from 0 to 1: roof, upper floor, shell, pipes, exterior. Example: the kitchen stop sets roof 0 and upper 0, so both are hidden. Scrolling blends the numbers between neighbouring stops.

**Looks.** Four Poly Haven texture sets (oak, stone, marble, plaster) at 947 KB total, or 138 KB for phones. Lighting comes from a built-in studio environment, so no sky file is needed. Desktop adds contact shadows and edge smoothing; phones skip them.

**Fast first load.** The page first shows a still picture of the house, which is a screenshot taken from the 3D model itself. The 3D code loads only when the visitor starts to scroll, hover or tap. If 3D fails, the picture and all the text stay. Their recorded mobile Lighthouse performance score went from 64 to 99 after this change.

### Reusable parts

| Part | Files | Reusable? |
| --- | --- | --- |
| Scroll and camera engine, lazy loading, reduced motion, cleanup | `src/scripts/house-journey.ts` (137 lines) | Yes. It only needs a model that offers `render`, `resize` and `dispose`, plus a list of stops. |
| Finishing effects | `src/scripts/house-postprocessing.ts` (22 lines) | Yes, as is. |
| Page layout and room text | `src/components/HouseJourney.astro` | Yes. Room names, copy and links are one list at the top. |
| Building helpers (`box`, `pipe`, `plant`, `oliveTree`) | inside `house-model.ts` | Yes, but they sit inside one big function and would need lifting out. |
| The house itself | `house-model.ts` | No. Every size and position is typed by hand for this house. |
| Texture preparation | `scripts/prepare-house-materials.mjs` | Yes. Downloads and shrinks Poly Haven textures. |

### How it got here

The bundled notes show four stages:

1. **Flat version.** Two AI-generated pictures of the same house, one normal and one with pipes exposed, stacked. A circle following the cursor showed the pipe picture through it. This code is still in the project (`HouseExplorer.astro`) but no longer on the homepage.
2. **First 3D version.** Simple boxes built in code.
3. **Realism pass.** Real textures, rounded edges, detailed fixtures, contact shadows.
4. **Closed exterior and speed pass.** Added the removable front and side walls and the picture-first loading.

Their own notes name Blender as the next step, not something already done: a detailed Blender model exported as GLB, with roof, upper floor, fixtures and pipes as separate groups, could replace the coded house without changing the page, the content system or the scroll setup.

## Side by side

| | Casa Serra | Astra (Clearline) |
| --- | --- | --- |
| Feel | Cinematic walk through a large villa | Dollhouse that opens up beside sales copy |
| Made in Blender | No | No (suggested as a future upgrade) |
| How the house is defined | Lists of room rectangles and openings, then generated | About 150 hand-placed shapes |
| Camera | Curved path, eye-level walk, many stops | Straight blends between 5 outside-looking-in stops |
| Signature trick | Floor plan that is secretly the 3D model, sliced and viewed from above | Named groups that fade and slide away |
| Site type | Single page, plain files | Full multi-page business site with content editor |
| Code state | Minified, hard to edit | Readable TypeScript |
| Download weight for 3D | 13 to 39 MB of textures | About 0.3 to 1.2 MB |
| Phone support | Smaller textures, video fallback | Smaller textures, picture-first, effects skipped |
| Search-engine friendliness | Low priority (concept piece) | High priority (all text is real HTML) |

## What this means if you want to build one

- **For a business site with a house as the hook:** the Astra pattern is the easier base. It is readable, light, and the text stays visible to search engines. Swap the room list and the five camera stops, then rebuild or replace the house.
- **For a showpiece walk-through:** the Casa pattern is the one to follow, but start from the readable Casa Larga code or the starter prompt, not this minified copy.
- **Where Blender fits:** both projects avoided it, but both designs leave room for it. Model the house in Blender, keep the parts in named groups (roof, upstairs, downstairs, pipes, exterior), export one GLB file, and load it in place of the coded house. The scroll and camera code stays the same. For the Casa floor-plan trick, the slice-from-above part works with any model; the ink-to-real sweep would need each Blender material passed through the same shader wrapper.
- **Trade-off between code-built and Blender-built:** code-built houses are tiny to download and easy to tweak by number, but organic or detailed shapes are slow to describe. Blender models look richer faster, but the file is heavier and changes mean re-exporting.
