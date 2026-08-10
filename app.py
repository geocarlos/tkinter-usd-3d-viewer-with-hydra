import math
import os
import tkinter as tk
from tkinter import filedialog

import numpy as np
from OpenGL import GL
from PIL import Image
from pyopengltk import OpenGLFrame

# OpenUSD modules
from pxr import Usd, UsdGeom, UsdShade, Gf

DEFAULT_COLOR = (0.7, 0.7, 0.8)
WHITE_COLOR = (1.0, 1.0, 1.0)

BACKGROUND_COLORS = {
    "Black": (0.0, 0.0, 0.0),
    "Gray": (0.5, 0.5, 0.5),
    "Foggy": (0.75, 0.75, 0.78),
}
SKY_HORIZON_COLOR = (0.82, 0.88, 0.95)
SKY_TOP_COLOR = (0.35, 0.55, 0.9)


def _to_gl_matrix(matrix4d):
    """Column-major flattening of a Gf.Matrix4d (row-vector convention) into
    the layout glLoadMatrixd expects for column-vector GL math -- i.e. the
    transpose of Gf's row-major storage, transposed by hand here rather than
    via glLoadTransposeMatrixd, which some drivers (e.g. Intel/Windows) accept
    without error but silently fail to apply."""
    rows = [list(row) for row in matrix4d]
    return [rows[col][row] for col in range(4) for row in range(4)]


def cube_faces(size):
    """Points/faceVertexCounts/faceVertexIndices for a UsdGeom.Cube of the given edge length."""
    h = size / 2.0
    points = [
        (-h, -h, -h), (h, -h, -h), (h, h, -h), (-h, h, -h),
        (-h, -h, h), (h, -h, h), (h, h, h), (-h, h, h),
    ]
    faces = [
        (0, 1, 2, 3), (5, 4, 7, 6), (4, 0, 3, 7),
        (1, 5, 6, 2), (3, 2, 6, 7), (4, 5, 1, 0),
    ]
    counts = [len(f) for f in faces]
    indices = [i for f in faces for i in f]
    return points, counts, indices


def sphere_faces(radius, rings=12, segments=16):
    """Points/faceVertexCounts/faceVertexIndices for a UsdGeom.Sphere, as a UV sphere."""
    points = []
    for i in range(rings + 1):
        theta = math.pi * i / rings
        for j in range(segments):
            phi = 2.0 * math.pi * j / segments
            points.append((
                radius * math.sin(theta) * math.cos(phi),
                radius * math.cos(theta),
                radius * math.sin(theta) * math.sin(phi),
            ))

    counts = []
    indices = []
    for i in range(rings):
        for j in range(segments):
            j_next = (j + 1) % segments
            top_left = i * segments + j
            top_right = i * segments + j_next
            bot_left = (i + 1) * segments + j
            bot_right = (i + 1) * segments + j_next
            if i == 0:
                counts.append(3)
                indices.extend((top_left, bot_left, bot_right))
            elif i == rings - 1:
                counts.append(3)
                indices.extend((top_left, bot_left, top_right))
            else:
                counts.append(4)
                indices.extend((top_left, bot_left, bot_right, top_right))

    return points, counts, indices


def get_display_colors(prim, time_code):
    """Returns (interpolation, flattened Vt.Vec3fArray) for a Gprim's
    displayColor primvar, or (None, None) if none is authored."""
    primvar = UsdGeom.Gprim(prim).GetDisplayColorPrimvar()
    if not primvar or not primvar.GetAttr().HasAuthoredValue():
        return None, None

    values = primvar.ComputeFlattened(time_code)
    if not values:
        return None, None

    return primvar.GetInterpolation(), values


def get_uv_coords(prim, time_code):
    """Returns (interpolation, flattened Vt.Vec2fArray) for a prim's "st"
    UV primvar, or (None, None) if none is authored."""
    primvar = UsdGeom.PrimvarsAPI(prim).GetPrimvar("st")
    if not primvar or not primvar.GetAttr().HasAuthoredValue():
        return None, None

    values = primvar.ComputeFlattened(time_code)
    if not values:
        return None, None

    return primvar.GetInterpolation(), values


def resolve_prim_texture_and_tint(prim):
    """Walks a prim's bound UsdPreviewSurface to find its diffuseColor input.
    Returns (resolved texture file path, None) if diffuseColor is fed by a
    UsdUVTexture, or (None, constant tint) if it's just a constant color."""
    material, _ = UsdShade.MaterialBindingAPI(prim).ComputeBoundMaterial()
    if not material:
        return None, None

    surface_output = material.GetSurfaceOutput()
    source = surface_output.GetConnectedSource() if surface_output else None
    if not source:
        return None, None

    diffuse_input = UsdShade.Shader(source[0]).GetInput("diffuseColor")
    if not diffuse_input:
        return None, None

    connected, _ = diffuse_input.GetConnectedSources()
    if connected:
        tex_shader = UsdShade.Shader(connected[0].source.GetPrim())
        file_input = tex_shader.GetInput("file")
        asset_path = file_input.Get() if file_input else None
        if asset_path and asset_path.resolvedPath:
            return asset_path.resolvedPath, None

    value = diffuse_input.Get()
    return None, (tuple(value) if value is not None else None)


def load_gl_texture(path):
    """Loads an image file and uploads it as a GL texture, returning its id."""
    image = Image.open(path).convert("RGB").transpose(Image.Transpose.FLIP_TOP_BOTTOM)
    width, height = image.size
    data = image.tobytes()

    tex_id = GL.glGenTextures(1)
    GL.glBindTexture(GL.GL_TEXTURE_2D, tex_id)
    GL.glPixelStorei(GL.GL_UNPACK_ALIGNMENT, 1)
    GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_S, GL.GL_REPEAT)
    GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_T, GL.GL_REPEAT)
    GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MIN_FILTER, GL.GL_LINEAR_MIPMAP_LINEAR)
    GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MAG_FILTER, GL.GL_LINEAR)
    GL.glTexImage2D(GL.GL_TEXTURE_2D, 0, GL.GL_RGB, width, height, 0,
                     GL.GL_RGB, GL.GL_UNSIGNED_BYTE, data)
    GL.glGenerateMipmap(GL.GL_TEXTURE_2D)
    return tex_id


def _corner_value(interp, values, indices, corner_offset, local_index, face_index, fallback):
    if interp is None or values is None:
        return fallback
    if interp == "constant":
        return values[0]
    if interp == "uniform":
        return values[face_index]
    if interp == "faceVarying":
        return values[corner_offset + local_index]
    # "vertex" / "varying": indexed by point, like the points array itself.
    return values[indices[corner_offset + local_index]]


def _triangulate(points, counts, indices, xform, color_interp, color_values,
                  uv_interp, uv_values, positions, normals, colors, uvs):
    """Fan-triangulate polygon faces into world-space position/normal/color/uv
    quadruples, appending onto the given lists. Only correct for convex faces."""
    world_points = [xform.Transform(Gf.Vec3d(*p)) for p in points]

    offset = 0
    for face_index, count in enumerate(counts):
        face = indices[offset:offset + count]
        corner_offset = offset
        offset += count

        a = world_points[face[0]]
        color_a = _corner_value(color_interp, color_values, indices, corner_offset, 0, face_index, DEFAULT_COLOR)
        uv_a = _corner_value(uv_interp, uv_values, indices, corner_offset, 0, face_index, (0.0, 0.0))
        for i in range(1, count - 1):
            b = world_points[face[i]]
            c = world_points[face[i + 1]]
            color_b = _corner_value(color_interp, color_values, indices, corner_offset, i, face_index, DEFAULT_COLOR)
            color_c = _corner_value(color_interp, color_values, indices, corner_offset, i + 1, face_index, DEFAULT_COLOR)
            uv_b = _corner_value(uv_interp, uv_values, indices, corner_offset, i, face_index, (0.0, 0.0))
            uv_c = _corner_value(uv_interp, uv_values, indices, corner_offset, i + 1, face_index, (0.0, 0.0))

            normal = Gf.Cross(b - a, c - a)
            length = normal.GetLength()
            if length > 1e-12:
                normal /= length

            positions.extend((a, b, c))
            normals.extend((normal, normal, normal))
            colors.extend((color_a, color_b, color_c))
            uvs.extend((uv_a, uv_b, uv_c))


def extract_triangles(stage, time_code=Usd.TimeCode.Default()):
    """Walk the stage's Mesh, Cube, and Sphere prims and fan-triangulate them,
    grouped by bound diffuse texture (or None) so each group can be drawn with
    its own texture bound in a single glDrawArrays call."""
    groups = {}

    def group_for(texture_path):
        if texture_path not in groups:
            groups[texture_path] = {"positions": [], "normals": [], "colors": [], "uvs": []}
        return groups[texture_path]

    for prim in stage.Traverse():
        xform = UsdGeom.Xformable(prim).ComputeLocalToWorldTransform(time_code)

        if prim.IsA(UsdGeom.Mesh):
            mesh = UsdGeom.Mesh(prim)
            points = mesh.GetPointsAttr().Get(time_code)
            counts = mesh.GetFaceVertexCountsAttr().Get(time_code)
            indices = mesh.GetFaceVertexIndicesAttr().Get(time_code)
            if not points or not counts or not indices:
                continue

        elif prim.IsA(UsdGeom.Cube):
            size = UsdGeom.Cube(prim).GetSizeAttr().Get(time_code) or 2.0
            points, counts, indices = cube_faces(size)

        elif prim.IsA(UsdGeom.Sphere):
            radius = UsdGeom.Sphere(prim).GetRadiusAttr().Get(time_code) or 1.0
            points, counts, indices = sphere_faces(radius)

        else:
            continue

        texture_path, tint = resolve_prim_texture_and_tint(prim)

        color_interp, color_values = get_display_colors(prim, time_code)
        if texture_path is not None:
            # A texture supplies its own color; a stale displayColor fallback
            # (common as a viewport-only preview tint) would otherwise darken it.
            color_interp, color_values = "constant", [WHITE_COLOR]
        elif color_interp is None and tint is not None:
            color_interp, color_values = "constant", [tint]

        uv_interp, uv_values = get_uv_coords(prim, time_code) if texture_path else (None, None)

        group = group_for(texture_path)
        _triangulate(points, counts, indices, xform, color_interp, color_values,
                     uv_interp, uv_values,
                     group["positions"], group["normals"], group["colors"], group["uvs"])

    result = []
    for texture_path, group in groups.items():
        if not group["positions"]:
            continue
        result.append({
            "texture_path": texture_path,
            "positions": np.array(group["positions"], dtype=np.float32),
            "normals": np.array(group["normals"], dtype=np.float32),
            "colors": np.array(group["colors"], dtype=np.float32),
            "uvs": np.array(group["uvs"], dtype=np.float32),
        })
    return result


class USDGLViewport(OpenGLFrame):
    """An OpenGL-backed Tkinter widget that renders USD mesh geometry
    with a fixed-function orbit camera (no Hydra/UsdImagingGL required)."""

    GRID_EXTENT = 10
    GRID_COLOR = (0.25, 0.25, 0.3)

    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self.animate = 0  # render on demand, not on a timer

        self.groups = []
        self.texture_cache = {}  # resolved file path -> GL texture id

        self.center = Gf.Vec3d(0, 0, 0)
        self.cam_dist = 10.0
        self.radius = 10.0  # half-diagonal of the loaded geometry's bounding box
        self.bbox_min = None
        self.bbox_max = None
        self.rot_x = 30.0
        self.rot_y = 45.0
        self.last_mouse_x = 0
        self.last_mouse_y = 0

        self.shading_mode = "Shaded"  # "Shaded" | "Solid" | "Wireframe" | "Normals"
        self.show_bbox = False
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

    def load_stage(self, stage, time_code=Usd.TimeCode.Default()):
        self.groups = extract_triangles(stage, time_code)
        self.frame_camera_on_geometry()
        self.tkExpose(None)
        return sum(len(g["positions"]) for g in self.groups) // 3

    def set_time(self, stage, time_code):
        """Re-evaluate geometry at a new time code without touching the camera,
        so scrubbing/playing an animation doesn't jump the view around."""
        self.groups = extract_triangles(stage, time_code)
        self.tkExpose(None)

    def frame_camera_on_geometry(self):
        """Recenter and pull the orbit camera back so whatever was just
        loaded is actually in view, regardless of the asset's scale/position."""
        self.rot_x, self.rot_y = 30.0, 45.0

        position_arrays = [g["positions"] for g in self.groups if len(g["positions"])]
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
        GL.glLoadMatrixd(_to_gl_matrix(frustum.ComputeProjectionMatrix()))

        GL.glMatrixMode(GL.GL_MODELVIEW)
        GL.glLoadIdentity()
        GL.glLoadMatrixd(_to_gl_matrix(self.get_view_matrix()))

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
        GL.glDisableClientState(GL.GL_VERTEX_ARRAY)
        GL.glDisableClientState(GL.GL_NORMAL_ARRAY)
        GL.glDisableClientState(GL.GL_COLOR_ARRAY)

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


class USDViewerTk(tk.Tk):
    def __init__(self, width=800, height=600):
        super().__init__()
        self.title("Tkinter USD 3D Viewer")
        self.geometry(f"{width}x{height}")

        self.open_bar = tk.Frame(self)
        self.open_bar.pack(side=tk.TOP, pady=5)

        self.lbl_filename = tk.Label(self.open_bar, text="")
        self.lbl_filename.pack(side=tk.LEFT, padx=(0, 8))

        self.btn_open = tk.Button(self.open_bar, text="Open USD File", command=self.load_file)
        self.btn_open.pack(side=tk.LEFT)

        self.toolbar = tk.Frame(self)
        self.toolbar.pack(side=tk.TOP, fill=tk.X, padx=5, pady=(0, 5))

        tk.Label(self.toolbar, text="Shading:").pack(side=tk.LEFT)
        self.shading_var = tk.StringVar(value="Shaded")
        self.shading_menu = tk.OptionMenu(self.toolbar, self.shading_var,
                                           "Shaded", "Solid", "Wireframe", "Normals",
                                           command=self.on_shading_changed)
        self.shading_menu.pack(side=tk.LEFT, padx=(2, 10))

        self.btn_reset_view = tk.Button(self.toolbar, text="Reset View", command=self.reset_view)
        self.btn_reset_view.pack(side=tk.LEFT, padx=(0, 10))

        self.show_bbox_var = tk.BooleanVar(value=False)
        self.chk_bbox = tk.Checkbutton(self.toolbar, text="Bounding Box",
                                        variable=self.show_bbox_var, command=self.on_bbox_toggled)
        self.chk_bbox.pack(side=tk.LEFT, padx=(0, 10))

        tk.Label(self.toolbar, text="Background:").pack(side=tk.LEFT)
        self.background_var = tk.StringVar(value="Black")
        self.background_menu = tk.OptionMenu(self.toolbar, self.background_var,
                                              "Black", "Gray", "Sky", "Foggy",
                                              command=self.on_background_changed)
        self.background_menu.pack(side=tk.LEFT, padx=(2, 0))

        self.viewport = USDGLViewport(self, width=width, height=height)
        self.viewport.pack(fill=tk.BOTH, expand=True)

        self.playback = tk.Frame(self)
        self.playback.pack(side=tk.BOTTOM, fill=tk.X, padx=5, pady=2)

        self.btn_play = tk.Button(self.playback, text="Play", width=6,
                                   command=self.toggle_play, state=tk.DISABLED)
        self.btn_play.pack(side=tk.LEFT)

        self.time_var = tk.DoubleVar(value=0.0)
        self.time_slider = tk.Scale(self.playback, orient=tk.HORIZONTAL,
                                     from_=0.0, to=0.0, showvalue=False,
                                     variable=self.time_var, command=self.on_scrub,
                                     state=tk.DISABLED)
        self.time_slider.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)

        self.status = tk.Label(self, text="No file loaded", anchor=tk.W)
        self.status.pack(side=tk.BOTTOM, fill=tk.X, padx=5, pady=2)

        self.stage = None
        self.stage_path = None
        self.stage_mtime = None
        self.playing = False
        self.fps = 24.0
        self._play_job = None

        self.after(1000, self._check_hot_reload)

    def _check_hot_reload(self):
        if self.stage_path:
            try:
                mtime = os.path.getmtime(self.stage_path)
            except OSError:
                mtime = self.stage_mtime
            if mtime != self.stage_mtime:
                self._reload_current_file(mtime)
        self.after(1000, self._check_hot_reload)

    def _reload_current_file(self, mtime):
        # Usd.Stage.Open() on a path that's already loaded returns the cached
        # in-memory layer, not a fresh read from disk -- Reload() is the actual
        # API for picking up on-disk changes to a layer that's already open.
        #
        # Advance stage_mtime unconditionally (success or failure) so a save
        # that fails to load is not retried every second until a *different*
        # save changes the mtime again -- and so a subsequent good save (a
        # new mtime) is always re-checked regardless of what happened here.
        self.stage_mtime = mtime
        try:
            self.stage.Reload()
        except Exception as exc:
            print(f"Hot-reload skipped for {self.stage_path}: {exc}")
            return  # syntax error mid-save; keep showing the last good version and retry on the next save

        if self._safe_set_time(Usd.TimeCode(self.time_var.get())):
            self.status.config(text=f"Hot-reloaded: {os.path.basename(self.stage_path)}")

    def _safe_set_time(self, time_code):
        """viewport.set_time() can raise if the stage's current content is
        broken -- e.g. Reload() succeeded but a value USD couldn't parse
        cleanly came back as an UnregisteredValue placeholder. Never let that
        escape into a recurring after() callback, or the callback chain dies
        silently; on failure the last successfully rendered geometry just
        stays on screen."""
        try:
            self.viewport.set_time(self.stage, time_code)
            return True
        except Exception as exc:
            print(f"Failed to refresh viewport for {self.stage_path}: {exc}")
            return False

    def on_shading_changed(self, mode):
        self.viewport.shading_mode = mode
        self.viewport.tkExpose(None)

    def on_bbox_toggled(self):
        self.viewport.show_bbox = self.show_bbox_var.get()
        self.viewport.tkExpose(None)

    def on_background_changed(self, mode):
        self.viewport.background_mode = mode
        self.viewport.tkExpose(None)

    def reset_view(self):
        self.viewport.frame_camera_on_geometry()
        self.viewport.tkExpose(None)

    def load_file(self):
        file_path = filedialog.askopenfilename(
            filetypes=[("USD Files", "*.usd *.usda *.usdc *.usdz")]
        )
        if not file_path:
            return

        self.stop_playback()
        new_stage = Usd.Stage.Open(file_path)
        if new_stage is None:
            self.status.config(text=f"Failed to open: {file_path}")
            return

        self.stage = new_stage
        self.stage_path = file_path
        self.stage_mtime = os.path.getmtime(file_path)

        filename = os.path.basename(file_path)
        self.title(f"Tkinter USD 3D Viewer | {filename}")
        self.lbl_filename.config(text=filename)
        self.btn_open.config(text="Open Another USD File")

        triangle_count = self.viewport.load_stage(self.stage)
        self._setup_playback_range()

        if triangle_count == 0:
            self.status.config(
                text="Opened, but found no Mesh/Cube/Sphere geometry to render"
            )
        else:
            self.status.config(text=f"Rendered {triangle_count} triangles")

    def _setup_playback_range(self):
        has_range = self.stage.HasAuthoredTimeCodeRange()
        start = self.stage.GetStartTimeCode()
        end = self.stage.GetEndTimeCode()
        self.fps = self.stage.GetFramesPerSecond() or 24.0

        self.time_slider.config(from_=start, to=end,
                                 state=tk.NORMAL if has_range else tk.DISABLED)
        self.time_var.set(start)
        self.btn_play.config(state=tk.NORMAL if has_range else tk.DISABLED)

    def on_scrub(self, value):
        if self.stage is None:
            return
        self._safe_set_time(Usd.TimeCode(float(value)))

    def toggle_play(self):
        if self.playing:
            self.stop_playback()
        else:
            self.playing = True
            self.btn_play.config(text="Pause")
            self._tick()

    def stop_playback(self):
        self.playing = False
        self.btn_play.config(text="Play")
        if self._play_job is not None:
            self.after_cancel(self._play_job)
            self._play_job = None

    def _tick(self):
        if not self.playing or self.stage is None:
            return

        start = self.time_slider.cget("from")
        end = self.time_slider.cget("to")
        next_time = self.time_var.get() + 1.0
        if next_time > end:
            next_time = start

        self.time_var.set(next_time)
        self._safe_set_time(Usd.TimeCode(next_time))
        self._play_job = self.after(max(1, int(1000 / self.fps)), self._tick)


if __name__ == "__main__":
    app = USDViewerTk()
    app.mainloop()
