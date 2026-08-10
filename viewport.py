import math

import numpy as np
from OpenGL import GL
from pyopengltk import OpenGLFrame

from pxr import Usd, Gf

from constants import BACKGROUND_COLORS, DEFAULT_COLOR, SKY_HORIZON_COLOR, SKY_TOP_COLOR
from gl_helpers import load_gl_texture, to_gl_matrix
from usd_geometry import (
    extract_triangles,
    extract_lightweight_curves_and_points,
    extract_solid_curves_and_points,
)


class USDGLViewport(OpenGLFrame):
    """An OpenGL-backed Tkinter widget that renders USD mesh geometry
    with a fixed-function orbit camera (no Hydra/UsdImagingGL required)."""

    GRID_EXTENT = 10
    GRID_COLOR = (0.25, 0.25, 0.3)
    DEFAULT_ROT_X = 15.0
    DEFAULT_ROT_Y = 45.0

    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self.animate = 0  # render on demand, not on a timer

        self.groups = []
        self.texture_cache = {}  # resolved file path -> GL texture id

        self.curves_points_mode = "Solid"  # "Solid" | "Lightweight"
        self.point_positions = np.zeros((0, 3), dtype=np.float32)
        self.point_colors = np.zeros((0, 3), dtype=np.float32)
        self.line_positions = np.zeros((0, 3), dtype=np.float32)
        self.line_colors = np.zeros((0, 3), dtype=np.float32)

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
        GL.glEnable(GL.GL_DEPTH_TEST)
        GL.glEnable(GL.GL_LIGHTING)
        GL.glEnable(GL.GL_LIGHT0)
        GL.glLightfv(GL.GL_LIGHT0, GL.GL_POSITION, (5.0, 10.0, 5.0, 0.0))
        GL.glLightfv(GL.GL_LIGHT0, GL.GL_DIFFUSE, (0.9, 0.9, 0.9, 1.0))
        GL.glLightfv(GL.GL_LIGHT0, GL.GL_AMBIENT, (0.15, 0.15, 0.15, 1.0))
        GL.glEnable(GL.GL_COLOR_MATERIAL)
        GL.glColorMaterial(GL.GL_FRONT_AND_BACK, GL.GL_AMBIENT_AND_DIFFUSE)
        GL.glShadeModel(GL.GL_SMOOTH)
        GL.glClearColor(0.0, 0.0, 0.0, 1.0)
        GL.glColor3f(*DEFAULT_COLOR)
        GL.glTexEnvi(GL.GL_TEXTURE_ENV, GL.GL_TEXTURE_ENV_MODE, GL.GL_MODULATE)

    def _load_geometry(self, stage, time_code):
        self.groups = extract_triangles(stage, time_code)
        if self.curves_points_mode == "Solid":
            self.groups += extract_solid_curves_and_points(stage, time_code)
            self.point_positions = np.zeros((0, 3), dtype=np.float32)
            self.point_colors = np.zeros((0, 3), dtype=np.float32)
            self.line_positions = np.zeros((0, 3), dtype=np.float32)
            self.line_colors = np.zeros((0, 3), dtype=np.float32)
        else:
            lightweight = extract_lightweight_curves_and_points(stage, time_code)
            self.point_positions = lightweight["point_positions"]
            self.point_colors = lightweight["point_colors"]
            self.line_positions = lightweight["line_positions"]
            self.line_colors = lightweight["line_colors"]

    def load_stage(self, stage, time_code=Usd.TimeCode.Default()):
        self._load_geometry(stage, time_code)
        self.frame_camera_on_geometry()
        self.tkExpose(None)
        return sum(len(g["positions"]) for g in self.groups) // 3

    def set_time(self, stage, time_code):
        """Re-evaluate geometry at a new time code without touching the camera,
        so scrubbing/playing an animation doesn't jump the view around."""
        self._load_geometry(stage, time_code)
        self.tkExpose(None)

    def frame_camera_on_geometry(self):
        """Recenter and pull the orbit camera back so whatever was just
        loaded is actually in view, regardless of the asset's scale/position."""
        self.rot_x, self.rot_y = self.DEFAULT_ROT_X, self.DEFAULT_ROT_Y

        position_arrays = [g["positions"] for g in self.groups if len(g["positions"])]
        if len(self.point_positions):
            position_arrays.append(self.point_positions)
        if len(self.line_positions):
            position_arrays.append(self.line_positions)
        if not position_arrays:
            self.center = Gf.Vec3d(0, 0, 0)
            self.cam_dist = 10.0
            self.radius = 10.0
            self.bbox_min = None
            self.bbox_max = None
            return

        combined = np.concatenate(position_arrays, axis=0)
        mins = combined.min(axis=0)
        maxs = combined.max(axis=0)
        center = (mins + maxs) / 2.0
        radius = float(np.linalg.norm(maxs - mins)) / 2.0

        self.bbox_min = mins
        self.bbox_max = maxs
        self.center = Gf.Vec3d(*[float(c) for c in center])
        self.radius = radius if radius > 1e-9 else 1.0
        half_fov = math.radians(45.0 / 2.0)
        self.cam_dist = max(1.0, (self.radius / math.sin(half_fov)) * 1.2)

    def get_view_matrix(self):
        center_mat = Gf.Matrix4d().SetTranslate(-self.center)
        rot = Gf.Matrix4d().SetRotate(Gf.Rotation(Gf.Vec3d(1, 0, 0), self.rot_x)) * \
              Gf.Matrix4d().SetRotate(Gf.Rotation(Gf.Vec3d(0, 1, 0), self.rot_y))
        trans = Gf.Matrix4d().SetTranslate(Gf.Vec3d(0, 0, -self.cam_dist))
        return center_mat * rot * trans

    def _get_texture(self, path):
        tex_id = self.texture_cache.get(path)
        if tex_id is None:
            try:
                tex_id = load_gl_texture(path)
            except Exception as exc:
                print(f"Failed to load texture {path}: {exc}")
                tex_id = 0
            self.texture_cache[path] = tex_id
        return tex_id

    def _draw_grid(self):
        """A ground grid + origin axes, drawn unlit so there's always
        something to look at (and orbit/zoom against) even with nothing loaded."""
        extent = max(self.GRID_EXTENT, self.radius * 1.5)
        step = extent / 10.0

        GL.glDisable(GL.GL_LIGHTING)
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
        GL.glEnable(GL.GL_LIGHTING)

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

        GL.glDisable(GL.GL_LIGHTING)
        GL.glDisable(GL.GL_DEPTH_TEST)
        GL.glBegin(GL.GL_QUADS)
        GL.glColor3f(*SKY_HORIZON_COLOR); GL.glVertex2f(0, 0)
        GL.glColor3f(*SKY_HORIZON_COLOR); GL.glVertex2f(1, 0)
        GL.glColor3f(*SKY_TOP_COLOR); GL.glVertex2f(1, 1)
        GL.glColor3f(*SKY_TOP_COLOR); GL.glVertex2f(0, 1)
        GL.glEnd()
        GL.glEnable(GL.GL_DEPTH_TEST)
        GL.glEnable(GL.GL_LIGHTING)

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

        GL.glDisable(GL.GL_LIGHTING)
        GL.glColor3f(1.0, 0.85, 0.2)
        GL.glBegin(GL.GL_LINES)
        for a, b in edges:
            GL.glVertex3f(*corners[a])
            GL.glVertex3f(*corners[b])
        GL.glEnd()
        GL.glEnable(GL.GL_LIGHTING)

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

        GL.glMatrixMode(GL.GL_PROJECTION)
        GL.glLoadIdentity()
        GL.glLoadMatrixd(to_gl_matrix(frustum.ComputeProjectionMatrix()))

        GL.glMatrixMode(GL.GL_MODELVIEW)
        GL.glLoadIdentity()
        GL.glLoadMatrixd(to_gl_matrix(self.get_view_matrix()))

        if self.show_grid:
            self._draw_grid()
        if self.show_bbox:
            self._draw_bbox()

        wireframe = self.shading_mode == "Wireframe"
        show_normals = self.shading_mode == "Normals"
        use_texture_and_vertex_colors = self.shading_mode == "Shaded"

        GL.glPolygonMode(GL.GL_FRONT_AND_BACK, GL.GL_LINE if wireframe else GL.GL_FILL)
        GL.glDisable(GL.GL_LIGHTING) if (wireframe or show_normals) else GL.glEnable(GL.GL_LIGHTING)

        GL.glEnableClientState(GL.GL_VERTEX_ARRAY)
        GL.glEnableClientState(GL.GL_NORMAL_ARRAY)

        for group in self.groups:
            texture_path = group["texture_path"] if use_texture_and_vertex_colors else None
            tex_id = self._get_texture(texture_path) if texture_path else 0

            if tex_id:
                GL.glEnable(GL.GL_TEXTURE_2D)
                GL.glBindTexture(GL.GL_TEXTURE_2D, tex_id)
                GL.glEnableClientState(GL.GL_TEXTURE_COORD_ARRAY)
                GL.glTexCoordPointer(2, GL.GL_FLOAT, 0, group["uvs"])
            else:
                GL.glDisable(GL.GL_TEXTURE_2D)
                GL.glDisableClientState(GL.GL_TEXTURE_COORD_ARRAY)

            GL.glVertexPointer(3, GL.GL_FLOAT, 0, group["positions"])
            GL.glNormalPointer(GL.GL_FLOAT, 0, group["normals"])

            if show_normals:
                GL.glDisableClientState(GL.GL_COLOR_ARRAY)
                normal_colors = group["normals"] * 0.5 + 0.5
                GL.glColorPointer(3, GL.GL_FLOAT, 0, normal_colors)
                GL.glEnableClientState(GL.GL_COLOR_ARRAY)
            elif use_texture_and_vertex_colors:
                GL.glEnableClientState(GL.GL_COLOR_ARRAY)
                GL.glColorPointer(3, GL.GL_FLOAT, 0, group["colors"])
            else:
                GL.glDisableClientState(GL.GL_COLOR_ARRAY)
                GL.glColor3f(*DEFAULT_COLOR)

            GL.glDrawArrays(GL.GL_TRIANGLES, 0, len(group["positions"]))

        GL.glPolygonMode(GL.GL_FRONT_AND_BACK, GL.GL_FILL)
        GL.glEnable(GL.GL_LIGHTING)
        GL.glDisable(GL.GL_TEXTURE_2D)
        GL.glDisableClientState(GL.GL_TEXTURE_COORD_ARRAY)
        GL.glDisableClientState(GL.GL_NORMAL_ARRAY)

        if len(self.point_positions) or len(self.line_positions):
            self._draw_lightweight_curves_and_points()

        GL.glDisableClientState(GL.GL_VERTEX_ARRAY)
        GL.glDisableClientState(GL.GL_COLOR_ARRAY)

    def _draw_lightweight_curves_and_points(self):
        """"Lightweight" mode's Points/BasisCurves representation -- unlit
        GL_POINTS/GL_LINES, drawn outside the shading-mode branching above
        since they're not triangles (no normals to light or triangulate)."""
        GL.glDisable(GL.GL_LIGHTING)
        GL.glEnableClientState(GL.GL_VERTEX_ARRAY)
        GL.glEnableClientState(GL.GL_COLOR_ARRAY)

        if len(self.point_positions):
            GL.glPointSize(6.0)
            GL.glVertexPointer(3, GL.GL_FLOAT, 0, self.point_positions)
            GL.glColorPointer(3, GL.GL_FLOAT, 0, self.point_colors)
            GL.glDrawArrays(GL.GL_POINTS, 0, len(self.point_positions))

        if len(self.line_positions):
            GL.glLineWidth(2.0)
            GL.glVertexPointer(3, GL.GL_FLOAT, 0, self.line_positions)
            GL.glColorPointer(3, GL.GL_FLOAT, 0, self.line_colors)
            GL.glDrawArrays(GL.GL_LINES, 0, len(self.line_positions))

        GL.glEnable(GL.GL_LIGHTING)

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
