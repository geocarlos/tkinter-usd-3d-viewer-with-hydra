# Gray / too-dark models — diagnosis and plan

Both causes were reproduced by rendering through the viewer's own `USDGLViewport` and screenshotting.

## Cause 1 — gray (BeetleFusca): `material:binding` authored without `MaterialBindingAPI`

- Beetle: 23 gprims, all have a `material:binding` relationship, **0** have `MaterialBindingAPI` in `apiSchemas`
  (USD warns: "Found material bindings … but MaterialBindingAPI is not applied"). Materials themselves are
  fine (`UsdPreviewSurface` + `UsdUVTexture`).
- Hydra (this USD build) ignores unapplied bindings → no material → default gray.
- Saveiro: 119/119 gprims have the API applied → materials resolve (it is *not* gray).
- Proof: applying `UsdShade.MaterialBindingAPI.Apply(prim)` on the session layer turned the Beetle from gray to
  teal/white/orange with textures.

## Cause 2 — too dark (Saveiro, and Beetle once textured): no environment light for metals

- Saveiro materials: 9 of 20 have `metallic` 0.5–1.0 (several diffuse = 0/black); many dielectric diffuse values
  are ~0.011–0.014 (near-black paint/rubber). Beetle uses metallic/roughness textures.
- Metallic PBR has no diffuse term; it only shows reflections. [viewport.py](viewport.py) injects three directional
  `Glf.SimpleLight`s (specular 0.35 / 0 / 0.1) and **no environment** → metals and rough dark surfaces render
  near-black.
- Proof: adding a `DomeLight` with a lat-long sky texture (session layer) fixed both models: bodies lit, chrome/rims
  reflective, interior readable. A `DomeLight` with **no texture** had *no effect* (identical pixels).

## Plan

1. **Auto-apply missing `MaterialBindingAPI` on load** — in `load_stage()` (viewport.py), on the session layer
   (non-destructive, same approach as `implicit_surfaces.apply_overrides`): for each gprim/prim with
   `HasRelationship("material:binding")` (also `material:binding:preview/full`) and no API, call
   `UsdShade.MaterialBindingAPI.Apply(prim)`. Do it *before* `_create_engine()`. Put it in a new small module
   (e.g. `stage_fixups.py`) so it's testable. Also covers hot-reload (re-run after `Reload()`; session-layer opinions
   survive Reload but new prims may appear).
2. **Add a default image-based light (IBL)** — ship a small neutral sky/studio lat-long image (e.g. `assets/env.png`,
   or `.exr/.hdr` for real HDR range; the test used a 512×256 PNG gradient) and add a session-layer
   `UsdLux.DomeLight` with `texture:file` + `texture:format = latlong` at a reserved path (e.g. `/__viewer_dome`),
   **only when the stage has no lights of its own** (existing `_stage_has_lights` logic, evaluated *before*
   adding ours).
   - Needs `enableSceneLights = True` in Shaded mode when our dome is present (currently gated on
     `_stage_has_lights`); keep the 3-point rig for Solid/Wireframe/Normals.
   - Exclude `/__viewer_dome` from `BBoxCache`/stage-light detection.
3. **Background interaction (decision needed)** — Hydra draws the dome texture as the backdrop (seen in the
   screenshots, overriding the Background dropdown). Options: (a) accept it and make "Background" meaningful only
   when the dome is hidden; (b) keep the Black/Gray/Sky/Foggy backdrops by drawing the dome as light-only.
   Recommend (b): the dome's `visibility`/camera-visibility can't be toggled per-light in Storm, so likely
   composite: render with the dome, then mask by depth/alpha — or simplest, expose a "Environment: Off / Studio"
   dropdown and let Studio own the background. Prototype (b); fall back to the dropdown.
4. **Light intensity/exposure** — expose a modest intensity default (tested at 1.0, looked right) and clamp
   so bright textured models don't blow out. Optional exposure slider later.
5. **Verification** — add a smoke script (headless-ish Tk + `glReadPixels`, like the one used here) asserting
   non-bg mean brightness above a threshold and that Beetle isn't uniform gray (e.g. colour variance across
   non-bg pixels). Run on both reference models plus a simple one-sphere stage (regression).
   Also run `usdchecker` on any generated/modified USD per project guidelines (session-layer edits aren't
   exported, so only needed if we add an "export fixed" feature).
6. **Optional, separate**: report to the user (status bar) when fixups were applied ("Applied MaterialBindingAPI to
   23 prims") so a silent fix isn't mistaken for the asset being valid; the source asset itself should be
   fixed in `openusd-vehicle-library` (re-export with API schemas applied).

## Notes / non-causes ruled out

- Not a texture-path problem: usdz textures resolve (`…usdz[0/material_baseColor.jpg]`).
- Not a UV/primvar problem: `st0` reader is present and textures displayed once binding was applied.
- Not a missing-lights-in-stage problem per se: the default rig is adequate for non-metal, light-colored
  materials; it's the lack of an environment that kills metals/dark materials.
