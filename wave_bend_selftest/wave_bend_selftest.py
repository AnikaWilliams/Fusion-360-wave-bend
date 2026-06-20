# wave_bend_selftest/wave_bend_selftest.py  -- run via Scripts and Add-Ins
#
# Self-contained, NON-interactive verification of the Stage 1a Fusion layer.
# Builds a test plate, picks a long top edge programmatically, runs the production
# pipeline (local_frame -> generate_pattern -> draw_and_cut) plus the body readers,
# and writes the result/traceback to <repo>/last_run.log.
#
# Lives in a Fusion-conventional folder (folder name == script name) and locates
# the repo root by walking up to the folder that contains "WaveBend".
import os, sys, traceback
import adsk.core, adsk.fusion

HERE = os.path.dirname(os.path.realpath(__file__))


def _find_repo(start):
    d = start
    for _ in range(6):
        if os.path.isdir(os.path.join(d, "WaveBend")):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return start


REPO = _find_repo(HERE)
sys.path.insert(0, os.path.join(REPO, "WaveBend"))
sys.path.insert(0, os.path.join(REPO, "WaveBend", "lib"))
import geometry as G
import fusion_build as FB

LOG_PATH = os.path.join(REPO, "last_run.log")


def _log(msg):
    try:
        with open(LOG_PATH, "w", encoding="utf-8") as fh:
            fh.write(msg)
    except Exception:
        pass
    print(msg)


# Stage 1a inputs (cm): 0.125 in plate, 0.7 gap, ~0.65 in slot.
THICKNESS_CM = 0.3175
GAP_CM       = THICKNESS_CM * 0.7
TAB_CM       = THICKNESS_CM
SLOT_LEN_CM  = 1.651
FILLET_CM    = GAP_CM * 0.3   # must be < gap/2 or the angled cell ends collapse


def _build_plate(root):
    """Create a 10 x 6 x 0.3175 cm flat plate; return its BRepBody."""
    sk = root.sketches.add(root.xYConstructionPlane)
    sk.sketchCurves.sketchLines.addTwoPointRectangle(
        adsk.core.Point3D.create(0, 0, 0),
        adsk.core.Point3D.create(10.0, 6.0, 0))
    prof = sk.profiles.item(0)
    ext = root.features.extrudeFeatures
    ein = ext.createInput(prof, adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
    ein.setDistanceExtent(False, adsk.core.ValueInput.createByReal(THICKNESS_CM))
    plate = ext.add(ein)
    return plate.bodies.item(0)


def _top_face(body):
    """Planar face whose normal is +Z and which sits highest."""
    top = None; best_z = -1e9
    for f in body.faces:
        if f.geometry.surfaceType == adsk.core.SurfaceTypes.PlaneSurfaceType:
            pl = adsk.core.Plane.cast(f.geometry)
            cz = (f.boundingBox.minPoint.z + f.boundingBox.maxPoint.z) / 2.0
            if pl.normal.z > 0.9 and cz > best_z:
                best_z = cz; top = f
    return top


def run(context):
    ui = None
    diag = "n/a"
    try:
        # Fusion caches imported modules across runs in one session; force-reload so
        # edits to geometry.py / fusion_build.py take effect without restarting Fusion.
        import importlib
        importlib.reload(G)
        importlib.reload(FB)

        app = adsk.core.Application.get(); ui = app.userInterface
        if not adsk.fusion.Design.cast(app.activeProduct):
            app.documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType)
        design = adsk.fusion.Design.cast(app.activeProduct)
        root = design.rootComponent

        body = _build_plate(root)
        top = _top_face(body)
        if top is None:
            raise RuntimeError("could not find the top face of the plate")
        # Interior bend line: a centerline drawn ON the top face, inset from the
        # plate ends, so the straddling wave pattern stays inside the body.
        z = top.boundingBox.minPoint.z                 # top-face plane height (== thickness)
        bsk = root.sketches.add(top)
        bend = bsk.sketchCurves.sketchLines.addByTwoPoints(
            adsk.core.Point3D.create(1.0, 3.0, z),
            adsk.core.Point3D.create(9.0, 3.0, z))
        edge_len = 8.0                                  # 9 - 1, the bend-line length in cm

        frame = FB.local_frame(bend)
        pattern = G.generate_pattern(frame[3], GAP_CM, TAB_CM, SLOT_LEN_CM, FILLET_CM, 40.0)

        # Pure-geometry diagnostics (cannot fail) so even a Fusion error tells me the shape:
        ncells = len(pattern["profiles"])
        c0 = G.sample_profile(pattern["profiles"][0])
        cw = max(p.x for p in c0) - min(p.x for p in c0)
        ch = max(p.y for p in c0) - min(p.y for p in c0)
        diag = "cells={} cell0={:.3f}x{:.3f}cm pitch={:.3f} min_lig={:.3f}".format(
            ncells, cw, ch, pattern['pitch'], pattern['min_ligament'])

        # Draw, inspect the sketch (1 closed profile per cell == healthy), then cut.
        sk = FB.draw_pattern_sketch(root, pattern, frame)
        diag += " sketch_profiles={}".format(sk.profiles.count)
        FB.cut_sketch(root, sk, THICKNESS_CM)

        t_meas = FB.measure_thickness_cm(top)
        mat = FB.read_material_name(top)

        _log("OK  selftest: bend L={:.3f}cm; {}; measured t={:.4f}cm; material='{}'".format(
            edge_len, diag, t_meas, mat))
        ui.messageBox("Wave-bend SELFTEST done. See last_run.log")
    except Exception:
        _log("FAIL selftest [{}]:\n{}".format(diag, traceback.format_exc()))
        if ui:
            ui.messageBox("Selftest failed. See last_run.log")
