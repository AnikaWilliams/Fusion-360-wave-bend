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
import geometry as G


def _pt3d(origin, u_hat, v_hat, u, v):
    # map local (u, v) [cm] onto the model frame -> Point3D [cm]
    x = origin.x + u_hat.x * u + v_hat.x * v
    y = origin.y + u_hat.y * u + v_hat.y * v
    z = origin.z + u_hat.z * u + v_hat.z * v
    return adsk.core.Point3D.create(x, y, z)   # (verify: Point3D.create signature)


def local_frame(entity):
    """Return (origin Point3D, u_hat Vector3D, v_hat Vector3D, length_cm, planar_face)."""
    # BRepEdge path: edge.geometry is a Line3D; faces[0] gives the sketch plane. (verify)
    geo = entity.geometry
    p0 = geo.startPoint; p1 = geo.endPoint
    u = adsk.core.Vector3D.create(p1.x - p0.x, p1.y - p0.y, p1.z - p0.z)
    length = u.length
    u.normalize()
    face = entity.faces.item(0) if hasattr(entity, "faces") else None   # (verify)
    n = face.geometry.normal if face else adsk.core.Vector3D.create(0, 0, 1)
    n.normalize()
    v = n.crossProduct(u)        # in-plane perpendicular (verify cross order/handedness)
    v.normalize()
    return p0, u, v, length, face


def draw_and_cut(comp, pattern, frame, depth_cm):
    origin, u_hat, v_hat, _length, face = frame
    sk = comp.sketches.add(face)                       # (verify: sketches.add(planarFace))
    lines = sk.sketchCurves.sketchLines
    arcs = sk.sketchCurves.sketchArcs
    for profile in pattern["profiles"]:
        for seg in profile:
            if seg[0] == "line":
                _, a, b = seg
                lines.addByTwoPoints(_pt3d(origin, u_hat, v_hat, a.x, a.y),
                                     _pt3d(origin, u_hat, v_hat, b.x, b.y))
            else:
                _, c, r, a0, a1, a, b = seg
                am = (a0 + a1) / 2.0
                mid = G.Pt(c.x + r * math.cos(am), c.y + r * math.sin(am))
                arcs.addByThreePoints(                 # (verify: addByThreePoints)
                    _pt3d(origin, u_hat, v_hat, a.x, a.y),
                    _pt3d(origin, u_hat, v_hat, mid.x, mid.y),
                    _pt3d(origin, u_hat, v_hat, b.x, b.y))
    # one cut consuming every closed profile in the sketch
    prof_coll = adsk.core.ObjectCollection.create()
    for p in sk.profiles:
        prof_coll.add(p)
    extrudes = comp.features.extrudeFeatures
    cut_input = extrudes.createInput(
        prof_coll, adsk.fusion.FeatureOperations.CutFeatureOperation)   # (verify enum)
    # through-all both directions is safest for a relief cut (verify ExtentDefinition API):
    cut_input.setAllExtent(adsk.fusion.ExtentDirections.SymmetricExtentDirection)
    return extrudes.add(cut_input)


# ---- Task 7: read thickness + material from the body --------------------------

def measure_thickness_cm(face):
    """Thickness = body bounding-box extent along the face normal (cm)."""
    body = face.body                                   # (verify: BRepFace.body)
    bb = body.boundingBox                              # (verify: BRepBody.boundingBox)
    n = face.geometry.normal; n.normalize()
    spans = (abs(bb.maxPoint.x - bb.minPoint.x),
             abs(bb.maxPoint.y - bb.minPoint.y),
             abs(bb.maxPoint.z - bb.minPoint.z))
    # project the box extent onto |normal|; for an axis-aligned plate this is the
    # span along the dominant normal axis:
    axis = max(range(3), key=lambda i: abs((n.x, n.y, n.z)[i]))
    return spans[axis]


def read_material_name(face):
    body = face.body
    mat = getattr(body, "material", None)              # (verify: BRepBody.material)
    return mat.name if mat else ""
