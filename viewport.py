import math

from OpenGL import GL
from pyopengltk import OpenGLFrame

from pxr import Usd, UsdGeom, UsdImagingGL, Glf, Gf

import implicit_surfaces
from constants import BACKGROUND_COLORS, SKY_HORIZON_COLOR, SKY_TOP_COLOR
from gl_helpers import to_gl_matrix

# Purposes considered when framing the camera and asking Hydra to draw --
# matches usdview's defaults; "guide" is deliberately left out of both.
BBOX_PURPOSES = [UsdGeom.Tokens.default_, UsdGeom.Tokens.proxy, UsdGeom.Tokens.render]

# A stage's authored upAxis ("Y" or "Z") says which stage-space axis is
# vertical -- it does not change how Hydra renders (Hydra just draws the
# geometry as authored), only how a viewer's camera ought to be oriented.
# Our orbit camera is hardcoded Y-up (see get_view_matrix()/_draw_grid()),
# so a Z-up stage needs this rotation to align its up axis with ours --
# same problem usdview solves by orienting its default camera from this
# same stage metadata.
UP_AXIS_ROTATIONS = {
    UsdGeom.Tokens.z: Gf.Rotation(Gf.Vec3d(1, 0, 0), -90.0),
}

# Hydra has no built-in "visualize vertex normals as RGB" draw mode, so
# "Normals" keeps DRAW_SHADED_SMOOTH's full shading geometry and instead
# swaps the displayed AOV to Storm's eye-space normal buffer ("Neye").
SHADING_DRAW_MODES = {
    "Shaded": UsdImagingGL.DrawMode.DRAW_SHADED_SMOOTH,
    "Solid": UsdImagingGL.DrawMode.DRAW_GEOM_SMOOTH,
    "Wireframe": UsdImagingGL.DrawMode.DRAW_WIREFRAME,
    "Normals": UsdImagingGL.DrawMode.DRAW_SHADED_SMOOTH,
}


class USDGLViewport(OpenGLFrame):
    """An OpenGL-backed Tkinter widget that renders a USD stage through
    Hydra (UsdImagingGL.Engine / Storm), with a hand-rolled orbit camera
    and raw-GL grid/bounding-box overlays composited around it."""

    GRID_EXTENT = 10
    GRID_COLOR = (0.25, 0.25, 0.3)
    DEFAULT_ROT_X = 15.0
    DEFAULT_ROT_Y = 45.0

    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self.animate = 0  # render on demand, not on a timer

        self.engine = None
        self.stage = None
        self.time_code = Usd.TimeCode.Default()
        self.up_axis_rotation = None  # set from the stage's upAxis on load_stage()
        self._implicit_overrides = []  # (path, type_name) pairs from implicit_surfaces.apply_overrides()
        self.tessellation_segments = implicit_surfaces.QUALITY_PRESETS[implicit_surfaces.DEFAULT_QUALITY]

        self.center = Gf.Vec3d(0, 0, 0)
        self.cam_dist = 10.0
        self.radius = 10.0  # half-diagonal of the loaded geometry's bounding box
        self.bbox_min = None
        self.bbox_max = None
        self.rot_x = self.DEFAULT_ROT_X
        self.rot_y = self.DEFAULT_ROT_Y
        self.last_mouse_x = 0
        self.last_mouse_y = 0
        self.last_pan_x = 0
        self.last_pan_y = 0

        self.shading_mode = "Shaded"  # "Shaded" | "Solid" | "Wireframe" | "Normals"
        self.show_bbox = False
        self.show_grid = True
        self.background_mode = "Black"  # "Black" | "Gray" | "Sky" | "Foggy"

        self.bind("<ButtonPress-1>", self.on_mouse_down)
        self.bind("<B1-Motion>", self.on_mouse_drag)
        self.bind("<MouseWheel>", self.on_zoom)
        self.bind("<ButtonPress-2>", self.on_pan_down)
        self.bind("<B2-Motion>", self.on_pan_drag)
        self.bind("<Shift-ButtonPress-1>", self.on_pan_down)
        self.bind("<Shift-B1-Motion>", self.on_pan_drag)

    def initgl(self):
        if self.engine is not None:
            return  # tkResize() calls initgl() again on every resize; the engine survives that
        GL.glEnable(GL.GL_DEPTH_TEST)
        GL.glShadeModel(GL.GL_SMOOTH)
        GL.glClearColor(0.0, 0.0, 0.0, 1.0)

        self._create_engine()

    def _create_engine(self):
        """A fresh UsdImagingGL.Engine has its own Hydra render index -- it
        must be rebuilt whenever a *different* stage is loaded, or leftover
        state from the previous stage corrupts the render (this is also why
        usdview's own _closeStage() drops its renderer before opening the
        next file). Not needed for time/camera changes on the same stage."""
        self.tkMakeCurrent()
        self.engine = UsdImagingGL.Engine()
        self._set_lighting_state()

    def _set_lighting_state(self):
        """A single strong, sun-like directional light, standing in for a
        scene light when the stage doesn't author its own (UsdImagingGL
        falls back to this only when the stage has no UsdLux lights).

        The previous values here (diffuse=1.4, sceneAmbient=0.3) rendered so
        dimly -- barely brighter than the material's own unlit response --
        that changing the background color was hard to even perceive.
        Boosted well past that, with a slightly warm key and a slightly
        cool, dim ambient fill (real sky-fill, not a flat gray wash) so the
        shadowed side still reads as *a side in shadow* rather than pure
        black."""
        light = Glf.SimpleLight()
        light.position = Gf.Vec4f(5.0, 10.0, 5.0, 0.0)
        light.diffuse = Gf.Vec4f(3.2, 3.05, 2.85, 1.0)
        light.specular = Gf.Vec4f(2.0, 2.0, 2.0, 1.0)
        light.ambient = Gf.Vec4f(0.0, 0.0, 0.0, 1.0)
        material = Glf.SimpleMaterial()
        scene_ambient = Gf.Vec4f(0.15, 0.16, 0.18, 1.0)
        self.engine.SetLightingState([light], material, scene_ambient)

    def load_stage(self, stage, time_code=Usd.TimeCode.Default()):
        self.stage = stage
        self.time_code = time_code
        self.up_axis_rotation = UP_AXIS_ROTATIONS.get(UsdGeom.GetStageUpAxis(stage))
        # Hydra tessellates Cylinder/Cone/Capsule/Sphere to a single fixed,
        # low-poly mesh no matter the render settings -- there's no knob for
        # it anywhere in UsdImagingGL. Replace them with our own, much finer
        # tessellation, authored non-destructively on the session layer (see
        # implicit_surfaces.py) so Hydra renders that instead.
        self._implicit_overrides = implicit_surfaces.apply_overrides(stage, time_code, self.tessellation_segments)
        if self.engine is not None:
            self._create_engine()
        self.frame_camera_on_geometry()
        self.tkExpose(None)

    def set_time(self, stage, time_code):
        """Point Hydra at a new time code without touching the camera, so
        scrubbing/playing an animation doesn't jump the view around."""
        self.stage = stage
        self.time_code = time_code
        # Also covers hot-reload: main_window calls this (not load_stage())
        # after Reload()-ing the same stage, so this is the only place a
        # hand-edited static radius/height on an already-discovered prim
        # gets picked back up.
        if self._implicit_overrides:
            implicit_surfaces.refresh_overrides(stage, self._implicit_overrides, time_code, self.tessellation_segments)
        self.tkExpose(None)

    def set_tessellation_segments(self, segments):
        """Change the implicit-surface tessellation density (see the
        "Quality" dropdown in main_window.py) and, if a stage is already
        loaded, immediately re-tessellate it at the new resolution.

        Uses refresh_overrides() (topology_too=True), not apply_overrides()
        -- the prims to update are already typed "Mesh" from the initial
        load_stage() pass, so re-traversing the stage looking for
        Cylinder/Cone/Capsule/Sphere prims would find nothing."""
        self.tessellation_segments = segments
        if self.stage is not None and self._implicit_overrides:
            implicit_surfaces.refresh_overrides(
                self.stage, self._implicit_overrides, self.time_code,
                self.tessellation_segments, topology_too=True)
            self.tkExpose(None)

    def frame_camera_on_geometry(self):
        """Recenter and pull the orbit camera back so whatever was just
        loaded is actually in view, regardless of the asset's scale/position."""
        self.rot_x, self.rot_y = self.DEFAULT_ROT_X, self.DEFAULT_ROT_Y

        bbox_cache = UsdGeom.BBoxCache(self.time_code, BBOX_PURPOSES)
        world_range = bbox_cache.ComputeWorldBound(self.stage.GetPseudoRoot()).ComputeAlignedRange()

        if world_range.IsEmpty():
            self.center = Gf.Vec3d(0, 0, 0)
            self.cam_dist = 10.0
            self.radius = 10.0
            self.bbox_min = None
            self.bbox_max = None
            return

        mins, maxs = world_range.GetMin(), world_range.GetMax()
        radius = world_range.GetSize().GetLength() / 2.0

        # bbox_min/bbox_max/center are kept in *display* space (Y-up, matching
        # the grid) rather than raw stage space, so the bbox overlay -- drawn
        # with the same plain, up-axis-agnostic get_view_matrix() as the grid
        # -- lines up with the (separately axis-corrected) Hydra geometry
        # instead of floating at an unrelated angle to it.
        if self.up_axis_rotation is not None:
            up_axis_mat = Gf.Matrix4d().SetRotate(self.up_axis_rotation)
            r_mins, r_maxs = up_axis_mat.Transform(mins), up_axis_mat.Transform(maxs)
            mins = Gf.Vec3d(*(min(a, b) for a, b in zip(r_mins, r_maxs)))
            maxs = Gf.Vec3d(*(max(a, b) for a, b in zip(r_mins, r_maxs)))

        self.bbox_min = mins
        self.bbox_max = maxs
        self.center = (mins + maxs) / 2.0
        self.radius = radius if radius > 1e-9 else 1.0
        half_fov = math.radians(45.0 / 2.0)
        self.cam_dist = max(1.0, (self.radius / math.sin(half_fov)) * 1.2)

    def get_view_matrix(self):
        """The shared camera used for the grid and bounding-box overlay --
        both already in display space (Y-up). Hydra's camera additionally
        prepends the up-axis correction; see _render_stage()."""
        center_mat = Gf.Matrix4d().SetTranslate(-self.center)
        rot = Gf.Matrix4d().SetRotate(Gf.Rotation(Gf.Vec3d(1, 0, 0), self.rot_x)) * \
              Gf.Matrix4d().SetRotate(Gf.Rotation(Gf.Vec3d(0, 1, 0), self.rot_y))
        trans = Gf.Matrix4d().SetTranslate(Gf.Vec3d(0, 0, -self.cam_dist))
        return center_mat * rot * trans

    def _draw_grid(self):
        """A ground grid + origin axes, drawn unlit so there's always
        something to look at (and orbit/zoom against) even with nothing loaded."""
        extent = max(self.GRID_EXTENT, self.radius * 1.5)
        step = extent / 10.0

        GL.glColor3f(*self.GRID_COLOR)
        GL.glBegin(GL.GL_LINES)
        i = -extent
        while i <= extent + 1e-6:
            GL.glVertex3f(i, 0.0, -extent)
            GL.glVertex3f(i, 0.0, extent)
            GL.glVertex3f(-extent, 0.0, i)
            GL.glVertex3f(extent, 0.0, i)
            i += step
        GL.glEnd()

        GL.glBegin(GL.GL_LINES)
        GL.glColor3f(0.8, 0.2, 0.2)
        GL.glVertex3f(0, 0, 0); GL.glVertex3f(extent * 0.3, 0, 0)
        GL.glColor3f(0.2, 0.8, 0.2)
        GL.glVertex3f(0, 0, 0); GL.glVertex3f(0, extent * 0.3, 0)
        GL.glColor3f(0.2, 0.4, 0.9)
        GL.glVertex3f(0, 0, 0); GL.glVertex3f(0, 0, extent * 0.3)
        GL.glEnd()

    def _draw_sky_gradient(self):
        """Full-screen vertical gradient (horizon -> sky blue), drawn as an
        unlit ortho quad behind everything else, for the "Sky" background mode."""
        GL.glMatrixMode(GL.GL_PROJECTION)
        GL.glPushMatrix()
        GL.glLoadIdentity()
        GL.glOrtho(0, 1, 0, 1, -1, 1)
        GL.glMatrixMode(GL.GL_MODELVIEW)
        GL.glPushMatrix()
        GL.glLoadIdentity()

        GL.glDisable(GL.GL_DEPTH_TEST)
        GL.glBegin(GL.GL_QUADS)
        GL.glColor3f(*SKY_HORIZON_COLOR); GL.glVertex2f(0, 0)
        GL.glColor3f(*SKY_HORIZON_COLOR); GL.glVertex2f(1, 0)
        GL.glColor3f(*SKY_TOP_COLOR); GL.glVertex2f(1, 1)
        GL.glColor3f(*SKY_TOP_COLOR); GL.glVertex2f(0, 1)
        GL.glEnd()
        GL.glEnable(GL.GL_DEPTH_TEST)

        GL.glPopMatrix()
        GL.glMatrixMode(GL.GL_PROJECTION)
        GL.glPopMatrix()
        GL.glMatrixMode(GL.GL_MODELVIEW)

    def _draw_bbox(self):
        """Wireframe box around the loaded geometry's world-space bounding box."""
        if self.bbox_min is None:
            return

        x0, y0, z0 = self.bbox_min
        x1, y1, z1 = self.bbox_max
        corners = [
            (x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
            (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1),
        ]
        edges = [(0, 1), (1, 2), (2, 3), (3, 0), (4, 5), (5, 6), (6, 7), (7, 4),
                 (0, 4), (1, 5), (2, 6), (3, 7)]

        GL.glColor3f(1.0, 0.85, 0.2)
        GL.glBegin(GL.GL_LINES)
        for a, b in edges:
            GL.glVertex3f(*corners[a])
            GL.glVertex3f(*corners[b])
        GL.glEnd()

    def _render_stage(self, view_matrix, projection_matrix, width, height):
        # Unlike the grid/bbox overlay, Hydra draws the stage's own raw
        # (un-corrected) geometry, so its camera needs the up-axis rotation
        # prepended here -- see the UP_AXIS_ROTATIONS comment above.
        if self.up_axis_rotation is not None:
            view_matrix = Gf.Matrix4d().SetRotate(self.up_axis_rotation) * view_matrix

        self.engine.SetRenderViewport((0, 0, width, height))
        self.engine.SetCameraState(view_matrix, projection_matrix)
        self.engine.SetRendererAov("Neye" if self.shading_mode == "Normals" else "color")

        params = UsdImagingGL.RenderParams()
        params.frame = self.time_code
        params.drawMode = SHADING_DRAW_MODES[self.shading_mode]
        params.enableSceneMaterials = self.shading_mode == "Shaded"
        # RenderParams.clearColor defaults to opaque black, and Hydra clears
        # the *entire* viewport to it when compositing -- not just the parts
        # it draws geometry into. Left alone, that silently overwrites
        # whatever background redraw() already drew (solid color or the sky
        # gradient) with flat black the moment any stage is loaded, no
        # matter what background_mode is selected. Matching it to our
        # chosen background makes Hydra's own clear indistinguishable from
        # ours for the solid modes; "Sky" has no single color to match
        # (it's a gradient), so its horizon color is the closest Hydra's
        # clear can represent.
        clear_rgb = SKY_HORIZON_COLOR if self.background_mode == "Sky" else \
            BACKGROUND_COLORS.get(self.background_mode, BACKGROUND_COLORS["Black"])
        params.clearColor = Gf.Vec4f(*clear_rgb, 1.0)
        self.engine.Render(self.stage.GetPseudoRoot(), params)

    def redraw(self):
        width = max(1, self.winfo_width())
        height = max(1, self.winfo_height())
        GL.glViewport(0, 0, width, height)

        clear_color = BACKGROUND_COLORS.get(self.background_mode, BACKGROUND_COLORS["Black"])
        GL.glClearColor(*clear_color, 1.0)
        GL.glClear(GL.GL_COLOR_BUFFER_BIT | GL.GL_DEPTH_BUFFER_BIT)

        if self.background_mode == "Sky":
            self._draw_sky_gradient()

        if self.background_mode == "Foggy":
            # Fixed-function fog only affects the grid/bbox overlays below --
            # Hydra's Storm shaders don't read legacy GL_FOG state.
            GL.glEnable(GL.GL_FOG)
            GL.glFogi(GL.GL_FOG_MODE, GL.GL_LINEAR)
            GL.glFogfv(GL.GL_FOG_COLOR, (*BACKGROUND_COLORS["Foggy"], 1.0))
            GL.glFogf(GL.GL_FOG_START, max(0.0, self.cam_dist - self.radius * 1.5))
            GL.glFogf(GL.GL_FOG_END, self.cam_dist + self.radius * 1.5)
        else:
            GL.glDisable(GL.GL_FOG)

        # Bracket near/far around the current camera distance with margin for
        # the object's own extent -- a fixed range clips anything framed or
        # zoomed outside it.
        near = max(self.cam_dist * 0.001, self.cam_dist - self.radius * 2.0)
        far = self.cam_dist + self.radius * 2.0

        frustum = Gf.Frustum()
        frustum.SetPerspective(45.0, width / height, near, far)
        view_matrix = self.get_view_matrix()
        projection_matrix = frustum.ComputeProjectionMatrix()

        GL.glMatrixMode(GL.GL_PROJECTION)
        GL.glLoadIdentity()
        GL.glLoadMatrixd(to_gl_matrix(projection_matrix))

        GL.glMatrixMode(GL.GL_MODELVIEW)
        GL.glLoadIdentity()
        GL.glLoadMatrixd(to_gl_matrix(view_matrix))

        if self.show_grid:
            self._draw_grid()
        if self.show_bbox:
            self._draw_bbox()

        if self.stage is not None:
            self._render_stage(view_matrix, projection_matrix, width, height)

    # Mouse Control Callbacks
    def on_mouse_down(self, event):
        self.last_mouse_x = event.x
        self.last_mouse_y = event.y

    def on_mouse_drag(self, event):
        dx = event.x - self.last_mouse_x
        dy = event.y - self.last_mouse_y

        self.rot_y += dx * 0.5
        self.rot_x += dy * 0.5

        self.last_mouse_x = event.x
        self.last_mouse_y = event.y
        self.tkExpose(None)

    def on_zoom(self, event):
        # Relative (percentage) zoom rather than a fixed +/-0.5 step, so it
        # scales with the loaded asset -- a fixed step is imperceptibly slow
        # on a huge object and overshoots straight past a tiny one. The min
        # distance allows getting far closer than before (~5x tighter than
        # the old hard 1.0 floor, relative to the object's own size).
        factor = 0.85 if event.delta > 0 else 1.0 / 0.85
        min_dist = max(self.radius * 0.01, 1e-4)
        max_dist = self.radius * 100.0
        self.cam_dist = min(max(self.cam_dist * factor, min_dist), max_dist)
        self.tkExpose(None)

    def _camera_right_up(self):
        """World-space (display-space; see UP_AXIS_ROTATIONS) right/up unit
        vectors for the camera's current orbit orientation, used to convert
        a screen-space pan drag into a world-space offset for self.center."""
        rot = Gf.Matrix4d().SetRotate(Gf.Rotation(Gf.Vec3d(1, 0, 0), self.rot_x)) * \
              Gf.Matrix4d().SetRotate(Gf.Rotation(Gf.Vec3d(0, 1, 0), self.rot_y))
        inv_rot = rot.GetInverse()
        return inv_rot.TransformDir(Gf.Vec3d(1, 0, 0)), inv_rot.TransformDir(Gf.Vec3d(0, 1, 0))

    def on_pan_down(self, event):
        self.last_pan_x = event.x
        self.last_pan_y = event.y

    def on_pan_drag(self, event):
        dx = event.x - self.last_pan_x
        dy = event.y - self.last_pan_y

        # Scale by the world-space distance a single pixel covers at the
        # camera's current distance/FOV, so a drag pans by the same visible
        # fraction of the view regardless of zoom level or window size.
        half_fov = math.radians(45.0 / 2.0)
        world_per_pixel = (2.0 * self.cam_dist * math.tan(half_fov)) / max(1, self.winfo_height())

        right, up = self._camera_right_up()
        self.center = self.center - right * dx * world_per_pixel + up * dy * world_per_pixel

        self.last_pan_x = event.x
        self.last_pan_y = event.y
        self.tkExpose(None)
