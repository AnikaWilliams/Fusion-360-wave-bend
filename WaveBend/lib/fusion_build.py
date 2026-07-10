# WaveBend/lib/fusion_build.py  -- runs ONLY inside Fusion
#
# Maps the pure geometry profiles (from geometry.py, in the local u,v frame, cm)
# onto the selected face and makes one non-destructive extrude-cut. Also reads
# thickness + material from the host body.
#
# NOTE: every adsk.* call below is marked (verify) — confirm the method name and
# signature against the Fusion API docs / Python add-in template before trusting it.
# These are the most likely points of first-run failure.
import math
import adsk.core, adsk.fusion          # (verify against docs)
try:
    from . import geometry as G        # package context: the WaveBend add-in
except ImportError:
    import geometry as G               # script context: selftest puts lib/ on sys.path


def _pt3d(origin, u_hat, v_hat, u, v):
    # map local (u, v) [cm] onto the model frame -> Point3D [cm]
    x = origin.x + u_hat.x * u + v_hat.x * v
    y = origin.y + u_hat.y * u + v_hat.y * v
    z = origin.z + u_hat.z * u + v_hat.z * v
    return adsk.core.Point3D.create(x, y, z)   # (verify: Point3D.create signature)


def local_frame(entity):
    """Return (origin Point3D, u_hat Vector3D, v_hat Vector3D, length_cm, planar_face).

    Accepts a BRepEdge (uses edge.geometry + the adjacent face) OR a SketchLine
    (uses worldGeometry + the sketch's reference face/plane). A wave bend line is
    normally an interior sketch line on the flat face, since the pattern straddles it.
    """
    if hasattr(entity, "worldGeometry"):               # SketchLine
        geo = entity.worldGeometry                     # Line3D in model space
        face = entity.parentSketch.referencePlane      # face/plane the sketch sits on (verify)
    else:                                              # BRepEdge
        geo = entity.geometry
        face = entity.faces.item(0)                    # (verify)
    p0 = geo.startPoint; p1 = geo.endPoint
    u = adsk.core.Vector3D.create(p1.x - p0.x, p1.y - p0.y, p1.z - p0.z)
    length = u.length
    u.normalize()
    n = face.geometry.normal                           # planar face/plane normal (verify)
    n.normalize()
    v = n.crossProduct(u)        # in-plane perpendicular (verify cross order/handedness)
    v.normalize()
    return p0, u, v, length, face


_MIN_SEG_CM = 1e-4   # skip sketch lines shorter than this (defensive against degenerate cells)


def draw_pattern_sketch(comp, pattern, frame):
    """Draw every cell profile into ONE new sketch on the frame's face. Returns the sketch.

    IMPORTANT: Fusion sketch entities live in the SKETCH's local coordinate system,
    not model space -- a face sketch has its own origin/axes (and often a flipped
    axis). Drawing raw model-space coordinates misplaces the pattern relative to the
    selected bend line. Every point is therefore mapped model->sketch via
    Sketch.modelToSketchSpace().
    """
    origin, u_hat, v_hat, _length, face = frame
    sk = comp.sketches.add(face)                       # (verify: sketches.add(planarFace))
    # Fusion may AUTO-PROJECT the face's boundary edges into a new face sketch
    # ("Auto project edges on reference" preference). Those projected curves close a
    # face-sized profile, and a cut over all profiles would then consume the whole
    # plate (observed in selftest run #3). Purge everything present before we draw --
    # anything already in this sketch is not ours.
    for i in range(sk.sketchCurves.count - 1, -1, -1):
        try:
            sk.sketchCurves.item(i).deleteMe()         # (verify: SketchCurve.deleteMe)
        except Exception:
            pass                                       # locked/undeletable refs: leave them

    def sp(u, v):
        # local (u,v) -> model Point3D -> THIS sketch's coordinates (verify: modelToSketchSpace)
        return sk.modelToSketchSpace(_pt3d(origin, u_hat, v_hat, u, v))

    lines = sk.sketchCurves.sketchLines
    arcs = sk.sketchCurves.sketchArcs
    for profile in pattern["profiles"]:
        for seg in profile:
            if seg[0] == "line":
                _, a, b = seg
                if math.hypot(b.x - a.x, b.y - a.y) < _MIN_SEG_CM:
                    continue                           # adjacent arcs already meet; skip the stub
                lines.addByTwoPoints(sp(a.x, a.y), sp(b.x, b.y))
            else:
                _, c, r, a0, a1, a, b = seg
                am = (a0 + a1) / 2.0
                mid = G.Pt(c.x + r * math.cos(am), c.y + r * math.sin(am))
                arcs.addByThreePoints(                 # (verify: addByThreePoints)
                    sp(a.x, a.y), sp(mid.x, mid.y), sp(b.x, b.y))
    return sk


def cut_sketch(comp, sk, depth_cm, max_profile_diag_cm=None):
    """One extrude-cut consuming the closed slot profiles in `sk`, through the sheet.

    If max_profile_diag_cm is given, profiles whose bounding-box diagonal exceeds it
    are skipped -- a second line of defense against a face-sized profile (from
    auto-projected boundary edges) turning the relief cut into cut-away-the-plate.
    """
    prof_coll = adsk.core.ObjectCollection.create()
    for p in sk.profiles:
        if max_profile_diag_cm is not None:
            bb = p.boundingBox                          # (verify: Profile.boundingBox)
            diag = math.hypot(bb.maxPoint.x - bb.minPoint.x, bb.maxPoint.y - bb.minPoint.y)
            if diag > max_profile_diag_cm:
                continue                                # not a slot; never cut it
        prof_coll.add(p)
    if prof_coll.count == 0:
        raise RuntimeError("no slot-sized profiles to cut (sketch profile filtering)")
    extrudes = comp.features.extrudeFeatures
    cut_input = extrudes.createInput(
        prof_coll, adsk.fusion.FeatureOperations.CutFeatureOperation)   # (verify enum)
    # Symmetric DISTANCE (>= thickness each way) rather than through-all: direction-agnostic
    # and it does not search for a body on both sides, so it avoids the "body not found"
    # failure of through-all when one side of the sketch plane is empty. (verify ValueInput)
    dist = adsk.core.ValueInput.createByReal(depth_cm * 1.25)
    cut_input.setDistanceExtent(True, dist)            # True = symmetric
    return extrudes.add(cut_input)


def draw_and_cut(comp, pattern, frame, depth_cm, name=None):
    """Draw the pattern sketch, then cut it. Returns (sketch, cut_feature).

    If `name` is given, both timeline features get readable names instead of
    the anonymous 'SketchN' / 'ExtrudeN'."""
    sk = draw_pattern_sketch(comp, pattern, frame)
    # slot-size ceiling for the profile filter: the largest cell bbox diagonal + slack
    diag = 0.0
    for prof in pattern["profiles"][:2]:               # smile + frown suffice
        pts = G.sample_profile(prof, n=4)
        w = max(p.x for p in pts) - min(p.x for p in pts)
        h = max(p.y for p in pts) - min(p.y for p in pts)
        diag = max(diag, math.hypot(w, h))
    cut = cut_sketch(comp, sk, depth_cm, max_profile_diag_cm=diag * 1.2)
    if name:
        try:
            sk.name = f'{name} sketch'                 # (verify: Sketch.name settable)
            cut.name = name                            # (verify: Feature.name settable)
        except Exception:
            pass                                       # cosmetic only; never fail the cut
    return sk, cut


# ---- body resolution + thickness/material readers ------------------------------

def frame_from_points(p0_xyz, p1_xyz):
    """Rebuild a bend-line frame from raw endpoint coordinates (cm).

    Entity references (tokens, faces, sketch lines) can be invalidated or even
    REMAPPED by Fusion's preview rollback — live-tested: a cached SketchLine token
    resolved to a sibling line after rollback. Raw coordinates cannot lie. The
    hosting face is re-found fresh from the geometry every time.
    Returns the same tuple local_frame does, or raises RuntimeError."""
    p0 = adsk.core.Point3D.create(*p0_xyz)
    p1 = adsk.core.Point3D.create(*p1_xyz)
    u = adsk.core.Vector3D.create(p1.x - p0.x, p1.y - p0.y, p1.z - p0.z)
    length = u.length
    if length < 1e-6:
        raise RuntimeError('cached bend line is degenerate')
    u.normalize()
    mid = adsk.core.Point3D.create((p0.x + p1.x) / 2.0, (p0.y + p1.y) / 2.0,
                                   (p0.z + p1.z) / 2.0)
    body = _body_at_point(mid)
    if body is None:
        raise RuntimeError('no solid body found near the cached bend line')
    face = _face_containing(body, p0, p1)
    if face is None:
        raise RuntimeError('no planar face of the host body contains the bend line')
    n = face.geometry.normal
    n.normalize()
    v = n.crossProduct(u)
    v.normalize()
    return p0, u, v, length, face


def _face_containing(body, p0, p1):
    """The planar face of `body` on which both points lie (within tolerance)."""
    mm = adsk.core.Application.get().measureManager
    best, best_d = None, 1e-3                          # 10 µm acceptance
    for f in body.faces:
        try:
            if f.geometry.objectType != adsk.core.Plane.classType():
                continue
            d = max(mm.measureMinimumDistance(f, p0).value,
                    mm.measureMinimumDistance(f, p1).value)
            if d < best_d:
                best, best_d = f, d
        except Exception:
            continue
    return best


def _body_at_point(pt):
    """Solid body containing/touching the point, else the nearest one."""
    design = adsk.fusion.Design.cast(adsk.core.Application.get().activeProduct)
    root = design.rootComponent
    bodies = [b for b in root.bRepBodies]
    for occ in root.allOccurrences:
        bodies.extend(occ.bRepBodies)
    solid = [b for b in bodies if b.isSolid and b.isVisible]
    for b in solid:
        try:
            c = b.pointContainment(pt)
            if c in (adsk.fusion.PointContainment.PointInsidePointContainment,
                     adsk.fusion.PointContainment.PointOnPointContainment):
                return b
        except Exception:
            pass
    mm = adsk.core.Application.get().measureManager
    best, best_d = None, float('inf')
    for b in solid:
        try:
            d = mm.measureMinimumDistance(b, pt).value
        except Exception:
            continue
        if d < best_d:
            best, best_d = b, d
    return best


def find_host_body(frame):
    """The body the bend line lies on: containment of the line midpoint, else nearest.

    Works when the sketch sits on a CONSTRUCTION PLANE (no face to walk from), for
    sheet-metal parts, and in multi-body files. Returns None only if the design has
    no solid bodies at all.
    """
    origin, u_hat, _v_hat, length, _face = frame
    mid = _pt3d(origin, u_hat, adsk.core.Vector3D.create(0, 0, 0), length / 2.0, 0.0)
    return _body_at_point(mid)


def _largest_planar_face_area(body):
    best = 0.0
    for f in body.faces:
        try:
            if f.geometry.objectType == adsk.core.Plane.classType():
                best = max(best, f.area)
        except Exception:
            pass
    return best


def read_thickness_cm(body):
    """Sheet thickness (cm): the sheet-metal rule when the part has one (exact),
    else body volume / largest planar face area (exact for any constant-thickness
    sheet, orientation-independent). Returns 0.0 if undeterminable."""
    # 1) sheet-metal parts carry the truth in their rule / Thickness parameter
    try:
        comp = body.parentComponent
        rule = getattr(comp, 'activeSheetMetalRule', None)   # (verify: activeSheetMetalRule)
        if rule:
            return rule.thickness.value                # (verify: SheetMetalRule.thickness)
    except Exception:
        pass
    try:
        comp = body.parentComponent
        for prm in comp.modelParameters:               # sheet-metal 'Thickness' parameter
            if prm.role == 'ThicknessDimension' or prm.name == 'Thickness':   # (verify)
                return prm.value
    except Exception:
        pass
    # 2) geometric measurement
    try:
        area = _largest_planar_face_area(body)
        vol = body.physicalProperties.volume
        return vol / area if area > 1e-12 else 0.0
    except Exception:
        return 0.0


def read_material_names(body):
    """(physical_material_name, sheetmetal_rule_name) — either may be ''. The rule
    name often carries the alloy (e.g. '.063\" 5052') when the physical material is
    still the generic default."""
    phys = ''
    try:
        mat = getattr(body, 'material', None)          # (verify: BRepBody.material)
        phys = mat.name if mat else ''
    except Exception:
        pass
    rule = ''
    try:
        r = getattr(body.parentComponent, 'activeSheetMetalRule', None)
        rule = r.name if r else ''
    except Exception:
        pass
    return phys, rule


def pattern_clearance_ok(body, frame, pattern):
    """True if the pattern band lies on the body (no slot runs past an edge or into
    a cutout). Samples the band rectangle's corners/edge-midpoints just inside the
    band and checks point containment against the host body."""
    if body is None:
        return True                                    # nothing to check against
    pts = []
    for prof in pattern["profiles"]:
        pts.extend(G.sample_profile(prof, n=4))
    if not pts:
        return True
    umin = min(p.x for p in pts); umax = max(p.x for p in pts)
    vmin = min(p.y for p in pts); vmax = max(p.y for p in pts)
    origin, u_hat, v_hat, _length, _face = frame
    probes = [(u, v)
              for u in (umin, (umin + umax) / 2.0, umax)
              for v in (vmin, 0.0, vmax)]
    for (u, v) in probes:
        p = _pt3d(origin, u_hat, v_hat, u, v)
        try:
            c = body.pointContainment(p)
            if c == adsk.fusion.PointContainment.PointOutsidePointContainment:
                return False
        except Exception:
            continue                                   # can't check THIS probe; try the rest
    return True


# ---- legacy face-based readers (kept for the Stage-1a scripts) ------------------

def measure_thickness_cm(face):
    """Deprecated in favour of read_thickness_cm(body); kept for the scripts."""
    return read_thickness_cm(face.body)


def read_material_name(face):
    mat = getattr(face.body, "material", None)
    return mat.name if mat else ""
