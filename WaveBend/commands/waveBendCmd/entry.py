# commands/waveBendCmd/entry.py — the Wave Bend command (dialog + execute).
# Structure follows Fusion's official add-in template (commandDialog sample).
import math
import os
import traceback

import adsk.core
import adsk.fusion

from ...lib import fusionAddInUtils as futil
from ...lib import geometry as G
from ...lib import fusion_build as FB
from ... import config

app = adsk.core.Application.get()
ui = app.userInterface

CMD_ID = f'{config.COMPANY_NAME}_{config.ADDIN_NAME}_waveBend'
CMD_NAME = 'Wave Bend'
CMD_Description = ('Cut a SendCutSend-style wave relief pattern along a selected bend '
                   'line so the flat part can be folded by hand.')
IS_PROMOTED = True

WORKSPACE_ID = 'FusionSolidEnvironment'
PANEL_ID = 'SolidScriptsAddinsPanel'
COMMAND_BESIDE_ID = 'ScriptsManagerCommand'
ICON_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'resources', '')

# repo root = ../../../.. from this file (WaveBend/commands/waveBendCmd/entry.py)
_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
LOG_PATH = os.path.join(_REPO, 'last_run.log')

local_handlers = []

# Fallback seed when no body has been measured yet (0.125 in plate).
_FALLBACK_T_CM = 0.3175

# Guard so programmatic .value writes don't re-trigger command_input_changed
# (without it, the Ls<->N interlink ping-pongs forever).
_suppress = False

# Cached linear pitch model: solve_pitch is too slow to run per dialog edit, but for
# fixed (gap, tab, fillet, angle, diag) the solved pitch tracks slot_len almost
# exactly as  pitch = slot_len + C.  We solve C once per parameter combination and
# do the interlink algebraically; execute() always uses the real solver.
_pitch_model = {'key': None, 'C': None}

_MATERIAL_ITEMS = ('Aluminum', 'Mild Steel', 'Stainless Steel', 'Titanium')


def _log_file(msg):
    try:
        with open(LOG_PATH, 'w', encoding='utf-8') as fh:
            fh.write(msg)
    except Exception:
        pass
    futil.log(msg, force_console=True)


def _material_item_for(name):
    """Map a body's physical-material name to our dropdown items (order matters:
    'stainless' must match before 'steel')."""
    n = (name or '').lower()
    if 'alumin' in n:
        return 'Aluminum'
    if 'stainless' in n:
        return 'Stainless Steel'
    if 'titanium' in n:
        return 'Titanium'
    if 'steel' in n:
        return 'Mild Steel'
    return 'Aluminum'


def _pitch_C(slot_len, gap, tab, fil):
    """C in the linear model pitch = slot_len + C, cached per (gap, tab, fil)."""
    key = (round(gap, 6), round(tab, 6), round(fil, 6))
    if _pitch_model['key'] != key:
        p = G.solve_pitch(slot_len, gap, tab, fil, config.DEFAULT_END_ANGLE_DEG,
                          diag_len=config.DEFAULT_DIAG_LEN_CM)
        _pitch_model['key'] = key
        _pitch_model['C'] = p - slot_len
    return _pitch_model['C']


def _margin(slot_len, gap):
    """Same solid end-margin rule generate_pattern uses (closed form for the cell width)."""
    th = math.radians(config.DEFAULT_END_ANGLE_DEG)
    cell_w = slot_len + 2.0 * config.DEFAULT_DIAG_LEN_CM * math.cos(th) + gap
    return cell_w / 2.0 + gap


def _bend_len(inputs):
    sel = inputs.itemById('bendLine')
    if not sel or sel.selectionCount == 0:
        return 0.0
    try:
        return FB.local_frame(sel.selection(0).entity)[3]
    except Exception:
        return 0.0


def start():
    cmd_def = ui.commandDefinitions.addButtonDefinition(CMD_ID, CMD_NAME, CMD_Description, ICON_FOLDER)
    futil.add_handler(cmd_def.commandCreated, command_created)
    workspace = ui.workspaces.itemById(WORKSPACE_ID)
    panel = workspace.toolbarPanels.itemById(PANEL_ID)
    control = panel.controls.addCommand(cmd_def, COMMAND_BESIDE_ID, False)
    control.isPromoted = IS_PROMOTED


def stop():
    workspace = ui.workspaces.itemById(WORKSPACE_ID)
    panel = workspace.toolbarPanels.itemById(PANEL_ID)
    command_control = panel.controls.itemById(CMD_ID)
    command_definition = ui.commandDefinitions.itemById(CMD_ID)
    if command_control:
        command_control.deleteMe()
    if command_definition:
        command_definition.deleteMe()


def command_created(args: adsk.core.CommandCreatedEventArgs):
    futil.log(f'{CMD_NAME} Command Created Event')
    inputs = args.command.commandInputs

    sel = inputs.addSelectionInput('bendLine', 'Bend line',
                                   'Select a straight edge or sketch line on the flat face')
    sel.addSelectionFilter('Edges')            # (verify: filter accepts linear edges)
    sel.addSelectionFilter('SketchLines')
    sel.setSelectionLimits(1, 1)

    t = _FALLBACK_T_CM
    gap = config.default_gap_cm(t, 'Aluminum')
    inputs.addValueInput('thickness', 'Thickness', 'cm',
                         adsk.core.ValueInput.createByReal(t))
    mat = inputs.addDropDownCommandInput('material', 'Material',
                                         adsk.core.DropDownStyles.TextListDropDownStyle)
    for name in _MATERIAL_ITEMS:
        mat.listItems.add(name, name == 'Aluminum')
    inputs.addValueInput('gap', 'Gap (cut width)', 'cm',
                         adsk.core.ValueInput.createByReal(gap))
    inputs.addValueInput('tab', 'Tab (min material)', 'cm',
                         adsk.core.ValueInput.createByReal(config.default_tab_cm(t)))
    inputs.addValueInput('fillet', 'Fillet radius', 'cm',
                         adsk.core.ValueInput.createByReal(config.default_fillet_cm(gap)))
    inputs.addValueInput('slotLen', 'Slot length', 'cm',
                         adsk.core.ValueInput.createByReal(config.DEFAULT_SLOT_LEN_CM))
    inputs.addIntegerSpinnerCommandInput('slotCount', 'Slot count', 1, 999, 1, 6)

    futil.add_handler(args.command.execute, command_execute, local_handlers=local_handlers)
    futil.add_handler(args.command.inputChanged, command_input_changed, local_handlers=local_handlers)
    futil.add_handler(args.command.validateInputs, command_validate_input, local_handlers=local_handlers)
    futil.add_handler(args.command.destroy, command_destroy, local_handlers=local_handlers)


def _reseed_from_body(inputs):
    """Bend line picked: measure thickness + read material from the host body."""
    sel = inputs.itemById('bendLine')
    if sel.selectionCount == 0:
        return
    try:
        face = FB.local_frame(sel.selection(0).entity)[4]
        t = FB.measure_thickness_cm(face)
        mat_name = FB.read_material_name(face)
    except Exception:
        futil.log(f'{CMD_NAME}: could not read body, keeping typed values')
        return
    if not t or t <= 0:
        return
    item_name = _material_item_for(mat_name)
    dd = inputs.itemById('material')
    for item in dd.listItems:
        item.isSelected = (item.name == item_name)
    inputs.itemById('thickness').value = t
    _reseed_derived(inputs)


def _reseed_derived(inputs):
    """thickness/material changed: re-derive gap, tab, fillet."""
    t = inputs.itemById('thickness').value
    dd = inputs.itemById('material').selectedItem
    mat = dd.name if dd else 'Aluminum'
    gap = config.default_gap_cm(t, mat)
    inputs.itemById('gap').value = gap
    inputs.itemById('tab').value = config.default_tab_cm(t)
    inputs.itemById('fillet').value = config.default_fillet_cm(gap)


def _refresh_count(inputs):
    """slot length (or upstream parameter) changed: recompute the count display."""
    B = _bend_len(inputs)
    if B <= 0:
        return
    gap = inputs.itemById('gap').value
    tab = inputs.itemById('tab').value
    fil = inputs.itemById('fillet').value
    slot = inputs.itemById('slotLen').value
    try:
        pitch = slot + _pitch_C(slot, gap, tab, fil)
        inputs.itemById('slotCount').value = G.fit_count(B, pitch, _margin(slot, gap))
    except ValueError:
        futil.log(f'{CMD_NAME}: infeasible combination, count not updated')


def _slot_from_count(inputs):
    """slot count edited: invert the linear model to a slot length (last-edited-wins)."""
    B = _bend_len(inputs)
    if B <= 0:
        return
    gap = inputs.itemById('gap').value
    tab = inputs.itemById('tab').value
    fil = inputs.itemById('fillet').value
    count = inputs.itemById('slotCount').value
    slot_now = inputs.itemById('slotLen').value
    try:
        C = _pitch_C(slot_now, gap, tab, fil)
    except ValueError:
        futil.log(f'{CMD_NAME}: infeasible combination, slot length not updated')
        return
    th = math.radians(config.DEFAULT_END_ANGLE_DEG)
    # usable(slot) = B - cell_w(slot) - 2*gap ; target pitch = usable / (count - 0.5)
    K = 2.0 * config.DEFAULT_DIAG_LEN_CM * math.cos(th) + 3.0 * gap
    q = max(count - 0.5, 0.5)
    slot = (B - K - q * C) / (q + 1.0)
    min_slot = max(4.0 * fil, 0.2)
    if slot < min_slot:
        futil.log(f'{CMD_NAME}: {count} slots need slot_len<{min_slot:.2f} cm; clamped')
        slot = min_slot
    inputs.itemById('slotLen').value = slot


def command_input_changed(args: adsk.core.InputChangedEventArgs):
    global _suppress
    if _suppress:
        return
    cid = args.input.id
    inputs = args.inputs
    _suppress = True
    try:
        if cid == 'bendLine':
            _reseed_from_body(inputs)
            _refresh_count(inputs)
        elif cid in ('thickness', 'material'):
            _reseed_derived(inputs)
            _refresh_count(inputs)
        elif cid in ('gap', 'tab', 'fillet', 'slotLen'):
            _refresh_count(inputs)
        elif cid == 'slotCount':
            _slot_from_count(inputs)          # last-edited-wins: do NOT recompute count
    except Exception:
        futil.log(f'{CMD_NAME} inputChanged error:\n{traceback.format_exc()}')
    finally:
        _suppress = False


def command_validate_input(args: adsk.core.ValidateInputsEventArgs):
    inputs = args.inputs
    try:
        ok = (inputs.itemById('bendLine').selectionCount == 1
              and inputs.itemById('thickness').value > 0
              and inputs.itemById('gap').value > 0
              and inputs.itemById('tab').value > 0
              and inputs.itemById('fillet').value > 0
              and inputs.itemById('slotLen').value > 0)
    except Exception:
        ok = False
    args.areInputsValid = ok


def command_execute(args: adsk.core.CommandEventArgs):
    futil.log(f'{CMD_NAME} Command Execute Event')
    try:
        inputs = args.command.commandInputs
        entity = inputs.itemById('bendLine').selection(0).entity
        t = inputs.itemById('thickness').value
        gap = inputs.itemById('gap').value
        tab = inputs.itemById('tab').value
        fil = inputs.itemById('fillet').value
        slot = inputs.itemById('slotLen').value

        frame = FB.local_frame(entity)
        design = adsk.fusion.Design.cast(app.activeProduct)
        comp = design.rootComponent
        pattern = G.generate_pattern(frame[3], gap, tab, slot, fil,
                                     config.DEFAULT_END_ANGLE_DEG,
                                     diag_len=config.DEFAULT_DIAG_LEN_CM)
        FB.draw_and_cut(comp, pattern, frame, t)
        _log_file('OK  WaveBend add-in: {} slots, pitch {:.3f} cm, min ligament {:.3f} cm '
                  '(tab {:.3f}); t={:.4f} gap={:.4f}'.format(
                      pattern['count'], pattern['pitch'], pattern['min_ligament'],
                      tab, t, gap))
    except Exception:
        _log_file('FAIL WaveBend add-in execute:\n' + traceback.format_exc())
        ui.messageBox('Wave Bend failed — see last_run.log / Text Commands for details.')


def command_destroy(args: adsk.core.CommandEventArgs):
    global local_handlers
    local_handlers = []
    futil.log(f'{CMD_NAME} Command Destroy Event')
