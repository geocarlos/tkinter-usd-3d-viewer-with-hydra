"""Non-destructive replacement of USD's implicit quadric primitives
(Cylinder, Cone, Capsule, Sphere) with explicitly tessellated Mesh prims.

Hydra never tessellates these adaptively: UsdImaging converts each one to a
single fixed-resolution "canonical unit mesh" (see
UsdImagingGetUnitCylinderMeshTopology() and friends in
usdImaging/implicitSurfaceMeshUtils.h) regardless of screen size, camera
distance, or any complexity/refinement setting -- there is no tessellation
knob exposed anywhere in UsdImagingGL for these types. That's why they
render visibly faceted. The fix here is to generate finer geometry
ourselves and author it as real Mesh prims on the stage's session layer
(never touching the source file), so Hydra renders our mesh instead of its
own coarse one for everything else -- materials, lighting, camera, time,
curves, points -- unchanged.

The tessellation density is a single "radial segments" knob (see
QUALITY_PRESETS) -- sphere/capsule latitude bands are derived from it so
main_window.py's Quality dropdown only needs to expose one control.
"""

import functools
import math

from pxr import Gf, Sdf, Usd, UsdGeom, Vt

MANAGED_TYPES = ("Cylinder", "Cone", "Capsule", "Sphere")

# 48+ segments is imperceptibly rounder than 32 on anything but a tight
# close-up, but costs noticeably more to generate/re-tessellate on every
# time-code change -- 32 (Blender's own default circle/sphere resolution)
# is the better default; Low/High/Ultra are there for people who want to
# trade one way or the other.
QUALITY_PRESETS = {
    "Low": 16,
    "Medium": 32,
    "High": 48,
    "Ultra": 64,
}
DEFAULT_QUALITY = "Medium"


def _sphere_lat_segments(n):
    return max(4, n // 2)


def _capsule_cap_segments(n):
    return max(2, n // 4)


_AXIS_MATRICES = {
    # Each maps the local +Z axis used below onto the schema's "axis" token.
    "X": ((0.0, 0.0, 1.0), (0.0, 1.0, 0.0), (-1.0, 0.0, 0.0)),
    "Y": ((1.0, 0.0, 0.0), (0.0, 0.0, 1.0), (0.0, -1.0, 0.0)),
    "Z": ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
}


def _apply_axis(vectors, axis):
    m = _AXIS_MATRICES[axis]
    return [(m[0][0] * x + m[0][1] * y + m[0][2] * z,
             m[1][0] * x + m[1][1] * y + m[1][2] * z,
             m[2][0] * x + m[2][1] * y + m[2][2] * z)
            for x, y, z in vectors]


@functools.lru_cache(maxsize=None)
def _ring(n):
    return tuple((math.cos(2.0 * math.pi * i / n), math.sin(2.0 * math.pi * i / n)) for i in range(n))


def _add(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _normalize(v):
    length = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2]) or 1.0
    return (v[0] / length, v[1] / length, v[2] / length)


# -- Cylinder -----------------------------------------------------------
# Local unit shape: radius 1, height 1, centered on the origin, running
# along +Z before the axis remap -- matches the "large end on -Z" convention
# implicitSurfaceMeshUtils.h documents for USD's own canonical meshes.

def _cylinder_topology(n):
    counts = [4] * n + [n, n]
    indices = []
    for i in range(n):
        j = (i + 1) % n
        indices += [i, j, n + j, n + i]  # bottom[i], bottom[j], top[j], top[i]
    indices += list(range(n, 2 * n))       # top cap
    indices += list(reversed(range(n)))    # bottom cap
    return counts, indices


def _cylinder_points_normals(radius, height, axis, n):
    ring = _ring(n)
    half_h = height / 2.0
    bottom = [(x * radius, y * radius, -half_h) for x, y in ring]
    top = [(x * radius, y * radius, half_h) for x, y in ring]
    points = bottom + top

    # A cylinder's side normal is purely radial -- exact regardless of how
    # radius/height are scaled, so the *unit* ring direction is already correct.
    side = [(x, y, 0.0) for x, y in ring]
    normals = []
    for i in range(n):
        j = (i + 1) % n
        normals += [side[i], side[j], side[j], side[i]]
    normals += [(0.0, 0.0, 1.0)] * n   # top cap
    normals += [(0.0, 0.0, -1.0)] * n  # bottom cap

    return _apply_axis(points, axis), _apply_axis(normals, axis)


# -- Cone -----------------------------------------------------------------
# Base ring on -Z, single apex point on +Z (matches UsdGeomCone / the header
# comment for the canonical unit cone).

def _cone_topology(n):
    apex = n
    counts = [3] * n + [n]
    indices = []
    for i in range(n):
        j = (i + 1) % n
        indices += [i, j, apex]
    indices += list(reversed(range(n)))  # base cap
    return counts, indices


def _cone_points_normals(radius, height, axis, n):
    ring = _ring(n)
    half_h = height / 2.0
    base = [(x * radius, y * radius, -half_h) for x, y in ring]
    apex = (0.0, 0.0, half_h)
    points = base + [apex]

    # A cone's side normal depends on the radius/height ratio (slant angle),
    # unlike a cylinder's -- it must be recomputed whenever either changes.
    slant = math.hypot(height, radius) or 1.0
    rim_normals = [(x * height / slant, y * height / slant, radius / slant) for x, y in ring]

    normals = []
    for i in range(n):
        j = (i + 1) % n
        # The apex is a true singularity (the limit normal depends on the
        # direction of approach); blending the two adjacent rim normals
        # gives a smooth, seamless highlight down to the tip.
        apex_normal = _normalize(_add(rim_normals[i], rim_normals[j]))
        normals += [rim_normals[i], rim_normals[j], apex_normal]
    normals += [(0.0, 0.0, -1.0)] * n  # base cap

    return _apply_axis(points, axis), _apply_axis(normals, axis)


# -- Sphere -----------------------------------------------------------------
# Standard UV sphere: a single point at each pole plus interior latitude
# rings in between. Axis-independent (spheres are radially symmetric).

def _sphere_topology(n, m):
    north_idx = (m - 1) * n
    south_idx = north_idx + 1

    def ring_start(band):
        return (band - 1) * n

    counts, indices = [], []

    for i in range(n):
        j = (i + 1) % n
        counts.append(3)
        indices += [north_idx, ring_start(1) + i, ring_start(1) + j]

    for band in range(1, m - 1):
        r0, r1 = ring_start(band), ring_start(band + 1)
        for i in range(n):
            j = (i + 1) % n
            counts.append(4)
            indices += [r0 + i, r0 + j, r1 + j, r1 + i]

    last = ring_start(m - 1)
    for i in range(n):
        j = (i + 1) % n
        counts.append(3)
        indices += [last + j, last + i, south_idx]

    return counts, indices


def _sphere_points_normals(radius, n, m):
    ring = _ring(n)
    unit = []
    for band in range(1, m):
        phi = math.pi * band / m
        ring_radius, z = math.sin(phi), math.cos(phi)
        unit += [(x * ring_radius, y * ring_radius, z) for x, y in ring]
    unit.append((0.0, 0.0, 1.0))   # north pole
    unit.append((0.0, 0.0, -1.0))  # south pole

    normals = list(unit)  # unit sphere: normal == position
    points = [(x * radius, y * radius, z * radius) for x, y, z in unit]
    return points, normals


# -- Capsule ------------------------------------------------------------
# Two hemispherical caps (reusing the sphere's lat/long scheme) joined by a
# cylindrical band. Each cap's own equator ring doubles as the cylinder's
# top/bottom ring, so there's no seam and no duplicated geometry.

def _capsule_layout(n, m):
    upper_pole = 0
    upper_start = 1
    upper_interior_count = (m - 1) * n
    upper_equator_start = upper_start + upper_interior_count
    lower_pole = upper_equator_start + n
    lower_start = lower_pole + 1
    lower_interior_count = (m - 1) * n
    lower_equator_start = lower_start + lower_interior_count
    total_points = lower_equator_start + n

    return {
        "n": n, "m": m,
        "upper_pole": upper_pole,
        "upper_start": upper_start,
        "upper_equator_start": upper_equator_start,
        "lower_pole": lower_pole,
        "lower_start": lower_start,
        "lower_equator_start": lower_equator_start,
        "total_points": total_points,
    }


def _capsule_topology(n, m):
    L = _capsule_layout(n, m)
    counts, indices = [], []

    def hemisphere_faces(pole_idx, ring_base, equator_start, flip):
        # band 1..m-1 are the interior rings (mirrors fill_hemisphere()'s
        # indexing exactly); band m is the equator, stored separately since
        # it's shared with the cylindrical band below.
        def ring_offset(band):
            return ring_base + (band - 1) * n if band < m else equator_start

        # Pole cap fan, connecting the pole to the first interior ring.
        first_ring = ring_offset(1)
        for i in range(n):
            j = (i + 1) % n
            tri = [pole_idx, first_ring + i, first_ring + j]
            counts.append(3)
            indices.extend(tri[::-1] if flip else tri)
        # Interior bands, running all the way to the equator ring -- a loop
        # bound of m-1 (not m-2) is required since there are m-1 connecting
        # bands between the m rings (pole excluded) of a hemisphere.
        #
        # band+1 (closer to the equator) goes first, band (closer to the
        # pole) second -- the reverse of what you'd guess from the pole
        # fan's winding above. That's not a typo: the pole fan and this
        # quad strip are different topological cases, and mirroring the
        # fan's [pole, near, far] order into [near, near, far, far] here
        # actually winds every quad backwards -- confirmed by comparing
        # each face's winding-derived (cross-product) normal against its
        # own authored normal; they came out exactly opposite (dot=-1) with
        # r0 listed first, and exactly matching (dot=+1) with r1 first, at
        # every band checked. Wound backwards, doubleSided still draws the
        # faces, but Storm's two-sided lighting flips the *shading* normal
        # to face the camera on a back-winding triangle -- which looked
        # like the domes being lit from the opposite side of the light
        # relative to the (correctly-wound) cylindrical band.
        for band in range(1, m):
            r0, r1 = ring_offset(band), ring_offset(band + 1)
            for i in range(n):
                j = (i + 1) % n
                quad = [r1 + i, r1 + j, r0 + j, r0 + i]
                counts.append(4)
                indices.extend(quad[::-1] if flip else quad)

    hemisphere_faces(L["upper_pole"], L["upper_start"], L["upper_equator_start"], flip=False)
    hemisphere_faces(L["lower_pole"], L["lower_start"], L["lower_equator_start"], flip=True)

    # Cylindrical band between the two equator rings.
    u_eq, l_eq = L["upper_equator_start"], L["lower_equator_start"]
    for i in range(n):
        j = (i + 1) % n
        counts.append(4)
        indices += [l_eq + i, l_eq + j, u_eq + j, u_eq + i]

    return counts, indices


def _capsule_points_normals(radius, height, axis, n, m):
    ring = _ring(n)
    L = _capsule_layout(n, m)
    half_h = height / 2.0
    points = [None] * L["total_points"]
    normals = [None] * L["total_points"]

    def fill_hemisphere(pole_idx, ring_base, equator_start, sign, z_offset):
        points[pole_idx] = (0.0, 0.0, sign * radius + z_offset)
        normals[pole_idx] = (0.0, 0.0, sign)
        for band in range(1, m + 1):
            phi = (math.pi / 2.0) * band / m
            ring_radius, z_unit = math.sin(phi), math.cos(phi)
            dest = ring_base + (band - 1) * n if band < m else equator_start
            for k, (x, y) in enumerate(ring):
                nrm = (x * ring_radius, y * ring_radius, sign * z_unit)
                points[dest + k] = (nrm[0] * radius, nrm[1] * radius, sign * z_unit * radius + z_offset)
                normals[dest + k] = nrm

    fill_hemisphere(L["upper_pole"], L["upper_start"], L["upper_equator_start"], sign=1.0, z_offset=half_h)
    fill_hemisphere(L["lower_pole"], L["lower_start"], L["lower_equator_start"], sign=-1.0, z_offset=-half_h)

    return _apply_axis(points, axis), _apply_axis(normals, axis)


@functools.lru_cache(maxsize=None)
def topology(type_name, segments):
    """(faceVertexCounts, faceVertexIndices) for `type_name` tessellated at
    `segments` radial divisions. Fixed per (type, segments) pair -- cached
    since QUALITY_PRESETS only offers a handful of distinct values."""
    if type_name == "Cylinder":
        return _cylinder_topology(segments)
    if type_name == "Cone":
        return _cone_topology(segments)
    if type_name == "Sphere":
        return _sphere_topology(segments, _sphere_lat_segments(segments))
    if type_name == "Capsule":
        return _capsule_topology(segments, _capsule_cap_segments(segments))
    raise ValueError(f"not a managed implicit-surface type: {type_name}")


def _get_axis(schema):
    axis_attr = schema.GetAxisAttr()
    return axis_attr.Get() if axis_attr and axis_attr.HasAuthoredValue() else "Z"


def _shape_attrs(type_name, schema):
    """(attributes whose value determines the mesh shape) for a given schema."""
    if type_name == "Sphere":
        return [schema.GetRadiusAttr()]
    return [schema.GetRadiusAttr(), schema.GetHeightAttr()]


# Sphere/Capsule generators return one normal per *point* (every corner
# sharing a point is smooth-shaded, there's no hard edge anywhere); Cylinder/
# Cone build a distinct normal per *face-corner* directly (needed for their
# hard edges at the caps, and for Cone's per-face apex blend). The mesh
# itself is always authored with faceVarying interpolation, so per-point
# arrays get expanded to per-corner here via the fixed topology's indices.
_PER_VERTEX_NORMALS = {"Sphere", "Capsule"}


def compute_mesh(type_name, prim, time_code, segments):
    """Tessellate `prim` (a Cylinder/Cone/Capsule/Sphere) at `time_code`
    with `segments` radial divisions.

    Returns (points, normals, is_time_varying) -- points is one entry per
    mesh point, normals is one entry per face-corner (faceVarying, matching
    topology(type_name, segments)'s faceVertexIndices) -- both ready for
    Vt.Vec3fArray.
    """
    schema = getattr(UsdGeom, type_name)(prim)
    radius = schema.GetRadiusAttr().Get(time_code)
    radius = 1.0 if radius is None else radius

    is_time_varying = any(attr.ValueMightBeTimeVarying() for attr in _shape_attrs(type_name, schema))

    if type_name == "Sphere":
        points, normals = _sphere_points_normals(radius, segments, _sphere_lat_segments(segments))
    else:
        height = schema.GetHeightAttr().Get(time_code)
        height = 1.0 if height is None else height
        axis = _get_axis(schema)
        is_time_varying = is_time_varying or schema.GetAxisAttr().ValueMightBeTimeVarying()

        if type_name == "Cylinder":
            points, normals = _cylinder_points_normals(radius, height, axis, segments)
        elif type_name == "Cone":
            points, normals = _cone_points_normals(radius, height, axis, segments)
        elif type_name == "Capsule":
            points, normals = _capsule_points_normals(radius, height, axis, segments, _capsule_cap_segments(segments))
        else:
            raise ValueError(f"not a managed implicit-surface type: {type_name}")

    if type_name in _PER_VERTEX_NORMALS:
        _, indices = topology(type_name, segments)
        normals = [normals[i] for i in indices]

    return points, normals, is_time_varying


def apply_overrides(stage, time_code, segments):
    """Walk `stage`, and on its session layer, override every Cylinder/Cone/
    Capsule/Sphere prim as an explicit high-resolution Mesh -- Hydra then
    renders our tessellation instead of its own fixed low-poly one.

    Only meaningful on a stage that hasn't been processed yet: it identifies
    candidates by `prim.GetTypeName()`, which is already "Mesh" for any prim
    a *previous* call already overrode. Re-tessellating at a new `segments`
    value belongs to refresh_overrides() instead, using the (path,
    original_type_name) pairs this returns.

    Returns those (prim_path, original_type_name) pairs, so the caller can
    keep the geometry in sync as time, the underlying file, or the
    tessellation quality changes (see refresh_overrides()).
    """
    overridden = []
    with Usd.EditContext(stage, stage.GetSessionLayer()):
        for prim in stage.Traverse():
            type_name = prim.GetTypeName()
            if type_name not in MANAGED_TYPES:
                continue
            _author_mesh(stage, prim, type_name, time_code, segments)
            overridden.append((prim.GetPath(), type_name))
    return overridden


def refresh_overrides(stage, overridden, time_code, segments, topology_too=False):
    """Recompute geometry for every previously-overridden prim (the list
    apply_overrides() returned) at `time_code`, at the given `segments`
    resolution.

    With `topology_too=False` (the default), only points/normals are
    touched -- cheap enough to call on every time-code change, and it also
    picks up a hot-reloaded edit to a *static* radius/height/axis value, not
    just genuine animation, since there's no reliable way to tell those two
    cases apart from here.

    Pass `topology_too=True` when `segments` itself has changed (e.g. the
    user picked a different tessellation quality): apply_overrides() can't
    be called again for this since the prims it would look for are already
    typed "Mesh" from the first pass, so this reuses the known
    (path, original_type_name) list instead of re-traversing the stage."""
    with Usd.EditContext(stage, stage.GetSessionLayer()):
        for path, type_name in overridden:
            prim = stage.GetPrimAtPath(path)
            if prim:
                _author_mesh(stage, prim, type_name, time_code, segments, topology_too=topology_too)


def _author_mesh(stage, prim, type_name, time_code, segments, topology_too=True):
    original_prim = UsdGeom.Gprim(prim)
    display_color = original_prim.GetDisplayColorAttr().Get() if original_prim else None

    mesh = UsdGeom.Mesh.Define(stage, prim.GetPath())
    mesh.CreateDoubleSidedAttr(True)  # sidesteps winding-direction bugs; harmless for opaque solids
    # UsdGeomMesh defaults subdivisionScheme to "catmullClark" -- left alone,
    # Storm treats our already-final tessellation as a coarse control cage
    # and subdivides it again, pinching the high-valence pole vertices into
    # a "navel" and creasing the seams between triangle fans and quad bands.
    # These meshes are the finished surface, not a control cage.
    mesh.CreateSubdivisionSchemeAttr(UsdGeom.Tokens.none)

    points, normals, _ = compute_mesh(type_name, prim, time_code, segments)
    mesh.CreatePointsAttr(Vt.Vec3fArray([Gf.Vec3f(*p) for p in points]))

    if topology_too:
        counts, indices = topology(type_name, segments)
        mesh.CreateFaceVertexCountsAttr(Vt.IntArray(counts))
        mesh.CreateFaceVertexIndicesAttr(Vt.IntArray(indices))

    normals_attr = mesh.CreateNormalsAttr(Vt.Vec3fArray([Gf.Vec3f(*nrm) for nrm in normals]))
    mesh.SetNormalsInterpolation(UsdGeom.Tokens.faceVarying)

    if display_color is not None and not mesh.GetDisplayColorAttr().HasAuthoredValue():
        mesh.CreateDisplayColorAttr(display_color)
