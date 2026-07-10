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


def draw_and_cut(comp, pattern, frame, depth_cm):
    """Convenience: draw the pattern sketch, then cut it. Returns the cut feature."""
    sk = draw_pattern_sketch(comp, pattern, frame)
    # slot-size ceiling for the profile filter: the largest cell bbox diagonal + slack
    diag = 0.0
    for prof in pattern["profiles"][:2]:               # smile + frown suffice
        pts = G.sample_profile(prof, n=4)
        w = max(p.x for p in pts) - min(p.x for p in pts)
        h = max(p.y for p in pts) - min(p.y for p in pts)
        diag = max(diag, math.hypot(w, h))
    return cut_sketch(comp, sk, depth_cm, max_profile_diag_cm=diag * 1.2)


# ---- Task 7: read thickness + material from the body --------------------------

def measure_thickness_cm(face):
    """Sheet thickness (cm) = body volume / selected-face area.

    For a constant-thickness sheet (a prism: volume = footprint_area * thickness) this
    is exact AND orientation-independent. The previous bounding-box-span approach
    overestimated badly for any plate whose faces were not axis-aligned (the axis span
    then includes the in-plane dimensions, not just the thickness).
    """
    body = face.body                                   # (verify: BRepFace.body)
    area = face.area                                   # footprint of the flat face (verify: BRepFace.area)
    vol = body.physicalProperties.volume               # geometric volume (verify: BRepBody.physicalProperties.volume)
    return vol / area if area > 1e-12 else 0.0


def read_material_name(face):
    body = face.body
    mat = getattr(body, "material", None)              # (verify: BRepBody.material)
    return mat.name if mat else ""
