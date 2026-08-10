import math

import numpy as np

from pxr import Usd, UsdGeom, UsdShade, Gf

from constants import DEFAULT_COLOR, WHITE_COLOR


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
