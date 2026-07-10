# commands/waveBendCmd/entry.py — the Wave Bend command (dialog + preview + execute)
# and the material-change watcher that keeps existing cuts up to date.
# Structure follows Fusion's official add-in template (commandDialog sample).
import json
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
CMD_Description = ('Cut a SendCutSend-style wave relief pattern along selected bend '
                   'lines so the flat part can be folded by hand.')
IS_PROMOTED = True

WORKSPACE_ID = 'FusionSolidEnvironment'
PANEL_ID = 'SolidScriptsAddinsPanel'
COMMAND_BESIDE_ID = 'ScriptsManagerCommand'
ICON_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'resources', '')

# repo root = ../../../.. from this file (WaveBend/commands/waveBendCmd/entry.py)
_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
LOG_PATH = os.path.join(_REPO, 'last_run.log')

ATTR_GROUP = 'WaveBend'
ATTR_NAME = 'feature'
ATTR_VERSION = 1

local_handlers = []

# Fallback seed when no body has been measured yet (0.125 in plate).
_FALLBACK_T_CM = 0.3175

# Guard so programmatic .value writes don't re-trigger command_input_changed
# (without it, the Ls<->N interlink ping-pongs forever).
_suppress = False

# Which dialog values are formula-derived (auto) vs typed by the user (override).
# Auto values follow the body when its material/thickness changes later (Part B);
# overridden values are the user's word and never touched.
_auto = {'thickness': True, 'material': True, 'gap': True, 'tab': True, 'fillet': True}

# Guard against the watcher reacting to its own rebuild.
_rebuilding = False

# Cached linear pitch model: solve_pitch is too slow to run per dialog edit, but for
# fixed (gap, tab, fillet, angle, diag) the solved pitch tracks slot_len almost
# exactly as  pitch = slot_len + C.  We solve C once per parameter combination and
# do the interlink algebraically; the preview/execute path uses the real solver.
_pitch_model = {'key': None, 'C': None}

# Cached solved patterns for the preview/execute path (multiple entries: one per
# selected line length). Only genuinely NEW parameter combinations pay the ~1s solve.
_pattern_cache = {}
_PATTERN_CACHE_MAX = 16


def _log_file(msg):
    try:
        with open(LOG_PATH, 'w', encoding='utf-8') as fh:
            fh.write(msg)
    except Exception:
        pass
    futil.log(msg, force_console=True)


def _units():
    try:
        return app.activeProduct.unitsManager.defaultLengthUnits
    except Exception:
        return 'mm'


def _fmt(value_cm):
    """Format an internal (cm) value in the document's display units, 2 decimals
    (formatInternalValue echoes full float precision — unreadable in the status)."""
    try:
        um = app.activeProduct.unitsManager
        units = _units()
        return f'{um.convert(value_cm, "cm", units):.2f} {units}'   # (verify: convert)
    except Exception:
        return f'{value_cm:.3f} cm'


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


def _selected_entities(inputs):
    sel = inputs.itemById('bendLine')
    return [sel.selection(i).entity for i in range(sel.selectionCount)]


def _bend_len(inputs):
    ents = _selected_entities(inputs)
    if not ents:
        return 0.0
    try:
        return FB.local_frame(ents[0])[3]
    except Exception:
        return 0.0


def _set_status(inputs, text):
    box = inputs.itemById('status')
    if box:
        box.text = text


def _get_pattern(bend_len, gap, tab, fil, slot):
    """Exact-solver pattern, cached per parameter combination."""
    key = tuple(round(v, 6) for v in (bend_len, gap, tab, fil, slot))
    if key not in _pattern_cache:
        if len(_pattern_cache) >= _PATTERN_CACHE_MAX:
            _pattern_cache.clear()
        _pattern_cache[key] = G.generate_pattern(
            bend_len, gap, tab, slot, fil,
            config.DEFAULT_END_ANGLE_DEG, diag_len=config.DEFAULT_DIAG_LEN_CM)
    return _pattern_cache[key]


def _snapshot_for(body):
    """What the auto-update watcher compares against later."""
    phys, rule = FB.read_material_names(body)
    return {
        'phys': phys, 'rule': rule,
        'family': config.material_family(phys) or config.material_family(rule) or '',
        't_meas': round(FB.read_thickness_cm(body), 6),
    }


def _tag_feature(cut, sk, entity, body, params):
    """Persist everything the watcher needs to rebuild this cut later."""
    payload = {
        'version': ATTR_VERSION,
        'line_token': entity.entityToken,              # (verify: entityToken)
        'sketch_token': sk.entityToken,
        'body_token': body.entityToken if body else '',
        'params': params,
        'auto': dict(_auto),
        'snapshot': _snapshot_for(body) if body else {},
    }
    cut.attributes.add(ATTR_GROUP, ATTR_NAME, json.dumps(payload))   # (verify: attributes.add)


def _build(inputs):
    """Shared by preview and execute: solve + cut every selected line.

    Phase 1 (no side effects): resolve frames/bodies, solve EVERY pattern, and run
    every clearance check against the still-pristine bodies. An infeasible
    combination raises here, before any geometry exists — so a multi-line build
    never half-commits because of a bad parameter set.
    Phase 2: cut line by line, isolated per line, so one line's API failure cannot
    orphan the others silently.
    Returns (results, warnings).
    """
    entities = _selected_entities(inputs)
    t = inputs.itemById('thickness').value
    gap = inputs.itemById('gap').value
    tab = inputs.itemById('tab').value
    fil = inputs.itemById('fillet').value
    slot = inputs.itemById('slotLen').value
    dd = inputs.itemById('material').selectedItem
    family = dd.name if dd else config.FAMILY_ALUMINUM
    params = {'t': t, 'gap': gap, 'tab': tab, 'fil': fil, 'slot': slot,
              'family': family}

    design = adsk.fusion.Design.cast(app.activeProduct)
    comp = design.rootComponent
    timeline_start = design.timeline.count             # (verify: Design.timeline.count)

    # ---- phase 1: validate everything against pristine geometry ----
    jobs, warnings = [], []
    for i, e in enumerate(entities):
        frame = FB.local_frame(e)
        body = FB.find_host_body(frame)
        pattern = _get_pattern(frame[3], gap, tab, fil, slot)   # may raise ValueError
        if not FB.pattern_clearance_ok(body, frame, pattern):
            warnings.append(f'line {i + 1}: pattern extends past the part edge or into a cutout')
        jobs.append((e, body, pattern))

    # ---- phase 2: cut, isolated per line ----
    results, failures = [], []
    for i, (e, body, pattern) in enumerate(jobs):
        try:
            frame = FB.local_frame(e)   # re-resolve: an earlier cut may have split a shared face
            name = f'Wave Bend ({pattern["count"]} slots)'
            sk, cut = FB.draw_and_cut(comp, pattern, frame, t, name=name)
            _tag_feature(cut, sk, e, body, params)
            results.append({'pattern': pattern, 'cut': cut})
        except Exception:
            futil.log(f'{CMD_NAME}: line {i + 1} failed:\n{traceback.format_exc()}')
            failures.append(i + 1)

    # One readable timeline group around everything we just made.
    try:
        end = design.timeline.count - 1
        if end > timeline_start and results:
            grp = design.timeline.timelineGroups.add(timeline_start, end)   # (verify)
            grp.name = f'Wave Bend x{len(results)}'
    except Exception:
        pass                                           # cosmetic only

    if failures and not results:
        raise RuntimeError(f'all {len(failures)} line(s) failed to cut — see Text Commands')
    for i in failures:
        warnings.append(f'line {i} FAILED to cut (others succeeded) — see Text Commands')
    return results, warnings


def _status_summary(inputs, results, warnings):
    """Human-readable status + validation warnings, in document display units."""
    t = inputs.itemById('thickness').value
    tab = inputs.itemById('tab').value
    min_lig = min(r['pattern']['min_ligament'] for r in results)
    pitch = results[0]['pattern']['pitch']   # pitch depends on params only, not line length
    counts = [str(r['pattern']['count']) for r in results]
    slots = counts[0] if len(counts) == 1 else '+'.join(counts)
    lines = 'line' if len(results) == 1 else f'{len(results)} lines'
    msg = 'OK: {} slots on {}, pitch {}, min ligament {}'.format(
        slots, lines, _fmt(pitch), _fmt(min_lig))
    if tab < t - 1e-9:
        msg += '\nWarning: tab < thickness — the fold ligaments will be weak (rule: tab >= t)'
    for w in warnings:
        msg += f'\nWarning: {w}'
    return msg


# ---------------------------------------------------------------------------
# add-in lifecycle
# ---------------------------------------------------------------------------

def start():
    cmd_def = ui.commandDefinitions.addButtonDefinition(CMD_ID, CMD_NAME, CMD_Description, ICON_FOLDER)
    futil.add_handler(cmd_def.commandCreated, command_created)
    workspace = ui.workspaces.itemById(WORKSPACE_ID)
    panel = workspace.toolbarPanels.itemById(PANEL_ID)
    control = panel.controls.addCommand(cmd_def, COMMAND_BESIDE_ID, False)
    control.isPromoted = IS_PROMOTED
    # Part B: watch for material / sheet-metal-rule changes for as long as we run.
    futil.add_handler(ui.commandTerminated, on_command_terminated)   # (verify: commandTerminated)


def stop():
    workspace = ui.workspaces.itemById(WORKSPACE_ID)
    panel = workspace.toolbarPanels.itemById(PANEL_ID)
    command_control = panel.controls.itemById(CMD_ID)
    command_definition = ui.commandDefinitions.itemById(CMD_ID)
    if command_control:
        command_control.deleteMe()
    if command_definition:
        command_definition.deleteMe()


# ---------------------------------------------------------------------------
# the Wave Bend command
# ---------------------------------------------------------------------------

def command_created(args: adsk.core.CommandCreatedEventArgs):
    futil.log(f'{CMD_NAME} Command Created Event')
    inputs = args.command.commandInputs
    units = _units()

    global _auto
    _auto = {'thickness': True, 'material': True, 'gap': True, 'tab': True, 'fillet': True}

    sel = inputs.addSelectionInput('bendLine', 'Bend lines',
                                   'Select straight edges or sketch lines on the flat face')
    sel.addSelectionFilter('Edges')
    sel.addSelectionFilter('SketchLines')
    sel.setSelectionLimits(1, 0)                       # 1..unlimited

    t = _FALLBACK_T_CM
    gap = config.default_gap_cm(t, config.FAMILY_ALUMINUM)
    inputs.addValueInput('thickness', 'Thickness', units,
                         adsk.core.ValueInput.createByReal(t))
    mat = inputs.addDropDownCommandInput('material', 'Material',
                                         adsk.core.DropDownStyles.TextListDropDownStyle)
    for name in config.MATERIAL_FAMILIES:
        mat.listItems.add(name, name == config.FAMILY_ALUMINUM)
    inputs.addValueInput('gap', 'Gap (cut width)', units,
                         adsk.core.ValueInput.createByReal(gap))
    inputs.addValueInput('tab', 'Tab (min material)', units,
                         adsk.core.ValueInput.createByReal(config.default_tab_cm(t)))
    inputs.addValueInput('fillet', 'Fillet radius', units,
                         adsk.core.ValueInput.createByReal(config.default_fillet_cm(gap)))
    inputs.addValueInput('slotLen', 'Slot length', units,
                         adsk.core.ValueInput.createByReal(config.DEFAULT_SLOT_LEN_CM))
    inputs.addIntegerSpinnerCommandInput('slotCount', 'Slot count', 1, 999, 1, 6)
    status = inputs.addTextBoxCommandInput(
        'status', 'Status', 'Select bend lines to preview the pattern.', 4, True)
    status.isFullWidth = True

    futil.add_handler(args.command.execute, command_execute, local_handlers=local_handlers)
    futil.add_handler(args.command.executePreview, command_preview, local_handlers=local_handlers)
    futil.add_handler(args.command.inputChanged, command_input_changed, local_handlers=local_handlers)
    futil.add_handler(args.command.validateInputs, command_validate_input, local_handlers=local_handlers)
    futil.add_handler(args.command.destroy, command_destroy, local_handlers=local_handlers)


def _reseed_from_body(inputs):
    """Bend line picked: read thickness + material from the host body (works for
    sheet-metal parts and construction-plane sketches too)."""
    ents = _selected_entities(inputs)
    if not ents:
        return
    try:
        frame = FB.local_frame(ents[0])
        body = FB.find_host_body(frame)
        if body is None:
            futil.log(f'{CMD_NAME}: no solid body found near the bend line')
            return
        t = FB.read_thickness_cm(body)
        phys, rule = FB.read_material_names(body)
    except Exception:
        futil.log(f'{CMD_NAME}: could not read body, keeping typed values\n{traceback.format_exc()}')
        return
    family = config.material_family(phys) or config.material_family(rule)
    if _auto['material'] and family:
        dd = inputs.itemById('material')
        for item in dd.listItems:
            item.isSelected = (item.name == family)
    if _auto['thickness'] and t and t > 0:
        inputs.itemById('thickness').value = t
    _reseed_derived(inputs)


def _reseed_derived(inputs):
    """thickness/material changed: re-derive whichever of gap/tab/fillet are auto."""
    t = inputs.itemById('thickness').value
    dd = inputs.itemById('material').selectedItem
    mat = dd.name if dd else config.FAMILY_ALUMINUM
    gap = config.default_gap_cm(t, mat)
    if _auto['gap']:
        inputs.itemById('gap').value = gap
    if _auto['tab']:
        inputs.itemById('tab').value = config.default_tab_cm(t)
    if _auto['fillet']:
        inputs.itemById('fillet').value = config.default_fillet_cm(
            inputs.itemById('gap').value)


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
    # A direct user edit of a seeded field makes it an override from now on.
    if cid in ('thickness', 'gap', 'tab', 'fillet'):
        _auto[cid if cid != 'thickness' else 'thickness'] = False
    if cid == 'material':
        _auto['material'] = False
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
        ok = (inputs.itemById('bendLine').selectionCount >= 1
              and inputs.itemById('thickness').value > 0
              and inputs.itemById('gap').value > 0
              and inputs.itemById('tab').value > 0
              and inputs.itemById('fillet').value > 0
              and inputs.itemById('slotLen').value > 0)
    except Exception:
        ok = False
    args.areInputsValid = ok


def command_preview(args: adsk.core.CommandEventArgs):
    """Live preview: build the REAL pattern + cut; Fusion auto-rolls it back on the
    next input change. isValidResult=True makes OK simply keep the last preview."""
    inputs = args.command.commandInputs
    if inputs.itemById('bendLine').selectionCount == 0:
        return
    try:
        results, warnings = _build(inputs)
        args.isValidResult = True                      # OK reuses this result instantly
        _set_status(inputs, _status_summary(inputs, results, warnings))
        total = sum(r['pattern']['count'] for r in results)
        _log_file('PREVIEW-OK  WaveBend: {} slots on {} line(s); min ligament {:.3f} cm'.format(
            total, len(results), min(r['pattern']['min_ligament'] for r in results)))
    except ValueError as e:
        _set_status(inputs, f'Cannot build pattern: {e}')
        futil.log(f'{CMD_NAME} preview infeasible: {e}')
    except Exception:
        _set_status(inputs, 'Preview failed — see Text Commands for details.')
        futil.log(f'{CMD_NAME} preview error:\n{traceback.format_exc()}')


def command_execute(args: adsk.core.CommandEventArgs):
    """Fallback path: only runs if the last preview was not marked valid."""
    futil.log(f'{CMD_NAME} Command Execute Event')
    try:
        inputs = args.command.commandInputs
        results, warnings = _build(inputs)
        total = sum(r['pattern']['count'] for r in results)
        _log_file('OK  WaveBend add-in: {} slots on {} line(s)'.format(total, len(results)))
    except Exception:
        _log_file('FAIL WaveBend add-in execute:\n' + traceback.format_exc())
        ui.messageBox('Wave Bend failed — see last_run.log / Text Commands for details.')


def command_destroy(args: adsk.core.CommandEventArgs):
    global local_handlers
    local_handlers = []
    futil.log(f'{CMD_NAME} Command Destroy Event')


# ---------------------------------------------------------------------------
# Part B: material-change watcher (one-click confirm, then rebuild)
# ---------------------------------------------------------------------------

# Command ids worth reacting to. Matched as lowercase substrings of the terminated
# command's id; tune with the DEBUG log if a material path is missed.
_WATCH_HINTS = ('material', 'sheetmetal', 'physicalmaterial')


def on_command_terminated(args):
    global _rebuilding
    try:
        cmd_id = getattr(args, 'commandId', '') or ''
        if _rebuilding or cmd_id == CMD_ID:
            return
        low = cmd_id.lower()
        if not any(h in low for h in _WATCH_HINTS):
            if config.DEBUG:
                futil.log(f'WaveBend watcher: ignoring command "{cmd_id}"')
            return
        design = adsk.fusion.Design.cast(app.activeProduct)
        if not design:
            return
        stale = _find_stale_features(design)
        if not stale:
            return
        n = len(stale)
        answer = ui.messageBox(
            'Material or thickness changed on {} part(s) with wave-bend cuts.\n'
            'Update {} wave bend feature(s) to match?'.format(n, n),
            'Wave Bend',
            adsk.core.MessageBoxButtonTypes.YesNoButtonType,           # (verify enum)
            adsk.core.MessageBoxIconTypes.QuestionIconType)
        if answer != adsk.core.DialogResults.DialogYes:                 # (verify enum)
            return
        _rebuilding = True
        try:
            rebuilt = sum(1 for item in stale if _rebuild_feature(design, *item))
        finally:
            _rebuilding = False
        _log_file(f'OK  WaveBend auto-update: rebuilt {rebuilt}/{n} feature(s)')
    except Exception:
        futil.log(f'WaveBend watcher error:\n{traceback.format_exc()}')


def _find_stale_features(design):
    """[(attribute, payload)] for every tagged cut whose material/thickness snapshot
    no longer matches its body AND whose parameters would actually change.

    A feature whose values were ALL hand-overridden can never change, so a body
    edit must not nag the user about it or churn the timeline rebuilding it."""
    stale = []
    for attr in design.findAttributes(ATTR_GROUP, ATTR_NAME):          # (verify)
        try:
            payload = json.loads(attr.value)
            if payload.get('version') != ATTR_VERSION:
                continue
            auto = payload.get('auto', {})
            if not any(auto.get(k, True) for k in ('thickness', 'gap', 'tab', 'fillet')):
                continue                       # fully overridden: body changes are moot
            bodies = design.findEntityByToken(payload.get('body_token', ''))   # (verify)
            body = bodies[0] if bodies else None
            if body is None:
                continue
            snap = payload.get('snapshot', {})
            now = _snapshot_for(body)
            family_matters = auto.get('material', True) and any(
                auto.get(k, True) for k in ('gap', 'fillet'))
            if ((family_matters and now['family'] != snap.get('family', ''))
                    or abs(now['t_meas'] - snap.get('t_meas', 0.0)) > 1e-4):
                stale.append((attr, payload))
        except Exception:
            continue
    return stale


def _rebuild_feature(design, attr, payload):
    """Rebuild one tagged cut with re-derived auto values (overrides preserved).

    Everything that can be validated is validated BEFORE the old feature is
    deleted (the pattern solve is pure math), so an infeasible new parameter set
    leaves the existing cut untouched. Only a hard Fusion API failure after the
    delete can lose the feature — and that is reported loudly, not swallowed."""
    try:
        lines = design.findEntityByToken(payload.get('line_token', ''))
        if not lines:
            futil.log('WaveBend update: bend line no longer exists; skipping one feature')
            return False
        entity = lines[0]
        # Re-resolve the body NOW: earlier rebuilds in this batch may have replaced
        # timeline state, and a pre-resolved handle could be stale.
        bodies = design.findEntityByToken(payload.get('body_token', ''))
        body = bodies[0] if bodies else None
        if body is None:
            futil.log('WaveBend update: host body no longer exists; skipping one feature')
            return False
        params = payload.get('params', {})
        auto = payload.get('auto', {})

        now = _snapshot_for(body)
        t = FB.read_thickness_cm(body) if auto.get('thickness', True) else params['t']
        # The material family follows the body ONLY when the user never overrode the
        # dropdown; an override is the user's word and survives every rebuild.
        stored_family = params.get('family', '')
        if auto.get('material', True):
            family = now['family'] or stored_family or config.FAMILY_ALUMINUM
        else:
            family = stored_family or config.FAMILY_ALUMINUM
        gap = (config.default_gap_cm(t, family) if auto.get('gap', True) else params['gap'])
        tab = (config.default_tab_cm(t) if auto.get('tab', True) else params['tab'])
        fil = (config.default_fillet_cm(gap) if auto.get('fillet', True) else params['fil'])
        slot = params['slot']

        # Validate the new pattern BEFORE touching the old feature.
        frame = FB.local_frame(entity)
        pattern = _get_pattern(frame[3], gap, tab, fil, slot)   # ValueError -> untouched
    except ValueError as e:
        futil.log(f'WaveBend update: new parameters infeasible, feature left as-is: {e}')
        return False
    except Exception:
        futil.log(f'WaveBend update: pre-check failed, feature left as-is:\n{traceback.format_exc()}')
        return False

    try:
        # Point of no return: delete the old cut + sketch, then rebuild.
        cut = attr.parent                                              # (verify: Attribute.parent)
        sketches = design.findEntityByToken(payload.get('sketch_token', ''))
        if cut:
            cut.deleteMe()
        for sk in sketches or []:
            try:
                sk.deleteMe()
            except Exception:
                pass
        frame = FB.local_frame(entity)                 # fresh after the delete
        name = f'Wave Bend ({pattern["count"]} slots)'
        sk_new, cut_new = FB.draw_and_cut(design.rootComponent, pattern, frame, t, name=name)
        new_params = {'t': t, 'gap': gap, 'tab': tab, 'fil': fil, 'slot': slot,
                      'family': family}
        payload_new = {
            'version': ATTR_VERSION,
            'line_token': entity.entityToken,
            'sketch_token': sk_new.entityToken,
            'body_token': body.entityToken,
            'params': new_params,
            'auto': auto,
            'snapshot': now,
        }
        cut_new.attributes.add(ATTR_GROUP, ATTR_NAME, json.dumps(payload_new))
        return True
    except Exception:
        futil.log(f'WaveBend update: rebuild failed AFTER delete:\n{traceback.format_exc()}')
        ui.messageBox('Wave Bend: one cut could not be rebuilt after its old geometry '
                      'was removed. Use Undo (Ctrl+Z) to restore it, then adjust the '
                      'parameters. Details in Text Commands.', 'Wave Bend')
        return False