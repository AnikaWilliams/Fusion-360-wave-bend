# commands/dxfExportCmd/entry.py — "Export DXF": write the selected flat face
# (plate outline + every cut) as a millimeter DXF ready for SendCutSend upload.
import os
import traceback

import adsk.core
import adsk.fusion

from ...lib import fusionAddInUtils as futil
from ...lib import dxf_post
from ... import config

app = adsk.core.Application.get()
ui = app.userInterface

CMD_ID = f'{config.COMPANY_NAME}_{config.ADDIN_NAME}_dxfExport'
CMD_NAME = 'Export DXF'
CMD_Description = ('Export the selected flat face — outline and all cuts — as a '
                   '1:1 millimeter DXF for laser cutting (SendCutSend-ready).')
IS_PROMOTED = True

WORKSPACE_ID = 'FusionSolidEnvironment'
PANEL_ID = 'SolidScriptsAddinsPanel'
COMMAND_BESIDE_ID = f'{config.COMPANY_NAME}_{config.ADDIN_NAME}_waveBend'
ICON_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'resources', '')

local_handlers = []

# Success report deferred to the destroy handler: a blocking messageBox inside
# execute keeps the (already-finished) command dialog lingering behind it.
_pending_report = None


def start():
    # Idempotent: a stale definition/control from a crashed reload must not block us.
    for stale in (ui.commandDefinitions.itemById(CMD_ID),):
        try:
            if stale:
                stale.deleteMe()
        except Exception:
            pass
    cmd_def = ui.commandDefinitions.addButtonDefinition(
        CMD_ID, CMD_NAME, CMD_Description, ICON_FOLDER)
    futil.add_handler(cmd_def.commandCreated, command_created)
    workspace = ui.workspaces.itemById(WORKSPACE_ID)
    panel = workspace.toolbarPanels.itemById(PANEL_ID)
    try:
        old = panel.controls.itemById(CMD_ID)
        if old:
            old.deleteMe()
    except Exception:
        pass
    control = panel.controls.addCommand(cmd_def, COMMAND_BESIDE_ID, False)
    control.isPromoted = IS_PROMOTED


def stop():
    workspace = ui.workspaces.itemById(WORKSPACE_ID)
    panel = workspace.toolbarPanels.itemById(PANEL_ID)
    command_control = panel.controls.itemById(CMD_ID)
    command_definition = ui.commandDefinitions.itemById(CMD_ID)
    try:
        if command_control:
            command_control.deleteMe()
    except Exception:
        pass
    try:
        if command_definition:
            command_definition.deleteMe()
    except Exception:
        pass


def command_created(args: adsk.core.CommandCreatedEventArgs):
    futil.log(f'{CMD_NAME} Command Created Event')
    inputs = args.command.commandInputs

    sel = inputs.addSelectionInput(
        'flatFace', 'Flat face',
        'Select the flat face to export (outline and all cuts come with it)')
    sel.addSelectionFilter('PlanarFaces')
    sel.setSelectionLimits(1, 1)

    status = inputs.addTextBoxCommandInput(
        'status', 'Status',
        'The DXF is written at 1:1 scale in millimeters.', 3, True)
    status.isFullWidth = True

    # Adopt a pre-selected planar face, same convention as the Wave Bend command.
    try:
        for i in range(ui.activeSelections.count):
            e = ui.activeSelections.item(i).entity
            if e.objectType == adsk.fusion.BRepFace.classType():
                face = adsk.fusion.BRepFace.cast(e)
                if face and face.geometry.objectType == adsk.core.Plane.classType():
                    if sel.addSelection(e):
                        break
    except Exception:
        pass

    futil.add_handler(args.command.execute, command_execute, local_handlers=local_handlers)
    futil.add_handler(args.command.validateInputs, command_validate,
                      local_handlers=local_handlers)
    futil.add_handler(args.command.destroy, command_destroy, local_handlers=local_handlers)


def command_validate(args: adsk.core.ValidateInputsEventArgs):
    try:
        args.areInputsValid = args.inputs.itemById('flatFace').selectionCount == 1
    except Exception:
        args.areInputsValid = False


def command_destroy(args: adsk.core.CommandEventArgs):
    global local_handlers, _pending_report
    local_handlers = []
    if _pending_report:
        msg, _pending_report = _pending_report, None
        try:
            ui.messageBox(msg, 'Wave Bend — Export DXF')
        except Exception:
            pass


def _default_filename(face):
    doc = app.activeDocument.name or 'design'
    try:
        body = face.body.name
    except Exception:
        body = 'body'
    bad = '<>:"/\\|?*'
    clean = ''.join(c for c in f'{doc} - {body}' if c not in bad).strip()
    return f'{clean or "wave bend"}.dxf'


def _ask_save_path(face):
    dlg = ui.createFileDialog()                            # (verify: createFileDialog)
    dlg.title = 'Export DXF (millimeters)'
    dlg.filter = 'DXF files (*.dxf)'
    dlg.initialFilename = _default_filename(face)
    if dlg.showSave() != adsk.core.DialogResults.DialogOK:  # (verify: showSave)
        return None
    return dlg.filename


def command_execute(args: adsk.core.CommandEventArgs):
    global _pending_report
    futil.log(f'{CMD_NAME} Command Execute Event')
    sk = None
    try:
        inputs = args.command.commandInputs
        face = adsk.fusion.BRepFace.cast(
            inputs.itemById('flatFace').selection(0).entity)
        out_path = _ask_save_path(face)
        if not out_path:
            return                                          # user cancelled: no-op

        design = adsk.fusion.Design.cast(app.activeProduct)
        comp = face.body.parentComponent

        # Temp sketch ON the face; purge whatever auto-projection added (that
        # preference is user-controlled, so never rely on it), then project the
        # face explicitly — its boundary arrives as outer outline + one closed
        # loop per cut.
        sk = comp.sketches.add(face)                        # (verify: sketches.add)
        try:
            sk.isComputeDeferred = True                     # bulk edit: solve once at the end
            for i in range(sk.sketchCurves.count - 1, -1, -1):
                try:
                    sk.sketchCurves.item(i).deleteMe()
                except Exception:
                    pass
            sk.project(face)                                # (verify: Sketch.project)
        finally:
            try:
                sk.isComputeDeferred = False                # saveAsDXF needs a solved sketch
            except Exception:
                pass

        tmp_path = out_path + '.tmp'
        if not sk.saveAsDXF(tmp_path):                      # (verify: saveAsDXF)
            raise RuntimeError('Sketch.saveAsDXF returned False')
        with open(tmp_path, 'r', encoding='utf-8', errors='replace') as f:
            text = f.read()

        # Unit normalization, belt and braces: measure the face's true width and
        # find which standard factor maps the DXF onto it; fall back to the
        # declared $INSUNITS; final fallback assumes Fusion's internal cm.
        bb = face.boundingBox
        face_w_mm = (bb.maxPoint.x - bb.minPoint.x) * 10.0  # cm -> mm
        face_w_mm = max(face_w_mm, (bb.maxPoint.y - bb.minPoint.y) * 10.0,
                        (bb.maxPoint.z - bb.minPoint.z) * 10.0)
        dxf_w = dxf_post.extents_width(text)
        scale = dxf_post.infer_scale(dxf_w, face_w_mm)
        how = f'measured against the face ({face_w_mm:.1f} mm)'
        if scale is None:
            scale = dxf_post.scale_for_declared_units(dxf_post.read_insunits(text))
            how = 'from the declared DXF units'
        if scale is None:
            scale = 10.0                                    # Fusion internal cm
            how = 'assumed Fusion-internal cm'
        text_mm, stats = dxf_post.to_mm(text, scale)

        with open(out_path, 'w', encoding='utf-8', newline='\n') as f:
            f.write(text_mm)
        try:
            os.remove(tmp_path)
        except OSError:
            pass

        ents = ', '.join(f'{v} {k.lower()}{"s" if v != 1 else ""}'
                         for k, v in sorted(stats.items()))
        futil.log(f'{CMD_NAME}: wrote {out_path} (scale x{scale:g}, {how}; {ents})',
                  force_console=True)
        _pending_report = f'DXF exported (1:1 mm):\n{out_path}\n\n{ents}'
    except Exception:
        futil.log(f'{CMD_NAME} failed:\n{traceback.format_exc()}', force_console=True)
        _pending_report = 'DXF export failed — see Text Commands for details.'
    finally:
        if sk is not None:
            try:
                sk.deleteMe()                               # the design stays untouched
            except Exception:
                pass
