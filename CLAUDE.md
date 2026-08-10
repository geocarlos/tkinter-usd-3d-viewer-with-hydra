This repo is a fresh copy of `tkinter-app` (Geo/code2graphics) — a lightweight Tkinter + raw OpenGL USD viewer with a hand-written fixed-function renderer (no Hydra). That original repo is being kept as-is, permanently, as the "no-Hydra" lightweight alternative. This copy's job is to replace its manual rendering path with Pixar Hydra (`UsdImagingGL.Engine` / the Storm render delegate), while keeping the same Tkinter shell — toolbar, orbit camera, playback slider, hot file-reload — wherever that still makes sense.

## What the original repo does today

- `usd_geometry.py` walks a `Usd.Stage` and hand-triangulates `Mesh`/`Cube`/`Sphere`/`Cone`/`Cylinder`/`Capsule` into flat position/normal/color/UV arrays grouped by bound texture; `Points`/`BasisCurves` get either instanced triangle geometry ("Solid" mode) or raw `GL_POINTS`/`GL_LINES` ("Lightweight" mode).
- `viewport.py`'s `USDGLViewport` (a `pyopengltk.OpenGLFrame`) draws all of that with immediate-mode-style vertex arrays and fixed-function lighting, plus its own orbit camera (drag to rotate, scroll to zoom, auto-framing on load).
- `main_window.py`'s `USDViewerTk` is the Tk window: file-open dialog, shading/background/curves-points dropdowns, bounding-box/grid checkboxes, a time slider + Play/Pause driven by the stage's authored time-code range, and a 1-second poll that hot-reloads the open file on disk changes.

None of that rendering code needs to survive intact here — Hydra supersedes almost all of it. The UI orchestration in `main_window.py` is the part worth keeping.

## Already verified — don't re-derive these

- The PyPI `usd-core` wheel (what the original repo installs via `uv`) has **no Hydra**: `from pxr import UsdImagingGL` raises `ImportError` there. Confirmed directly.
- **conda-forge ships a prebuilt `openusd` package that includes Hydra/Storm/UsdImagingGL/usdview**: https://anaconda.org/conda-forge/openusd. No from-source build needed.
- This machine's GPU/driver clears Hydra's GL backend (`HgiGL`) minimum requirement (OpenGL 4.5) with room to spare — a live `glGetString(GL_VERSION)` query inside an actual `pyopengltk` context reported **OpenGL 4.6 core** on the Intel Iris Xe. There's also a discrete NVIDIA MX330 available, which supports 4.6+ as well.
- **Not yet verified**: whether `pyopengltk`'s Tkinter-created GL context can be adopted directly by `HgiGL`/`UsdImagingGL.Engine`, or whether Hydra needs/prefers to own its own context. Treat this as the first real risk to retire, before investing in anything else.

## Task 1: swap `uv` for conda

- Replace `pyproject.toml`/`uv.lock` with a conda/mamba `environment.yml` so `openusd` can come from conda-forge prebuilt.
- Likely dependencies: `openusd` (conda-forge), `pyopengl`, `pillow`, `numpy`; check whether `pyopengltk` is available on conda-forge or needs a `pip:` sub-section in the env file.
- Update `.python-version`/README to describe `conda env create`/`conda activate` instead of `uv sync`/`uv run`.

## Task 2: get Hydra rendering, in this order

1. Create the conda env, confirm `from pxr import UsdImagingGL` imports.
2. **Spike the context question first**, before anything else: the smallest possible `pyopengltk.OpenGLFrame` subclass whose `initgl()` constructs a `UsdImagingGL.Engine()` and whose `redraw()` calls `engine.Render(stage.GetPseudoRoot(), UsdImagingGL.RenderParams())` against a trivial one-sphere stage. Get one real frame on screen before touching the rest of the app.
3. Once that works, wire in real behavior:
   - **Camera** — reuse the existing `Gf.Frustum`-based view/projection matrix math (`viewport.py`'s `get_view_matrix()`/`redraw()`), fed to `engine.SetCameraState(view_matrix, projection_matrix)` (confirm exact method name/signature in the installed version — the API has moved around across USD releases).
   - **Time** — feed the time slider's `Usd.TimeCode` into the render params' frame instead of re-triangulating by hand.
   - **Shading modes** — map the existing Shaded/Solid/Wireframe/Normals dropdown to `UsdImagingGL.RenderParams.drawMode` (check the exact enum names shipped in this version, e.g. `DRAW_SHADED_SMOOTH`, `DRAW_WIREFRAME`, `DRAW_GEOM_ONLY`).
   - **Grid / bounding-box overlays** — not a Hydra concept; keep drawing these with the existing raw-GL calls (`_draw_grid`/`_draw_bbox`), composited before or after `engine.Render()` (whichever order looks right against the depth buffer).
4. Decide, with the user, what happens to the "Solid vs Lightweight" Points/Curves toggle — Hydra renders `Points`/`BasisCurves` natively and correctly (including real curve-basis evaluation, which the original's linear-only approximation doesn't do), so the toggle may just become unnecessary. Don't remove it unilaterally without checking.
5. Once Hydra rendering is solid, most of `usd_geometry.py` (triangulation, per-Gprim face generators, primvar plumbing) is dead code. Delete it rather than leaving it around unused.

## Explicit non-goals

- Don't try to preserve feature parity with the original's "Lightweight" `GL_POINTS`/`GL_LINES` mode unless asked — Hydra's native handling supersedes it.
- Don't add a fallback to the old fixed-function path in this repo "just in case" — that path already exists, permanently, in the original `tkinter-app` repo.
