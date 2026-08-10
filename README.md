# Tkinter USD 3D Viewer

A lightweight desktop viewer for [OpenUSD](https://openusd.org/) files, built with Tkinter and raw OpenGL (via [`pyopengltk`](https://pypi.org/project/pyopengltk/)). It renders `Mesh`, `Cube`, `Sphere`, `Cone`, `Cylinder`, and `Capsule` prims using a fixed-function orbit camera — no Hydra or `UsdImagingGL` required.

## Features

- **Open USD files** — `.usd`, `.usda`, `.usdc`, `.usdz`
- **Orbit camera** — drag to rotate, scroll to zoom (relative zoom that scales with the loaded asset's size)
- **Auto-framing** — the camera centers and fits itself to whatever geometry is loaded
- **Shading modes** — Shaded (textures + vertex colors), Solid, Wireframe, and Normals (visualized as RGB)
- **Textures & colors** — resolves a prim's bound `UsdPreviewSurface` to pull in a `diffuseColor` texture (with `st` UVs) or a constant tint, falling back to authored `displayColor` primvars
- **Bounding box overlay** — toggle a wireframe box around the loaded geometry
- **Background modes** — Black, Gray, Sky (gradient), Foggy (with depth fog)
- **Animation playback** — a time slider and Play/Pause button drive the stage's authored time-code range at its authored frames-per-second
- **Hot reload** — the currently open file is polled once a second and automatically reloaded when its contents change on disk, without resetting the camera. A save that fails to parse is skipped (the last good frame stays on screen) and retried on the next save.

## Requirements

- Python 3.14 (see `.python-version`)
- Dependencies (see `pyproject.toml`): `numpy`, `pillow`, `pyopengl`, `pyopengltk`, `usd-core`

## Installation

Using [uv](https://docs.astral.sh/uv/):

```sh
uv sync
```

## Usage

```sh
uv run app.py
```

Click **Open USD File** to load a stage, then:

| Action | Control |
| --- | --- |
| Orbit | Left-click drag |
| Zoom | Mouse wheel |
| Reset view | "Reset View" button |
| Change shading | "Shading" dropdown |
| Toggle bounding box | "Bounding Box" checkbox |
| Change background | "Background" dropdown |
| Scrub time | Time slider (enabled when the stage has an authored time-code range) |
| Play/pause animation | "Play" button |

## Project Structure

| File | Responsibility |
| --- | --- |
| `app.py` | Entry point — launches the Tk application |
| `main_window.py` | `USDViewerTk` — the main window: toolbar, playback controls, file loading, and hot-reload |
| `viewport.py` | `USDGLViewport` — the OpenGL Tkinter widget: camera, rendering, mouse input |
| `usd_geometry.py` | Walks a USD stage and fan-triangulates `Mesh`/`Cube`/`Sphere`/`Cone`/`Cylinder`/`Capsule` prims into position/normal/color/UV arrays, grouped by bound texture |
| `gl_helpers.py` | Generic OpenGL helpers — matrix conversion and texture loading |
| `constants.py` | Shared color and background constants |

## Limitations

- Only `Mesh`, `Cube`, `Sphere`, `Cone`, `Cylinder`, and `Capsule` prims are rendered (no curves or points)
- Fan triangulation assumes convex polygon faces
- Uses fixed-function OpenGL lighting (single directional light), not a physically based renderer
