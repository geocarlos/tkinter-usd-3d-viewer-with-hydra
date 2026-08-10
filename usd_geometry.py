import math

import numpy as np

from pxr import Usd, UsdGeom, UsdShade, Gf

from constants import DEFAULT_COLOR, WHITE_COLOR

DEFAULT_POINT_WIDTH = 0.1
DEFAULT_CURVE_WIDTH = 0.05


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
                indices.extend((top_left, bot_right, bot_left))
            elif i == rings - 1:
                counts.append(3)
                indices.extend((top_left, top_right, bot_left))
            else:
                counts.append(4)
                indices.extend((top_left, top_right, bot_right, bot_left))

    return points, counts, indices


def _apply_axis(point, axis):
    """Rotates a point defined in a local Z-spine frame onto the given
    UsdGeom "axis" token ("X" | "Y" | "Z"), using a proper rotation (not an
    axis swap) so that outward-facing winding stays outward regardless of
    which axis the prim is aligned to."""
    x, y, z = point
    if axis == "X":
        return (z, y, -x)
    if axis == "Y":
        return (x, z, -y)
    return (x, y, z)


def cone_faces(height, radius, axis="Z", segments=24):
    """Points/faceVertexCounts/faceVertexIndices for a UsdGeom.Cone: an apex
    at +height/2 along the local Z spine, tapering to a capped base circle
    of the given radius at -height/2, then rotated onto the given axis."""
    hh = height / 2.0
    apex = [(0.0, 0.0, hh)] * segments
    base_ring = []
    for j in range(segments):
        phi = 2.0 * math.pi * j / segments
        base_ring.append((radius * math.cos(phi), radius * math.sin(phi), -hh))
    base_center_index = 2 * segments
    points = apex + base_ring + [(0.0, 0.0, -hh)]

    counts = []
    indices = []
    for j in range(segments):
        j_next = (j + 1) % segments
        apex_j, base_j, base_jn = j, segments + j, segments + j_next

        counts.append(3)
        indices.extend((apex_j, base_j, base_jn))
        counts.append(3)
        indices.extend((base_center_index, base_jn, base_j))

    points = [_apply_axis(p, axis) for p in points]
    return points, counts, indices


def cylinder_faces(height, radius, axis="Z", segments=24):
    """Points/faceVertexCounts/faceVertexIndices for a UsdGeom.Cylinder: two
    capped circles of the given radius, height apart along the local Z
    spine, then rotated onto the given axis."""
    hh = height / 2.0
    top_ring = []
    bottom_ring = []
    for j in range(segments):
        phi = 2.0 * math.pi * j / segments
        x, y = radius * math.cos(phi), radius * math.sin(phi)
        top_ring.append((x, y, hh))
        bottom_ring.append((x, y, -hh))
    top_center_index = 2 * segments
    bottom_center_index = 2 * segments + 1
    points = top_ring + bottom_ring + [(0.0, 0.0, hh), (0.0, 0.0, -hh)]

    counts = []
    indices = []
    for j in range(segments):
        j_next = (j + 1) % segments
        top_j, top_jn = j, j_next
        bot_j, bot_jn = segments + j, segments + j_next

        counts.append(4)
        indices.extend((top_j, bot_j, bot_jn, top_jn))
        counts.append(3)
        indices.extend((top_center_index, top_j, top_jn))
        counts.append(3)
        indices.extend((bottom_center_index, bot_jn, bot_j))

    points = [_apply_axis(p, axis) for p in points]
    return points, counts, indices


def capsule_faces(height, radius, axis="Z", segments=24, hemisphere_rings=6):
    """Points/faceVertexCounts/faceVertexIndices for a UsdGeom.Capsule: a
    cylindrical band of the given height capped by hemispheres of the given
    radius, then rotated onto the given axis. Built as a sphere-like stack of
    latitude rings (pole -> pole), with the equator duplicated so the two
    hemispheres are joined by a straight (non-tapering) cylindrical band."""
    hh = height / 2.0

    ring_specs = []
    for i in range(hemisphere_rings + 1):
        theta = (math.pi / 2.0) * i / hemisphere_rings
        ring_specs.append((hh + radius * math.cos(theta), radius * math.sin(theta)))
    ring_specs.append((-hh, radius))
    for i in range(1, hemisphere_rings + 1):
        theta = (math.pi / 2.0) * i / hemisphere_rings
        ring_specs.append((-hh - radius * math.sin(theta), radius * math.cos(theta)))

    points = []
    for z, ring_radius in ring_specs:
        for j in range(segments):
            phi = 2.0 * math.pi * j / segments
            points.append((ring_radius * math.cos(phi), ring_radius * math.sin(phi), z))

    counts = []
    indices = []
    ring_count = len(ring_specs) - 1
    for i in range(ring_count):
        for j in range(segments):
            j_next = (j + 1) % segments
            top_left = i * segments + j
            top_right = i * segments + j_next
            bot_left = (i + 1) * segments + j
            bot_right = (i + 1) * segments + j_next
            if i == 0:
                counts.append(3)
                indices.extend((top_left, bot_left, bot_right))
            elif i == ring_count - 1:
                counts.append(3)
                indices.extend((top_left, bot_left, top_right))
            else:
                counts.append(4)
                indices.extend((top_left, bot_left, bot_right, top_right))

    points = [_apply_axis(p, axis) for p in points]
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


def get_widths(prim, time_code):
    """Returns (interpolation, flattened widths array) for a Points/Curves
    prim's authored "widths" attribute, or (None, None) if none is authored."""
    schema = UsdGeom.Points(prim) if prim.IsA(UsdGeom.Points) else UsdGeom.Curves(prim)
    widths_attr = schema.GetWidthsAttr()
    if not widths_attr or not widths_attr.HasAuthoredValue():
        return None, None

    values = widths_attr.Get(time_code)
    if not values:
        return None, None

    return schema.GetWidthsInterpolation(), values


def _indexed_value(interp, values, index, fallback):
    """Looks up a "constant" or per-element value by point/curve-vertex
    index. Unlike Mesh face-corner primvars (see _corner_value), Points and
    Curves widths/colors are indexed directly by point, with no faceVertexIndices
    to go through."""
    if interp is None or values is None:
        return fallback
    if interp == "constant":
        return values[0]
    return values[index] if index < len(values) else values[-1]


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

        elif prim.IsA(UsdGeom.Cone):
            cone = UsdGeom.Cone(prim)
            height = cone.GetHeightAttr().Get(time_code) or 2.0
            radius = cone.GetRadiusAttr().Get(time_code) or 1.0
            axis = cone.GetAxisAttr().Get(time_code) or "Z"
            points, counts, indices = cone_faces(height, radius, axis)

        elif prim.IsA(UsdGeom.Cylinder):
            cylinder = UsdGeom.Cylinder(prim)
            height = cylinder.GetHeightAttr().Get(time_code) or 2.0
            radius = cylinder.GetRadiusAttr().Get(time_code) or 1.0
            axis = cylinder.GetAxisAttr().Get(time_code) or "Z"
            points, counts, indices = cylinder_faces(height, radius, axis)

        elif prim.IsA(UsdGeom.Capsule):
            capsule = UsdGeom.Capsule(prim)
            height = capsule.GetHeightAttr().Get(time_code) or 2.0
            radius = capsule.GetRadiusAttr().Get(time_code) or 0.5
            axis = capsule.GetAxisAttr().Get(time_code) or "Z"
            points, counts, indices = capsule_faces(height, radius, axis)

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


def _append_point_spheres(prim, xform, time_code, positions, normals, colors, uvs):
    """Renders one Points prim's "Solid" representation: a low-poly sphere
    instanced at each point, scaled to its authored width (diameter). Real
    per-point triangle geometry is inherently heavier than a point sprite --
    that cost is exactly why "Lightweight" mode exists as an alternative for
    large point clouds."""
    points = UsdGeom.Points(prim).GetPointsAttr().Get(time_code)
    if not points:
        return

    color_interp, color_values = get_display_colors(prim, time_code)
    width_interp, width_values = get_widths(prim, time_code)
    unit_sphere = sphere_faces(1.0, rings=3, segments=6)

    for i, local_point in enumerate(points):
        radius = _indexed_value(width_interp, width_values, i, DEFAULT_POINT_WIDTH) / 2.0
        color = _indexed_value(color_interp, color_values, i, DEFAULT_COLOR)
        world_point = xform.Transform(Gf.Vec3d(*local_point))

        instance_xform = Gf.Matrix4d().SetScale(radius) * Gf.Matrix4d().SetTranslate(world_point)
        sphere_points, sphere_counts, sphere_indices = unit_sphere
        _triangulate(sphere_points, sphere_counts, sphere_indices, instance_xform,
                     "constant", [color], None, None, positions, normals, colors, uvs)


def _append_curve_tubes(prim, xform, time_code, positions, normals, colors, uvs):
    """Renders one BasisCurves prim's "Solid" representation: a tube
    instanced along each control-point segment, radius averaged from the two
    endpoint widths. Treats every curve as linear -- for spline bases
    (bezier/bspline/catmullRom) this draws the control polygon rather than
    the evaluated curve, which keeps this a simple per-segment instancing
    problem instead of a basis-evaluation one."""
    curves = UsdGeom.BasisCurves(prim)
    points = curves.GetPointsAttr().Get(time_code)
    counts = curves.GetCurveVertexCountsAttr().Get(time_code)
    if not points or not counts:
        return

    color_interp, color_values = get_display_colors(prim, time_code)
    width_interp, width_values = get_widths(prim, time_code)
    unit_tube = cylinder_faces(1.0, 1.0, "Z", segments=8)
    world_points = [xform.Transform(Gf.Vec3d(*p)) for p in points]

    offset = 0
    for count in counts:
        for i in range(offset, offset + count - 1):
            a, b = world_points[i], world_points[i + 1]
            direction = b - a
            length = direction.GetLength()
            if length < 1e-9:
                continue
            direction /= length

            width_a = _indexed_value(width_interp, width_values, i, DEFAULT_CURVE_WIDTH)
            width_b = _indexed_value(width_interp, width_values, i + 1, DEFAULT_CURVE_WIDTH)
            radius = (width_a + width_b) / 4.0
            color = _indexed_value(color_interp, color_values, i, DEFAULT_COLOR)

            instance_xform = (
                Gf.Matrix4d().SetScale(Gf.Vec3d(radius, radius, length))
                * Gf.Matrix4d().SetRotate(Gf.Rotation(Gf.Vec3d(0, 0, 1), direction))
                * Gf.Matrix4d().SetTranslate((a + b) / 2.0)
            )
            tube_points, tube_counts, tube_indices = unit_tube
            _triangulate(tube_points, tube_counts, tube_indices, instance_xform,
                         "constant", [color], None, None, positions, normals, colors, uvs)
        offset += count


def extract_solid_curves_and_points(stage, time_code=Usd.TimeCode.Default()):
    """"Solid" mode: Points as instanced low-poly spheres and BasisCurves as
    instanced tube segments, both real triangle geometry folded into a single
    triangle group so they're lit and shaded through the same pipeline as
    Mesh/Cube/etc. Costs triangles per point/segment -- see
    extract_lightweight_curves_and_points for the cheaper alternative."""
    positions, normals, colors, uvs = [], [], [], []

    for prim in stage.Traverse():
        xform = UsdGeom.Xformable(prim).ComputeLocalToWorldTransform(time_code)

        if prim.IsA(UsdGeom.Points):
            _append_point_spheres(prim, xform, time_code, positions, normals, colors, uvs)
        elif prim.IsA(UsdGeom.BasisCurves):
            _append_curve_tubes(prim, xform, time_code, positions, normals, colors, uvs)

    if not positions:
        return []

    return [{
        "texture_path": None,
        "positions": np.array(positions, dtype=np.float32),
        "normals": np.array(normals, dtype=np.float32),
        "colors": np.array(colors, dtype=np.float32),
        "uvs": np.array(uvs, dtype=np.float32),
    }]


def extract_lightweight_curves_and_points(stage, time_code=Usd.TimeCode.Default()):
    """"Lightweight" mode: Points as a raw GL_POINTS cloud and BasisCurves as
    raw GL_LINES through their control points -- ignores authored width and
    (for spline-basis curves) the basis itself, drawing the control polygon
    rather than the evaluated curve. Cost is independent of point/segment
    count in a way instanced geometry can't be, making it the fallback for
    large point clouds or curve caches where "Solid" mode gets too heavy."""
    point_positions, point_colors = [], []
    line_positions, line_colors = [], []

    for prim in stage.Traverse():
        xform = UsdGeom.Xformable(prim).ComputeLocalToWorldTransform(time_code)

        if prim.IsA(UsdGeom.Points):
            points = UsdGeom.Points(prim).GetPointsAttr().Get(time_code)
            if not points:
                continue
            color_interp, color_values = get_display_colors(prim, time_code)
            for i, p in enumerate(points):
                point_positions.append(xform.Transform(Gf.Vec3d(*p)))
                point_colors.append(_indexed_value(color_interp, color_values, i, DEFAULT_COLOR))

        elif prim.IsA(UsdGeom.BasisCurves):
            curves = UsdGeom.BasisCurves(prim)
            points = curves.GetPointsAttr().Get(time_code)
            counts = curves.GetCurveVertexCountsAttr().Get(time_code)
            if not points or not counts:
                continue
            color_interp, color_values = get_display_colors(prim, time_code)
            world_points = [xform.Transform(Gf.Vec3d(*p)) for p in points]

            offset = 0
            for count in counts:
                for i in range(offset, offset + count - 1):
                    color = _indexed_value(color_interp, color_values, i, DEFAULT_COLOR)
                    line_positions.extend((world_points[i], world_points[i + 1]))
                    line_colors.extend((color, color))
                offset += count

    def _to_array(values):
        return np.array(values, dtype=np.float32) if values else np.zeros((0, 3), dtype=np.float32)

    return {
        "point_positions": _to_array(point_positions),
        "point_colors": _to_array(point_colors),
        "line_positions": _to_array(line_positions),
        "line_colors": _to_array(line_colors),
    }
