# Tkinter USD 3D Viewer

A desktop viewer for [OpenUSD](https://openusd.org/) files, built with Tkinter and [`pyopengltk`](https://pypi.org/project/pyopengltk/), rendering through Pixar Hydra (`UsdImagingGL.Engine` / the Storm render delegate). It renders whatever the stage contains — meshes, primitive shapes, `Points`, `BasisCurves` with correct curve-basis evaluation, materials, and lights — the same way `usdview` does, behind a lightweight custom Tk shell with its own orbit camera.

## Features

- **Open USD files** — `.usd`, `.usda`, `.usdc`, `.usdz`
- **Orbit camera** — drag to rotate, scroll to zoom (relative zoom that scales with the loaded asset's size)
- **Auto-framing** — the camera centers and fits itself to whatever geometry is loaded, computed from the stage's world-space bounding box
- **Shading modes** — Shaded (materials + lighting), Solid (lit, materials ignored), Wireframe, and Normals (Storm's eye-space normal AOV)
- **Bounding box overlay** — toggle a wireframe box around the loaded geometry
- **Grid toggle** — the ground grid + origin axes are shown by default and can be toggled off
- **Background modes** — Black, Gray, Sky (gradient), Foggy (depth fog on the grid/bbox overlay only — Hydra-rendered geometry doesn't read legacy `GL_FOG` state)
- **Animation playback** — a time slider and Play/Pause button drive the stage's authored time-code range at its authored frames-per-second, feeding `Usd.TimeCode` straight into Hydra's render params
- **Hot reload** — the currently open file is polled once a second and automatically reloaded when its contents change on disk, without resetting the camera. A save that fails to parse is skipped (the last good frame stays on screen) and retried on the next save.

## Requirements

- [conda](https://docs.conda.io/) or [mamba](https://mamba.readthedocs.io/) (e.g. [Miniforge](https://github.com/conda-forge/miniforge)), for the conda-forge `openusd` package (Hydra/`UsdImagingGL`-enabled — the PyPI `usd-core` wheel is not)
- Python 3.14 and dependencies (see `environment.yml`): `numpy`, `pillow`, `pyopengl`, `openusd`, `pyopengltk` (via pip)

## Installation

```sh
conda env create -f environment.yml
```

### Windows installer

Windows users who don't want to use conda/the terminal can instead install the app via a self-contained `.exe` installer, which adds a "Tkinter USD 3D Viewer" Start Menu shortcut that launches the app directly (no console window, no `conda activate`).

To build the installer yourself:

```sh
conda create -n constructor-build -c conda-forge constructor nsis
conda run -n constructor-build constructor packaging --output-dir packaging/out
```

This produces `packaging/out/TkinterUsdViewer-<version>-Windows-x86_64.exe`. It bundles the same conda-forge packages as `environment.yml` (so it's ~400MB+, mostly `openusd`'s own dependency tree, notably Qt/PySide6 which this app doesn't use but which `openusd` depends on) plus a vendored copy of `pyopengltk` (`packaging/vendor/`, since it's pip-only and not on conda-forge) and this repo's own `.py` files.

## Usage

```sh
conda run -n tkinter-usd-3d-viewer python app.py
```

`conda run` launches the app directly in the environment with no activation step. If you'd rather activate the environment for your terminal session and then just run `python app.py` repeatedly, use `conda activate tkinter-usd-3d-viewer` instead — but note that on Windows, `conda activate` only works in PowerShell/cmd after running `conda init powershell` (or `conda init cmd.exe`) once; it works out of the box in the Anaconda Prompt shortcut the installer creates, or in bash/zsh after `conda init bash`/`conda init zsh`.

Click **Open USD File** to load a stage, then:

| Action | Control |
| --- | --- |
| Orbit | Left-click drag |
| Zoom | Mouse wheel |
| Reset view | "Reset View" button |
| Change shading | "Shading" dropdown |
| Toggle bounding box | "Bounding Box" checkbox |
| Toggle grid | "Grid" checkbox |
| Change background | "Background" dropdown |
| Scrub time | Time slider (enabled when the stage has an authored time-code range) |
| Play/pause animation | "Play" button |

## Project Structure

| File | Responsibility |
| --- | --- |
| `app.py` | Entry point — launches the Tk application |
| `main_window.py` | `USDViewerTk` — the main window: toolbar, playback controls, file loading, and hot-reload |
| `viewport.py` | `USDGLViewport` — the OpenGL Tkinter widget: orbit camera, Hydra (`UsdImagingGL.Engine`) rendering, grid/bbox overlays, mouse input |
| `gl_helpers.py` | Generic OpenGL helper — `Gf.Matrix4d` to `glLoadMatrixd` layout conversion |
| `constants.py` | Shared background-color constants |
| `packaging/` | `constructor` config, vendored `pyopengltk`, and post-install/uninstall scripts for the Windows installer |

## Limitations

- A single fixed directional light is provided as a fallback and is only used by Hydra when the stage authors no `UsdLux` lights of its own
- "Normals" shading mode shows Storm's eye-space normal AOV (`Neye`), not the original's per-vertex world-space RGB visualization — there's no built-in Hydra draw mode for that
- "Foggy" background fog only affects the grid/bounding-box overlay, not Hydra-rendered geometry
