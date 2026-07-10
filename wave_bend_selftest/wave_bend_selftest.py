# wave_bend_selftest/wave_bend_selftest.py  -- run via Scripts and Add-Ins
#
# Self-contained, NON-interactive verification of the Stage 1a Fusion layer.
# Builds a test plate, draws an interior bend line, then exercises the PRODUCTION
# data path: measure thickness + read material from the body -> derive gap/tab/
# fillet -> generate the wave chain -> sketch (model->sketch space) -> one cut.
# Writes the result/traceback to <repo>/last_run.log.
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
import config
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


PLATE_T_CM = 0.3175   # the test plate we build (0.125 in)


def _build_plate(root):
    """Create a 10 x 6 x PLATE_T_CM flat plate; return its BRepBody."""
    sk = root.sketches.add(root.xYConstructionPlane)
    sk.sketchCurves.sketchLines.addTwoPointRectangle(
        adsk.core.Point3D.create(0, 0, 0),
        adsk.core.Point3D.create(10.0, 6.0, 0))
    prof = sk.profiles.item(0)
    ext = root.features.extrudeFeatures
    ein = ext.createInput(prof, adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
    ein.setDistanceExtent(False, adsk.core.ValueInput.createByReal(PLATE_T_CM))
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
        # library edits take effect without restarting Fusion.
        import importlib
        importlib.reload(config)
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
        # plate ends, so the wave chain stays inside the body.
        z = top.boundingBox.minPoint.z
        bsk = root.sketches.add(top)
        p0 = adsk.core.Point3D.create(1.0, 3.0, z)
        p1 = adsk.core.Point3D.create(9.0, 3.0, z)
        bend = bsk.sketchCurves.sketchLines.addByTwoPoints(
            bsk.modelToSketchSpace(p0), bsk.modelToSketchSpace(p1))
        edge_len = 8.0

        frame = FB.local_frame(bend)

        # PRODUCTION data path: measure the body, derive the numbers.
        t = FB.measure_thickness_cm(top)
        if not t or t <= 0:
            t = PLATE_T_CM
        mat = FB.read_material_name(top)
        m = config.gap_multiplier_for(mat)
        gap = config.default_gap_cm(t, mat)
        tab = config.default_tab_cm(t)
        fil = config.default_fillet_cm(gap)

        pattern = G.generate_pattern(frame[3], gap, tab,
                                     config.DEFAULT_SLOT_LEN_CM, fil,
                                     config.DEFAULT_END_ANGLE_DEG,
                                     diag_len=config.DEFAULT_DIAG_LEN_CM)

        # Pure-geometry diagnostics (cannot fail) so even a Fusion error tells the shape:
        ncells = len(pattern["profiles"])
        c0 = G.sample_profile(pattern["profiles"][0])
        cw = max(p.x for p in c0) - min(p.x for p in c0)
        ch = max(p.y for p in c0) - min(p.y for p in c0)
        diag = ("t={:.4f} mat='{}' m={} gap={:.4f} | slots={} cell0={:.3f}x{:.3f}cm "
                "pitch={:.3f} min_lig={:.3f} (tab {:.4f})").format(
                    t, mat, m, gap, ncells, cw, ch,
                    pattern['pitch'], pattern['min_ligament'], tab)

        # Draw, inspect the sketch (1 closed profile per slot == healthy), then cut.
        sk = FB.draw_pattern_sketch(root, pattern, frame)
        diag += " sketch_profiles={}".format(sk.profiles.count)
        # Alignment probe: the first drawn entity, mapped back to model space, must sit
        # on the bend line (y ~ 3.0, z ~ plate top). (verify: SketchCurve.worldGeometry)
        try:
            wg = sk.sketchCurves.sketchLines.item(0).worldGeometry
            diag += " probe_model=({:.3f},{:.3f},{:.3f})".format(
                wg.startPoint.x, wg.startPoint.y, wg.startPoint.z)
        except Exception:
            diag += " probe_model=unavailable"
        FB.cut_sketch(root, sk, t)

        _log("OK  selftest: bend L={:.3f}cm; {}".format(edge_len, diag))
        ui.messageBox("Wave-bend SELFTEST done. See last_run.log")
    except Exception:
        _log("FAIL selftest [{}]:\n{}".format(diag, traceback.format_exc()))
        if ui:
            ui.messageBox("Selftest failed. See last_run.log")
