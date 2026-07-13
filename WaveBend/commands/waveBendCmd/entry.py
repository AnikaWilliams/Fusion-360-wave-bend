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
# Hidden helper command: CustomFeatures.add is refused outside a command's execute
# context (and inside previews), so post-commit wrapping runs via this command.
WRAP_CMD_ID = f'{config.COMPANY_NAME}_{config.ADDIN_NAME}_wrapPending'
# Edit command: what Fusion runs on right-click > Edit Feature on our timeline node.
EDIT_CMD_ID = f'{config.COMPANY_NAME}_{config.ADDIN_NAME}_waveBendEdit'
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
ATTR_VERSION = 2          # v2: payload carries a LIST of bend lines per feature

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

# Custom-feature definition: gives every Wave Bend cut ONE timeline node carrying
# our wave icon. Two hard requirements (live-tested 2026-07-09/10):
#   1. The add-in .manifest MUST have a non-empty "id" (UUID) or every
#      CustomFeatures.add fails with 'RuntimeError: 3 : make params invalid'
#      (see _wrap_custom_feature docstring).
#   2. Wrapping happens inside a command's execute handler — never in a preview.
# Architecture therefore: executePreview draws the OUTLINE sketch only (nothing
# destructive -> nothing rolls back -> selection stays); execute creates
# sketch+cut AND wraps them right there. Fallback on any wrap failure: plain
# named features in a named group — a cut is never lost.
ENABLE_TIMELINE_ICON = True
_custom_def = None

# Selection safety net: the preview rollback drops the visual selection AND can
# remap entity tokens (live-tested: a cached SketchLine token resolved to a SIBLING
# line after rollback, cutting along the wrong line). So we cache the lines' raw
# GEOMETRY — endpoint coordinates in cm — and rebuild frames from coordinates.
_cached_line_geoms = []          # [((x0,y0,z0), (x1,y1,z1)), ...]

# Cached linear pitch model: solve_pitch is too slow to run per dialog edit, but for
# fixed (gap, tab, fillet, style) the solved pitch tracks slot_len almost exactly
# as  pitch = slot_len + C.  We solve C once per parameter combination (kept for
# the whole session, so flipping between styles never re-solves) and do the
# interlink algebraically; the preview/execute path uses the real solver.
_pitch_model = {}                 # (gap, tab, fil, style) -> C
_PITCH_MODEL_MAX = 64

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


def _style(inputs):
    """Selected pattern style key ('wave', 'slot', ...)."""
    dd = inputs.itemById('patternStyle')
    item = dd.selectedItem if dd else None
    return config.pattern_style_for_label(item.name) if item else config.DEFAULT_PATTERN_STYLE


def _diag(inputs):
    """The wave's diagonal end-segment length (user-adjustable; falls back to the
    SendCutSend reference value). Only the wave cell consumes it."""
    inp = inputs.itemById('diagLen')
    v = inp.value if inp else 0.0
    return v if v > 1e-6 else config.DEFAULT_DIAG_LEN_CM


def _pitch_C(slot_len, gap, tab, fil, style, diag):
    """C in the linear model pitch = slot_len + C, cached per parameter set."""
    key = (round(gap, 6), round(tab, 6), round(fil, 6), round(diag, 6), style)
    if key not in _pitch_model:
        if len(_pitch_model) >= _PITCH_MODEL_MAX:
            _pitch_model.clear()
        p = G.solve_pitch(slot_len, gap, tab, fil, config.DEFAULT_END_ANGLE_DEG,
                          diag_len=diag, style=style)
        _pitch_model[key] = p - slot_len
    return _pitch_model[key]


def _margin(slot_len, gap, fil, style, diag):
    """Same solid end-margin rule generate_pattern uses (probe-based cell width)."""
    half_w = G.cell_halfwidth(style, slot_len, gap, fil,
                              config.DEFAULT_END_ANGLE_DEG, diag)
    return half_w + gap


def _selected_entities(inputs):
    sel = inputs.itemById('bendLine')
    return [sel.selection(i).entity for i in range(sel.selectionCount)]


def _line_geom(entity):
    """((x0,y0,z0),(x1,y1,z1)) for a SketchLine (worldGeometry) or linear BRepEdge."""
    geo = entity.worldGeometry if hasattr(entity, 'worldGeometry') else entity.geometry
    p0, p1 = geo.startPoint, geo.endPoint
    return ((p0.x, p0.y, p0.z), (p1.x, p1.y, p1.z))


def _frames_for_build(inputs):
    """Frames for every bend line: from the live selection when present, else
    rebuilt from the cached endpoint coordinates (immune to entity invalidation)."""
    ents = _selected_entities(inputs)
    if ents:
        return [FB.local_frame(e) for e in ents]
    return [FB.frame_from_points(p0, p1) for (p0, p1) in _cached_line_geoms]


def _bend_len(inputs):
    ents = _selected_entities(inputs)
    if ents:
        try:
            return FB.local_frame(ents[0])[3]
        except Exception:
            return 0.0
    if _cached_line_geoms:
        (p0, p1) = _cached_line_geoms[0]
        return math.dist(p0, p1)
    return 0.0


def _set_status(inputs, text):
    box = inputs.itemById('status')
    if box:
        box.text = text


def _get_pattern(bend_len, gap, tab, fil, slot, style, diag):
    """Exact-solver pattern, cached per parameter combination."""
    key = tuple(round(v, 6) for v in (bend_len, gap, tab, fil, slot, diag)) + (style,)
    if key not in _pattern_cache:
        if len(_pattern_cache) >= _PATTERN_CACHE_MAX:
            _pattern_cache.clear()
        _pattern_cache[key] = G.generate_pattern(
            bend_len, gap, tab, slot, fil,
            config.DEFAULT_END_ANGLE_DEG, diag_len=diag, style=style)
    return _pattern_cache[key]


def _snapshot_for(body):
    """What the auto-update watcher compares against later."""
    phys, rule = FB.read_material_names(body)
    return {
        'phys': phys, 'rule': rule,
        'family': config.material_family(phys) or config.material_family(rule) or '',
        't_meas': round(FB.read_thickness_cm(body), 6),
    }


def _wrap_custom_feature(comp, sk, cut, name):
    """Fold the sketch + cut into ONE timeline node carrying the Wave Bend icon.

    REQUIRES a non-empty "id" (any UUID) in the add-in .manifest: without it
    every CustomFeatures.add call fails with the unrelated-sounding
    'RuntimeError: 3 : make params invalid'. The docs claim the field "is not
    used and can be left empty" and Fusion's own template omits it, but Fusion
    needs it to associate custom features with their owning add-in
    (forums.autodesk.com t5/.../error-when-adding-custom-feature/td-p/13777839).

    NO custom parameters, deliberately: every custom parameter automatically
    becomes a dependency of the feature, so any touch of it fires a
    customFeatureCompute event that nothing here answers (the wrapped extrude
    is outside the supported compute-edit set) — a feature stuck waiting on an
    unanswered compute is a known way to wedge a document. Autodesk's
    RoundEmboss sample (same shape as ours: wrapped sketch+extrude, no compute
    handler) only adds parameters it wires into the wrapped features' native
    parameters; gap/tab have no native counterpart, so they stay out. The cut's
    values are persisted in the feature attributes instead (_tag_feature).

    Single attempt, deliberately: retrying customFeatures.add inside the same
    command transaction after a failure can commit partially-created custom-
    feature state (documented in the custom-feature feedback thread).
    Returns the custom feature's entityToken ('' if unavailable)."""
    if not ENABLE_TIMELINE_ICON or _custom_def is None:
        return ''
    cfs = comp.features.customFeatures                     # (verify: customFeatures)
    before = cfs.count
    try:
        ci = cfs.createInput(_custom_def)                  # (verify: createInput)
        ci.setStartAndEndFeatures(sk, cut)                 # (verify: setStartAndEndFeatures)
        cf = cfs.add(ci)
        try:
            cf.name = name
        except Exception:
            pass
        futil.log(f'WRAP OK: {name}')
        return cf.entityToken
    except Exception as e:
        futil.log(f'WRAP failed: {type(e).__name__}: {e}')
        # A failed add must leave nothing behind — partial custom-feature state
        # committed with the transaction can corrupt the document.
        try:
            while cfs.count > before:
                cfs.item(cfs.count - 1).deleteMe()
        except Exception:
            pass
    futil.log(f'{CMD_NAME}: custom-feature wrap failed (plain features kept)', force_console=True)
    return ''


def _tag_feature(cut, sk, lines, body, params, custom_token=''):
    """Persist everything the watcher/editor needs to rebuild this feature later.

    `lines` is a LIST of bend lines, each stored as raw endpoint COORDINATES
    ((x0,y0,z0),(x1,y1,z1)) — entity tokens proved unstable across preview
    rollbacks (they can remap to sibling sketch lines); coordinates survive
    anything. One feature may carry several lines (one command run, one face)."""
    payload = {
        'version': ATTR_VERSION,
        'lines': list(lines),
        'sketch_token': sk.entityToken,
        'body_token': body.entityToken if body else '',
        'custom_token': custom_token,
        'params': params,
        'auto': dict(_auto),
        'snapshot': _snapshot_for(body) if body else {},
    }
    cut.attributes.add(ATTR_GROUP, ATTR_NAME, json.dumps(payload))   # (verify: attributes.add)


def _payload_lines(payload):
    """Bend lines from a payload, tolerant of the v1 single-line format."""
    if payload.get('lines'):
        return payload['lines']
    lg = payload.get('line_geom')
    return [lg] if lg else []


def _build(inputs, sketch_only=False):
    """Shared by preview and execute: solve every selected line, then build.

    sketch_only=True (preview): draw ONLY the wave outline sketches — no cut, no
    wrapper. Nothing destructive happens, so the preview rollback has nothing to
    invalidate (keeps the selection input alive) and it is fast.
    sketch_only=False (execute): sketch + cut + custom-feature wrap, all inside
    THIS command execution — the only context Fusion allows the wrap in.

    Phase 1 (no side effects): resolve frames/bodies, solve EVERY pattern, and run
    every clearance check against the still-pristine bodies. An infeasible
    combination raises here, before any geometry exists — so a multi-line build
    never half-commits because of a bad parameter set.
    Phase 2: build line by line, isolated per line, so one line's API failure
    cannot orphan the others silently.
    Returns (results, warnings).
    """
    frames = _frames_for_build(inputs)
    t = inputs.itemById('thickness').value
    gap = inputs.itemById('gap').value
    tab = inputs.itemById('tab').value
    fil = inputs.itemById('fillet').value
    slot = inputs.itemById('slotLen').value
    style = _style(inputs)
    diag = _diag(inputs)
    dd = inputs.itemById('material').selectedItem
    family = dd.name if dd else config.FAMILY_ALUMINUM
    params = {'t': t, 'gap': gap, 'tab': tab, 'fil': fil, 'slot': slot,
              'family': family, 'style': style, 'diag': diag}

    design = adsk.fusion.Design.cast(app.activeProduct)
    comp = design.rootComponent
    timeline_start = design.timeline.count             # (verify: Design.timeline.count)

    # ---- phase 1: validate everything against pristine geometry ----
    jobs, warnings = [], []
    for i, frame in enumerate(frames):
        body = FB.find_host_body(frame)
        pattern = _get_pattern(frame[3], gap, tab, fil, slot, style, diag)   # may raise ValueError
        if not FB.pattern_clearance_ok(body, frame, pattern):
            warnings.append(f'line {i + 1}: pattern extends past the part edge or into a cutout')
        origin, u_hat, _v, length, _f = frame
        line_geom = ((origin.x, origin.y, origin.z),
                     (origin.x + u_hat.x * length, origin.y + u_hat.y * length,
                      origin.z + u_hat.z * length))
        jobs.append((line_geom, body, pattern))

    # ---- phase 2: build, grouped by face — one command run produces ONE sketch,
    # ONE cut and ONE custom feature per face (normally: exactly one node) ----
    results, failures, wrapped_all = [], [], True
    pending = list(enumerate(jobs))
    while pending:
        # ALWAYS re-resolve frames from raw coordinates against CURRENT geometry:
        # an earlier group's cut may have split/replaced faces, and coordinate
        # lookup is immune to that.
        resolved = []
        for idx, (line_geom, body, pattern) in pending:
            try:
                resolved.append((idx, line_geom, body, pattern,
                                 FB.frame_from_points(*line_geom)))
            except Exception:
                futil.log(f'{CMD_NAME}: line {idx + 1} failed:\n{traceback.format_exc()}')
                failures.append(idx + 1)
        if not resolved:
            break
        face_token = resolved[0][4][4].entityToken
        group = [r for r in resolved if r[4][4].entityToken == face_token]
        group_ids = {r[0] for r in group}
        pending = [(idx, jobs[idx]) for (idx, *_rest) in resolved
                   if idx not in group_ids]
        sk = None
        try:
            pairs = [(pattern, frame) for _i, _lg, _b, pattern, frame in group]
            total = sum(p['count'] for p, _f in pairs)
            name = _feature_name(style, total, len(pairs))
            if sketch_only:
                FB.draw_patterns_sketch(comp, pairs)
                for _i, _lg, _b, pattern, _f in group:
                    results.append({'pattern': pattern, 'cut': None, 'wrapped': False})
                continue
            sk, cut = FB.draw_and_cut_multi(comp, pairs, t, name=name)
            cf_token = _wrap_custom_feature(comp, sk, cut, name)
            if not cf_token:
                wrapped_all = False
            lines = [lg for _i, lg, _b, _p, _f in group]
            _tag_feature(cut, sk, lines, group[0][2], params, custom_token=cf_token)
            for _i, _lg, _b, pattern, _f in group:
                results.append({'pattern': pattern, 'cut': cut, 'wrapped': bool(cf_token)})
        except Exception:
            futil.log(f'{CMD_NAME}: group of {len(group)} line(s) failed:\n'
                      f'{traceback.format_exc()}')
            failures.extend(i + 1 for i in sorted(group_ids))
            if sk is not None:
                try:
                    sk.deleteMe()                      # never leave an orphan sketch behind
                except Exception:
                    pass

    # Fallback timeline identity: only when some cut did NOT get its custom-feature
    # node (the custom feature IS the readable timeline entry otherwise).
    if not sketch_only and not wrapped_all:
        try:
            end = design.timeline.count - 1
            if end > timeline_start and results:
                grp = design.timeline.timelineGroups.add(timeline_start, end)   # (verify)
                grp.name = f'Wave Bend x{len(results)}'
        except Exception:
            pass                                       # cosmetic only

    if failures and not results:
        raise RuntimeError(f'all {len(failures)} line(s) failed to cut — see Text Commands')
    for i in failures:
        warnings.append(f'line {i} FAILED to cut (others succeeded) — see Text Commands')
    return results, warnings


def _feature_name(style, count, nlines=1):
    """Timeline node name; the style is called out for everything but the classic wave."""
    where = f'{count} slots' if nlines <= 1 else f'{count} slots, {nlines} lines'
    if style == config.DEFAULT_PATTERN_STYLE:
        return f'Wave Bend ({where})'
    return f'Wave Bend ({config.pattern_label_for_style(style)}, {where})'


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
    if t > config.MAX_RELIABLE_THICKNESS_CM + 1e-9:
        msg += ('\nWarning: thickness over 3 mm — hand-bend relief patterns risk '
                'cracking at this gauge (see docs/pattern-research.md)')
    for w in warnings:
        msg += f'\nWarning: {w}'
    return msg


# ---------------------------------------------------------------------------
# add-in lifecycle
# ---------------------------------------------------------------------------

_watcher_handler = None


def start():
    # Idempotent: clear any stale registration from a previous load in this session
    # (a stop() that failed half-way leaves a definition behind, and an unguarded
    # addButtonDefinition would then throw and abort the whole start).
    stale_def = ui.commandDefinitions.itemById(CMD_ID)
    if stale_def:
        try:
            stale_def.deleteMe()
        except Exception:
            pass
    workspace = ui.workspaces.itemById(WORKSPACE_ID)
    panel = workspace.toolbarPanels.itemById(PANEL_ID)
    stale_ctl = panel.controls.itemById(CMD_ID)
    if stale_ctl:
        try:
            stale_ctl.deleteMe()
        except Exception:
            pass

    cmd_def = ui.commandDefinitions.addButtonDefinition(CMD_ID, CMD_NAME, CMD_Description, ICON_FOLDER)
    futil.add_handler(cmd_def.commandCreated, command_created)
    control = panel.controls.addCommand(cmd_def, COMMAND_BESIDE_ID, False)
    control.isPromoted = IS_PROMOTED

    # The hidden wrap command (no button, no inputs; executes straight through).
    stale_wrap = ui.commandDefinitions.itemById(WRAP_CMD_ID)
    if stale_wrap:
        try:
            stale_wrap.deleteMe()
        except Exception:
            pass
    wrap_def = ui.commandDefinitions.addButtonDefinition(
        WRAP_CMD_ID, 'Wave Bend (internal)', 'Internal: applies timeline icons')
    futil.add_handler(wrap_def.commandCreated, _wrap_cmd_created)
    # Part B: watch for material / sheet-metal-rule changes for as long as we run.
    # Keep the handler reference so stop() can detach it from the native event —
    # clear_handlers() alone leaves a zombie watcher alive across reloads.
    global _watcher_handler
    _watcher_handler = futil.add_handler(ui.commandTerminated, on_command_terminated)
    # The edit command (no button): Fusion invokes it for right-click > Edit
    # Feature / double-click on our timeline nodes via editCommandId below.
    stale_edit = ui.commandDefinitions.itemById(EDIT_CMD_ID)
    if stale_edit:
        try:
            stale_edit.deleteMe()
        except Exception:
            pass
    edit_def = ui.commandDefinitions.addButtonDefinition(
        EDIT_CMD_ID, 'Edit Wave Bend', 'Edit an existing Wave Bend feature')
    futil.add_handler(edit_def.commandCreated, edit_command_created)
    # Timeline identity: the custom-feature definition that puts the Wave Bend icon
    # on every cut's timeline node. (verify: CustomFeatureDefinition.create)
    global _custom_def
    try:
        _custom_def = adsk.fusion.CustomFeatureDefinition.create(
            f'{config.COMPANY_NAME}.{config.ADDIN_NAME}.waveBend', CMD_NAME, ICON_FOLDER)
        _custom_def.editCommandId = EDIT_CMD_ID        # (verify: editCommandId)
    except Exception:
        # e.g. definition already registered from a previous load in this session
        futil.log(f'{CMD_NAME}: custom-feature definition unavailable:\n{traceback.format_exc()}')
        _custom_def = None


def stop():
    global _watcher_handler
    if _watcher_handler is not None:
        try:
            ui.commandTerminated.remove(_watcher_handler)   # (verify: Event.remove)
        except Exception:
            pass
        _watcher_handler = None
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
    wrap_def = ui.commandDefinitions.itemById(WRAP_CMD_ID)
    try:
        if wrap_def:
            wrap_def.deleteMe()
    except Exception:
        pass
    edit_def = ui.commandDefinitions.itemById(EDIT_CMD_ID)
    try:
        if edit_def:
            edit_def.deleteMe()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# the Wave Bend command
# ---------------------------------------------------------------------------

def command_created(args: adsk.core.CommandCreatedEventArgs):
    futil.log(f'{CMD_NAME} Command Created Event')
    inputs = args.command.commandInputs
    units = _units()

    global _auto, _cached_line_geoms, _suppress
    _auto = {'thickness': True, 'material': True, 'gap': True, 'tab': True, 'fillet': True}
    _cached_line_geoms = []

    sel = inputs.addSelectionInput('bendLine', 'Bend lines',
                                   'Select straight edges or sketch lines on the flat face')
    sel.addSelectionFilter('Edges')
    sel.addSelectionFilter('SketchLines')
    sel.setSelectionLimits(1, 0)                       # 1..unlimited

    t = _FALLBACK_T_CM
    gap = config.default_gap_cm(t, config.FAMILY_ALUMINUM)
    _param_inputs(inputs, units, {
        'style': config.DEFAULT_PATTERN_STYLE, 't': t, 'family': config.FAMILY_ALUMINUM,
        'gap': gap, 'tab': config.default_tab_cm(t),
        'fil': config.default_fillet_cm(gap), 'slot': config.DEFAULT_SLOT_LEN_CM,
        'diag': config.DEFAULT_DIAG_LEN_CM, 'count': 6,
        'status_text': 'Select bend lines to preview the pattern.',
    })

    # Adopt pre-selected bend lines (standard Fusion command behavior): anything the
    # user (or automation) selected before launching the command flows into the input.
    try:
        pre = [ui.activeSelections.item(i).entity for i in range(ui.activeSelections.count)]
        adopted = 0
        for e in pre:
            try:
                if e.objectType in (adsk.fusion.SketchLine.classType(),
                                    adsk.fusion.BRepEdge.classType()):
                    if sel.addSelection(e):            # (verify: addSelection)
                        adopted += 1
            except Exception:
                continue
        if adopted:
            # inputChanged does not fire for programmatic adds: seed manually.
            _suppress = True
            try:
                live = _selected_entities(inputs)
                if live:
                    _cached_line_geoms = [_line_geom(e) for e in live]
                _reseed_from_body(inputs)
                _refresh_count(inputs)
            finally:
                _suppress = False
    except Exception:
        futil.log(f'{CMD_NAME}: preselection adoption failed:\n{traceback.format_exc()}')

    futil.add_handler(args.command.execute, command_execute, local_handlers=local_handlers)
    futil.add_handler(args.command.executePreview, command_preview, local_handlers=local_handlers)
    futil.add_handler(args.command.inputChanged, command_input_changed, local_handlers=local_handlers)
    futil.add_handler(args.command.validateInputs, command_validate_input, local_handlers=local_handlers)
    futil.add_handler(args.command.destroy, command_destroy, local_handlers=local_handlers)


def _param_inputs(inputs, units, seed):
    """The shared parameter inputs (everything except the bend-line selection),
    seeded with the given values. Used by both the create and the edit dialog."""
    style_dd = inputs.addDropDownCommandInput(
        'patternStyle', 'Pattern style', adsk.core.DropDownStyles.TextListDropDownStyle)
    for key, label in config.PATTERN_STYLE_LABELS:
        style_dd.listItems.add(label, key == seed['style'])
    inputs.addValueInput('thickness', 'Thickness', units,
                         adsk.core.ValueInput.createByReal(seed['t']))
    mat = inputs.addDropDownCommandInput('material', 'Material',
                                         adsk.core.DropDownStyles.TextListDropDownStyle)
    for name in config.MATERIAL_FAMILIES:
        mat.listItems.add(name, name == seed['family'])
    inputs.addValueInput('gap', 'Gap (cut width)', units,
                         adsk.core.ValueInput.createByReal(seed['gap']))
    inputs.addValueInput('tab', 'Tab (min material)', units,
                         adsk.core.ValueInput.createByReal(seed['tab']))
    inputs.addValueInput('fillet', 'Fillet radius', units,
                         adsk.core.ValueInput.createByReal(seed['fil']))
    inputs.addValueInput('slotLen', 'Slot length', units,
                         adsk.core.ValueInput.createByReal(seed['slot']))
    diag_in = inputs.addValueInput('diagLen', 'End length', units,
                                   adsk.core.ValueInput.createByReal(seed['diag']))
    diag_in.tooltip = ('Length of the angled end segments of each wave slot '
                       '(the diagonal runs that sweep away from the bend line)')
    diag_in.isVisible = (seed['style'] == G.STYLE_WAVE)
    inputs.addIntegerSpinnerCommandInput('slotCount', 'Slot count', 1, 999, 1,
                                         int(seed.get('count', 6)))
    status = inputs.addTextBoxCommandInput('status', 'Status',
                                           seed.get('status_text', ''), 4, True)
    status.isFullWidth = True


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
    """thickness/material/style changed: re-derive whichever of gap/tab/fillet
    are auto. The gap default is style-aware (research kerf floors)."""
    t = inputs.itemById('thickness').value
    dd = inputs.itemById('material').selectedItem
    mat = dd.name if dd else config.FAMILY_ALUMINUM
    gap = config.default_gap_cm(t, mat, style=_style(inputs))
    if _auto['gap']:
        inputs.itemById('gap').value = gap
    if _auto['tab']:
        inputs.itemById('tab').value = config.default_tab_cm(t)
    if _auto['fillet']:
        inputs.itemById('fillet').value = config.default_fillet_cm(
            inputs.itemById('gap').value)


def _apply_slot_floor(inputs):
    """Auto-lengthen the slot to the shortest the current style can build (the
    meander's squared arms need clearance the wave doesn't). Only ever raises
    the value, so a valid user slot is left untouched. Returns True if changed."""
    style = _style(inputs)
    gap = inputs.itemById('gap').value
    fil = inputs.itemById('fillet').value
    floor = G.min_slot_len(style, gap, fil)
    if inputs.itemById('slotLen').value < floor - 1e-9:
        inputs.itemById('slotLen').value = floor
        return True
    return False


def _refresh_count(inputs):
    """slot length (or upstream parameter) changed: recompute the count display."""
    B = _bend_len(inputs)
    if B <= 0:
        return
    gap = inputs.itemById('gap').value
    tab = inputs.itemById('tab').value
    fil = inputs.itemById('fillet').value
    slot = inputs.itemById('slotLen').value
    style = _style(inputs)
    diag = _diag(inputs)
    try:
        pitch = slot + _pitch_C(slot, gap, tab, fil, style, diag)
        inputs.itemById('slotCount').value = G.fit_count(
            B, pitch, _margin(slot, gap, fil, style, diag))
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
    style = _style(inputs)
    diag = _diag(inputs)
    try:
        C = _pitch_C(slot_now, gap, tab, fil, style, diag)
    except ValueError:
        futil.log(f'{CMD_NAME}: infeasible combination, slot length not updated')
        return
    # usable(slot) = B - cell_w(slot) - 2*gap ; target pitch = usable / (count - 0.5).
    # K folds the style's slot-independent width overhead into the linear model:
    # cell_w(slot) + 2*gap ~= slot + K (cell width grows ~1:1 with slot length).
    K = (2.0 * G.cell_halfwidth(style, slot_now, gap, fil, config.DEFAULT_END_ANGLE_DEG,
                                diag) - slot_now + 2.0 * gap)
    q = max(count - 0.5, 0.5)
    slot = (B - K - q * C) / (q + 1.0)
    min_slot = G.min_slot_len(style, gap, fil)         # style-specific buildable floor
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
            live = _selected_entities(inputs)
            if live:                                   # cache tokens as the safety net
                global _cached_line_geoms
                _cached_line_geoms = [_line_geom(e) for e in live]
            _reseed_from_body(inputs)
            _refresh_count(inputs)
        elif cid in ('thickness', 'material'):
            _reseed_derived(inputs)
            _apply_slot_floor(inputs)     # gap moved -> the buildable floor moved
            _refresh_count(inputs)
        elif cid == 'patternStyle':
            _reseed_derived(inputs)       # style-aware kerf floor (auto gap only)
            _apply_slot_floor(inputs)     # auto-lengthen slot for e.g. the meander
            # The diagonal end length only exists on the wave cell.
            diag_in = inputs.itemById('diagLen')
            if diag_in:
                diag_in.isVisible = (_style(inputs) == G.STYLE_WAVE)
            _refresh_count(inputs)
        elif cid in ('gap', 'fillet'):
            _apply_slot_floor(inputs)     # floor depends on gap/fillet
            _refresh_count(inputs)
        elif cid in ('tab', 'slotLen', 'diagLen'):
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
        ok = ((inputs.itemById('bendLine').selectionCount >= 1 or bool(_cached_line_geoms))
              and inputs.itemById('thickness').value > 0
              and inputs.itemById('gap').value > 0
              and inputs.itemById('tab').value > 0
              and inputs.itemById('fillet').value > 0
              and inputs.itemById('slotLen').value > 0
              and inputs.itemById('diagLen').value > 0)
    except Exception:
        ok = False
    args.areInputsValid = ok


def command_preview(args: adsk.core.CommandEventArgs):
    """Live preview: draw the wave OUTLINE sketches only. No cut and no wrapper —
    nothing destructive, so the rollback between edits can't invalidate the
    selection, and the preview is fast. The real cut + custom-feature wrap happen
    in execute (isValidResult stays False so execute always runs on OK)."""
    inputs = args.command.commandInputs
    if inputs.itemById('bendLine').selectionCount == 0 and not _cached_line_geoms:
        return
    try:
        results, warnings = _build(inputs, sketch_only=True)
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
    """The real build: sketch + cut + custom-feature wrap (same-execution context)."""
    futil.log(f'{CMD_NAME} Command Execute Event')
    try:
        inputs = args.command.commandInputs
        results, warnings = _build(inputs, sketch_only=False)
        total = sum(r['pattern']['count'] for r in results)
        wrapped = len({id(r['cut']) for r in results if r.get('wrapped')})
        _log_file('OK  WaveBend add-in: {} slots on {} line(s) ({} custom-feature node(s))'.format(
            total, len(results), wrapped))
    except Exception:
        _log_file('FAIL WaveBend add-in execute:\n' + traceback.format_exc())
        ui.messageBox('Wave Bend failed — see last_run.log / Text Commands for details.')


def command_destroy(args: adsk.core.CommandEventArgs):
    global local_handlers
    local_handlers = []
    futil.log(f'{CMD_NAME} Command Destroy Event')


# ---------------------------------------------------------------------------
# Edit Feature (right-click / double-click on a Wave Bend timeline node)
# ---------------------------------------------------------------------------

# What the edit dialog is operating on: {'custom_token', 'payload'}.
_edit_ctx = None


def _find_feature_payload(design, cf_token):
    """(attribute, payload) of the tagged cut whose wrapper is cf_token."""
    for attr in design.findAttributes(ATTR_GROUP, ATTR_NAME):
        try:
            payload = json.loads(attr.value)
            if payload.get('custom_token') == cf_token:
                return attr, payload
        except Exception:
            continue
    return None, None


def edit_command_created(args: adsk.core.CommandCreatedEventArgs):
    """Fusion invokes this via editCommandId. The feature being edited arrives
    as the active selection; its stored payload seeds the same dialog inputs
    as the create command (minus the bend-line selection — the lines are fixed)."""
    global _edit_ctx, _auto, _cached_line_geoms, _suppress
    futil.log(f'{CMD_NAME} Edit Command Created Event')
    _edit_ctx = None
    inputs = args.command.commandInputs
    design = adsk.fusion.Design.cast(app.activeProduct)

    cf = None
    try:
        for i in range(ui.activeSelections.count):
            e = ui.activeSelections.item(i).entity
            if e.objectType == adsk.fusion.CustomFeature.classType():
                cf = adsk.fusion.CustomFeature.cast(e)
                break
    except Exception:
        pass
    attr, payload = (None, None)
    if cf is not None:
        attr, payload = _find_feature_payload(design, cf.entityToken)
    if payload is None:
        status = inputs.addTextBoxCommandInput(
            'status', 'Status',
            'Wave Bend data was not found on this feature — it may predate the '
            'add-in version that stores editable parameters. Delete and recut it.',
            4, True)
        status.isFullWidth = True
        futil.add_handler(args.command.destroy, command_destroy, local_handlers=local_handlers)
        return

    p = payload.get('params', {})
    _edit_ctx = {'custom_token': payload.get('custom_token', ''), 'payload': payload}
    _auto = dict(payload.get('auto', _auto))
    _cached_line_geoms = [tuple(map(tuple, lg)) for lg in _payload_lines(payload)]

    _suppress = True
    try:
        _param_inputs(inputs, _units(), {
            'style': p.get('style', config.DEFAULT_PATTERN_STYLE),
            't': p.get('t', _FALLBACK_T_CM),
            'family': p.get('family', config.FAMILY_ALUMINUM),
            'gap': p.get('gap', 0.1), 'tab': p.get('tab', 0.1),
            'fil': p.get('fil', 0.05), 'slot': p.get('slot', config.DEFAULT_SLOT_LEN_CM),
            'diag': p.get('diag', config.DEFAULT_DIAG_LEN_CM), 'count': 6,
            'status_text': f'Editing {len(_cached_line_geoms)} bend line(s). '
                           'Changes rebuild the whole feature on OK.',
        })
        _refresh_count(inputs)
    finally:
        _suppress = False

    futil.add_handler(args.command.execute, edit_command_execute, local_handlers=local_handlers)
    futil.add_handler(args.command.inputChanged, command_input_changed, local_handlers=local_handlers)
    futil.add_handler(args.command.validateInputs, edit_command_validate, local_handlers=local_handlers)
    futil.add_handler(args.command.destroy, command_destroy, local_handlers=local_handlers)


def edit_command_validate(args: adsk.core.ValidateInputsEventArgs):
    inputs = args.inputs
    try:
        ok = (_edit_ctx is not None
              and inputs.itemById('thickness').value > 0
              and inputs.itemById('gap').value > 0
              and inputs.itemById('tab').value > 0
              and inputs.itemById('fillet').value > 0
              and inputs.itemById('slotLen').value > 0
              and inputs.itemById('diagLen').value > 0)
    except Exception:
        ok = False
    args.areInputsValid = ok


def edit_command_execute(args: adsk.core.CommandEventArgs):
    """Rebuild the edited feature with the dialog values (same machinery as the
    material-change auto-rebuild, with the user's values as explicit overrides)."""
    futil.log(f'{CMD_NAME} Edit Command Execute Event')
    global _edit_ctx
    ctx, _edit_ctx = _edit_ctx, None
    if ctx is None:
        return
    try:
        inputs = args.command.commandInputs
        design = adsk.fusion.Design.cast(app.activeProduct)
        attr, payload = _find_feature_payload(design, ctx['custom_token'])
        if attr is None:
            _log_file('FAIL WaveBend edit: feature payload vanished')
            return
        old = payload.get('params', {})
        dd = inputs.itemById('material').selectedItem
        new_params = {
            't': inputs.itemById('thickness').value,
            'gap': inputs.itemById('gap').value,
            'tab': inputs.itemById('tab').value,
            'fil': inputs.itemById('fillet').value,
            'slot': inputs.itemById('slotLen').value,
            'diag': _diag(inputs),
            'style': _style(inputs),
            'family': dd.name if dd else old.get('family', config.FAMILY_ALUMINUM),
        }
        # A field the user left untouched keeps its stored auto flag; a changed
        # field becomes an override (the user's word survives future rebuilds).
        stored_auto = payload.get('auto', {})
        auto = {}
        for key, pkey in (('thickness', 't'), ('gap', 'gap'), ('tab', 'tab'),
                          ('fillet', 'fil')):
            unchanged = abs(new_params[pkey] - old.get(pkey, -1.0)) < 1e-9
            auto[key] = stored_auto.get(key, True) if unchanged else False
        auto['material'] = (stored_auto.get('material', True)
                            if new_params['family'] == old.get('family') else False)
        ok = _rebuild_feature(design, attr, payload,
                              params_override=new_params, auto_override=auto)
        if ok:
            _log_file(f'OK  WaveBend edit: {len(_payload_lines(payload))} line(s) rebuilt')
        else:
            _log_file('FAIL WaveBend edit — see Text Commands')
    except Exception:
        _log_file('FAIL WaveBend edit:\n' + traceback.format_exc())
        ui.messageBox('Wave Bend edit failed — see Text Commands for details.',
                      'Wave Bend')


# ---------------------------------------------------------------------------
# Part B: material-change watcher (one-click confirm, then rebuild)
# ---------------------------------------------------------------------------

# Command ids worth reacting to. Matched as lowercase substrings of the terminated
# command's id; tune with the DEBUG log if a material path is missed.
_WATCH_HINTS = ('material', 'sheetmetal', 'physicalmaterial')


# Rebuild jobs handed from the watcher (no command context) to the hidden
# command's execute (legal context for CustomFeatures.add): list of (attr, payload).
_pending_rebuilds = []


def _wrap_cmd_created(args: adsk.core.CommandCreatedEventArgs):
    # No inputs: Fusion runs execute immediately, giving us a legal context
    # for CustomFeatures.add during material-change rebuilds.
    futil.add_handler(args.command.execute, _rebuild_cmd_execute, local_handlers=local_handlers)
    try:
        args.command.isAutoExecute = True              # (verify: Command.isAutoExecute)
    except Exception:
        pass


def _rebuild_cmd_execute(args: adsk.core.CommandEventArgs):
    """Perform the queued material-change rebuilds inside a command execution, so
    the rebuilt cuts get their custom-feature timeline node back."""
    global _pending_rebuilds, _rebuilding
    jobs, _pending_rebuilds = _pending_rebuilds, []
    if not jobs:
        return
    design = adsk.fusion.Design.cast(app.activeProduct)
    if not design:
        return
    _rebuilding = True
    try:
        rebuilt = sum(1 for (attr, payload) in jobs if _rebuild_feature(design, attr, payload))
    finally:
        _rebuilding = False
    _log_file(f'OK  WaveBend auto-update: rebuilt {rebuilt}/{len(jobs)} feature(s)')


def _trigger_rebuilds():
    """Execute the hidden command, which performs _pending_rebuilds in-context."""
    try:
        wrap_def = ui.commandDefinitions.itemById(WRAP_CMD_ID)
        if wrap_def:
            wrap_def.execute()                         # (verify: CommandDefinition.execute)
            return True
    except Exception:
        futil.log(f'{CMD_NAME}: rebuild trigger failed:\n{traceback.format_exc()}')
    return False


def on_command_terminated(args):
    global _pending_rebuilds, _rebuilding
    try:
        cmd_id = getattr(args, 'commandId', '') or ''
        if _rebuilding or cmd_id in (WRAP_CMD_ID, CMD_ID):
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
        _pending_rebuilds = list(stale)
        if not _trigger_rebuilds():
            # hidden command unavailable: rebuild without the icon rather than not at all
            _pending_rebuilds = []
            _rebuilding = True
            try:
                rebuilt = sum(1 for item in stale if _rebuild_feature(design, *item))
            finally:
                _rebuilding = False
            _log_file(f'OK  WaveBend auto-update: rebuilt {rebuilt}/{n} feature(s), no icons')
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
            if payload.get('version') not in (1, ATTR_VERSION):
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


def _rebuild_feature(design, attr, payload, params_override=None, auto_override=None):
    """Rebuild one tagged feature (which may carry SEVERAL bend lines) with
    re-derived auto values — or, for the Edit Feature dialog, with the explicit
    `params_override`/`auto_override` the user just entered.

    Everything that can be validated is validated BEFORE the old feature is
    deleted (the pattern solve is pure math), so an infeasible new parameter set
    leaves the existing cut untouched. Only a hard Fusion API failure after the
    delete can lose the feature — and that is reported loudly, not swallowed."""
    try:
        lines = _payload_lines(payload)
        if not lines:
            futil.log('WaveBend update: payload has no bend lines; skipping one feature')
            return False
        # Re-resolve the body NOW: earlier rebuilds in this batch may have replaced
        # timeline state, and a pre-resolved handle could be stale.
        bodies = design.findEntityByToken(payload.get('body_token', ''))
        body = bodies[0] if bodies else None
        if body is None:
            futil.log('WaveBend update: host body no longer exists; skipping one feature')
            return False
        auto = dict(payload.get('auto', {}))
        if auto_override is not None:
            auto = dict(auto_override)

        if params_override is not None:
            params = dict(params_override)
            t, family = params['t'], params['family']
            gap, tab, fil = params['gap'], params['tab'], params['fil']
            style = params.get('style', config.DEFAULT_PATTERN_STYLE)
            slot = max(params['slot'],
                       G.min_slot_len(style, gap, fil))
            diag = params.get('diag', config.DEFAULT_DIAG_LEN_CM)
            now = _snapshot_for(body)
        else:
            params = payload.get('params', {})
            now = _snapshot_for(body)
            t = FB.read_thickness_cm(body) if auto.get('thickness', True) else params['t']
            # The material family follows the body ONLY when the user never overrode
            # the dropdown; an override is the user's word and survives every rebuild.
            stored_family = params.get('family', '')
            if auto.get('material', True):
                family = now['family'] or stored_family or config.FAMILY_ALUMINUM
            else:
                family = stored_family or config.FAMILY_ALUMINUM
            style = params.get('style', config.DEFAULT_PATTERN_STYLE)
            gap = (config.default_gap_cm(t, family, style=style)
                   if auto.get('gap', True) else params['gap'])
            tab = (config.default_tab_cm(t) if auto.get('tab', True) else params['tab'])
            fil = (config.default_fillet_cm(gap) if auto.get('fillet', True) else params['fil'])
            # A gap-widening material change can push the stored slot below what the
            # style can build (e.g. the meander) — auto-lengthen so the rebuild holds.
            slot = max(params['slot'], G.min_slot_len(style, gap, fil))
            diag = params.get('diag', config.DEFAULT_DIAG_LEN_CM)

        # Validate EVERY line's new pattern BEFORE touching the old feature.
        patterns = []
        for line_geom in lines:
            frame = FB.frame_from_points(*line_geom)
            patterns.append(_get_pattern(frame[3], gap, tab, fil, slot, style, diag))
    except ValueError as e:
        futil.log(f'WaveBend update: new parameters infeasible, feature left as-is: {e}')
        return False
    except Exception:
        futil.log(f'WaveBend update: pre-check failed, feature left as-is:\n{traceback.format_exc()}')
        return False

    try:
        # Point of no return: delete the old wrapper + cut + sketch, then rebuild.
        # Deleting the custom-feature wrapper may or may not cascade to its children
        # depending on API behaviour, so every delete is individually tolerant.
        cut = attr.parent                                              # (verify: Attribute.parent)
        for cf in design.findEntityByToken(payload.get('custom_token', '')) or []:
            try:
                cf.deleteMe()
            except Exception:
                pass
        sketches = design.findEntityByToken(payload.get('sketch_token', ''))
        try:
            if cut:
                cut.deleteMe()
        except Exception:
            pass                                       # wrapper delete already took it
        for sk in sketches or []:
            try:
                sk.deleteMe()
            except Exception:
                pass
        # Fresh frames after the delete, one sketch + one cut for the whole group.
        pairs = [(patterns[i], FB.frame_from_points(*lines[i]))
                 for i in range(len(lines))]
        total = sum(p['count'] for p, _f in pairs)
        name = _feature_name(style, total, len(pairs))
        comp = design.rootComponent
        sk_new, cut_new = FB.draw_and_cut_multi(comp, pairs, t, name=name)
        cf_token = _wrap_custom_feature(comp, sk_new, cut_new, name)
        new_params = {'t': t, 'gap': gap, 'tab': tab, 'fil': fil, 'slot': slot,
                      'family': family, 'style': style, 'diag': diag}
        payload_new = {
            'version': ATTR_VERSION,
            'lines': lines,
            'sketch_token': sk_new.entityToken,
            'body_token': body.entityToken,
            'custom_token': cf_token,
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