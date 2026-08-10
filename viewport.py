import math

from OpenGL import GL
from pyopengltk import OpenGLFrame

from pxr import Usd, UsdGeom, UsdImagingGL, Glf, Gf

from constants import BACKGROUND_COLORS, SKY_HORIZON_COLOR, SKY_TOP_COLOR
from gl_helpers import to_gl_matrix

# Purposes considered when framing the camera and asking Hydra to draw --
# matches usdview's defaults; "guide" is deliberately left out of both.
BBOX_PURPOSES = [UsdGeom.Tokens.default_, UsdGeom.Tokens.proxy, UsdGeom.Tokens.render]

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

        self.center = Gf.Vec3d(0, 0, 0)
        self.cam_dist = 10.0
        self.radius = 10.0  # half-diagonal of the loaded geometry's bounding box
        self.bbox_min = None
        self.bbox_max = None
        self.rot_x = self.DEFAULT_ROT_X
        self.rot_y = self.DEFAULT_ROT_Y
        self.last_mouse_x = 0
        self.last_mouse_y = 0

        self.shading_mode = "Shaded"  # "Shaded" | "Solid" | "Wireframe" | "Normals"
        self.show_bbox = False
        self.show_grid = True
        self.background_mode = "Black"  # "Black" | "Gray" | "Sky" | "Foggy"

        self.bind("<ButtonPress-1>", self.on_mouse_down)
        self.bind("<B1-Motion>", self.on_mouse_drag)
        self.bind("<MouseWheel>", self.on_zoom)

    def initgl(self):
        if self.engine is not None:
            return  # tkResize() calls initgl() again on every resize; the engine survives that
        GL.glEnable(GL.GL_DEPTH_TEST)
        GL.glShadeModel(GL.GL_SMOOTH)
        GL.glClearColor(0.0, 0.0, 0.0, 1.0)

        self.engine = UsdImagingGL.Engine()
        self._set_lighting_state()

    def _set_lighting_state(self):
        """A single fixed directional light, standing in for a scene light
        when the stage doesn't author its own (UsdImagingGL falls back to
        this only when the stage has no UsdLux lights)."""
        light = Glf.SimpleLight()
        light.position = Gf.Vec4f(5.0, 10.0, 5.0, 0.0)
        light.diffuse = Gf.Vec4f(0.9, 0.9, 0.9, 1.0)
        light.ambient = Gf.Vec4f(0.0, 0.0, 0.0, 1.0)
        material = Glf.SimpleMaterial()
        scene_ambient = Gf.Vec4f(0.15, 0.15, 0.15, 1.0)
        self.engine.SetLightingState([light], material, scene_ambient)

    def load_stage(self, stage, time_code=Usd.TimeCode.Default()):
        self.stage = stage
        self.time_code = time_code
        self.frame_camera_on_geometry()
        self.tkExpose(None)

    def set_time(self, stage, time_code):
        """Point Hydra at a new time code without touching the camera, so
        scrubbing/playing an animation doesn't jump the view around."""
        self.stage = stage
        self.time_code = time_code
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

        self.bbox_min = mins
        self.bbox_max = maxs
        self.center = (mins + maxs) / 2.0
        self.radius = radius if radius > 1e-9 else 1.0
        half_fov = math.radians(45.0 / 2.0)
        self.cam_dist = max(1.0, (self.radius / math.sin(half_fov)) * 1.2)

    def get_view_matrix(self):
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
        self.engine.SetRenderViewport((0, 0, width, height))
        self.engine.SetCameraState(view_matrix, projection_matrix)
        self.engine.SetRendererAov("Neye" if self.shading_mode == "Normals" else "color")

        params = UsdImagingGL.RenderParams()
        params.frame = self.time_code
        params.drawMode = SHADING_DRAW_MODES[self.shading_mode]
        params.enableSceneMaterials = self.shading_mode == "Shaded"
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
