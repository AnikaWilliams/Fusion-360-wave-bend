# wave_bend_script.py  -- run via Design > Utilities > Scripts and Add-Ins
#
# Stage 1a run-once prototype. Hard-coded inputs; proves the Fusion cut pipeline
# (select line -> sketch the wave pattern -> one extrude-cut) before we build the
# packaged add-in. Writes a machine-readable record to last_run.log on every run.
import os, sys, traceback
import adsk.core, adsk.fusion

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, os.path.join(HERE, "WaveBend"))
sys.path.insert(0, os.path.join(HERE, "WaveBend", "lib"))
import geometry as G
import fusion_build as FB

LOG_PATH = os.path.join(HERE, "last_run.log")            # the implementer reads THIS file


def _log(msg):
    """Write a clean, machine-readable run record the implementer can Read directly."""
    try:
        with open(LOG_PATH, "w", encoding="utf-8") as fh:
            fh.write(msg)
    except Exception:
        pass
    print(msg)                                           # also -> Text Commands palette


# ---- HARD-CODED Stage 1a inputs (cm). 0.125 in plate, 0.7 gap, etc. ----
THICKNESS_CM = 0.3175
GAP_CM       = THICKNESS_CM * 0.7
TAB_CM       = THICKNESS_CM
SLOT_LEN_CM  = 1.651
FILLET_CM    = GAP_CM * 0.3   # must be < gap/2 or build_cell rejects the degenerate ends


def run(context):
    ui = None
    try:
        app = adsk.core.Application.get(); ui = app.userInterface
        design = adsk.fusion.Design.cast(app.activeProduct)
        comp = design.rootComponent
        sel = ui.selectEntity("Select the bend line (edge or sketch line)",
                              "Edges,SketchLines")        # (verify selectEntity filter)
        frame = FB.local_frame(sel.entity)
        pattern = G.generate_pattern(frame[3], GAP_CM, TAB_CM, SLOT_LEN_CM, FILLET_CM, 40.0)
        FB.draw_and_cut(comp, pattern, frame, THICKNESS_CM)
        _log("OK  Wave bend: {} cells/row, pitch {:.3f} cm, min ligament {:.3f} cm".format(
             pattern['count'], pattern['pitch'], pattern['min_ligament']))
        ui.messageBox("Wave bend done. See last_run.log")
    except Exception:
        _log("FAIL Wave-bend script:\n" + traceback.format_exc())
        if ui: ui.messageBox("Wave-bend script failed. See last_run.log")
