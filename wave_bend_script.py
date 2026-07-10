# wave_bend_script.py  -- run via Design > Utilities > Scripts and Add-Ins
#
# Stage 1a prototype: select a bend line on your flat part; thickness and material
# are READ FROM THE BODY (gap = multiplier * t; aluminum 0.6, steel/Ti 0.7). Draws
# the SendCutSend-style wave chain and makes one extrude-cut through the thickness.
# Writes a machine-readable record to last_run.log on every run.
import os, sys, traceback
import adsk.core, adsk.fusion

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, os.path.join(HERE, "WaveBend"))
sys.path.insert(0, os.path.join(HERE, "WaveBend", "lib"))
import config
import geometry as G
import fusion_build as FB

LOG_PATH = os.path.join(HERE, "last_run.log")            # the implementer reads THIS file

FALLBACK_THICKNESS_CM = 0.3175   # used only if the body thickness cannot be measured


def _log(msg):
    """Write a clean, machine-readable run record the implementer can Read directly."""
    try:
        with open(LOG_PATH, "w", encoding="utf-8") as fh:
            fh.write(msg)
    except Exception:
        pass
    print(msg)                                           # also -> Text Commands palette


def run(context):
    ui = None
    try:
        # Fusion caches imported modules across runs in one session; force-reload so
        # edits to the library take effect without restarting Fusion.
        import importlib
        importlib.reload(config)
        importlib.reload(G)
        importlib.reload(FB)

        app = adsk.core.Application.get(); ui = app.userInterface
        design = adsk.fusion.Design.cast(app.activeProduct)
        comp = design.rootComponent
        sel = ui.selectEntity("Select the bend line (edge or sketch line)",
                              "Edges,SketchLines")        # (verify selectEntity filter)
        frame = FB.local_frame(sel.entity)
        face = frame[4]

        # Read thickness + material from the body; derive the fabrication numbers.
        t = FB.measure_thickness_cm(face)
        if not t or t <= 0:
            t = FALLBACK_THICKNESS_CM
        mat = FB.read_material_name(face)
        m = config.gap_multiplier_for(mat)
        gap = config.default_gap_cm(t, mat)
        tab = config.default_tab_cm(t)
        fil = config.default_fillet_cm(gap)

        pattern = G.generate_pattern(frame[3], gap, tab,
                                     config.DEFAULT_SLOT_LEN_CM, fil,
                                     config.DEFAULT_END_ANGLE_DEG,
                                     diag_len=config.DEFAULT_DIAG_LEN_CM)
        FB.draw_and_cut(comp, pattern, frame, t)
        _log("OK  Wave bend: {} slots, pitch {:.3f} cm, min ligament {:.3f} cm; "
             "t={:.4f} cm material='{}' (m={}) gap={:.4f} cm".format(
                 pattern['count'], pattern['pitch'], pattern['min_ligament'],
                 t, mat, m, gap))
        ui.messageBox("Wave bend done. See last_run.log")
    except Exception:
        _log("FAIL Wave-bend script:\n" + traceback.format_exc())
        if ui: ui.messageBox("Wave-bend script failed. See last_run.log")
