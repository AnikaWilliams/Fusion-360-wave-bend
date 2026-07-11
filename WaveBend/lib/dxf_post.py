"""DXF post-processing: normalize a Fusion sketch DXF to millimeters. Pure; no adsk.

Fusion's Sketch.saveAsDXF writes coordinates in the sketch's internal units and
is inconsistent about declaring them ($INSUNITS is often absent). SendCutSend and
most laser services expect an explicit, correctly-scaled file, so this module
rescales every geometric value to mm and stamps $INSUNITS = 4.

A DXF file is a flat list of (group code, value) line pairs. We walk those pairs
with just enough state to know WHICH numbers are lengths:
  - point coordinates (codes 10-13 / 20-23 / 30-33) scale everywhere;
  - code 40/41/43 scale only where they mean a length (arc/circle radius,
    polyline widths, text height) -- for SPLINE they are knots/weights (parameter
    space) and for ELLIPSE the axis ratio, which must NOT be scaled;
  - angles (50, 51) never scale.
"""

# entity type -> the 4x-series codes that are true lengths for that entity
_RADIUS_CODES = {
    'ARC': (40,),
    'CIRCLE': (40,),
    'LWPOLYLINE': (40, 41, 43),
    'POLYLINE': (40, 41),
    'TEXT': (40,),
    'MTEXT': (40, 41),
}
_COORD_CODES = frozenset((10, 11, 12, 13, 20, 21, 22, 23, 30, 31, 32, 33))

# $INSUNITS values (DXF spec)
INSUNITS_MM = 4
_UNIT_TO_MM = {0: None, 1: 25.4, 2: 304.8, 4: 1.0, 5: 10.0, 6: 1000.0}


def read_insunits(text):
    """The declared $INSUNITS value, or None when the header does not carry one."""
    lines = text.splitlines()
    for i in range(len(lines) - 3):
        if lines[i].strip() == '9' and lines[i + 1].strip() == '$INSUNITS':
            try:
                return int(lines[i + 3].strip())
            except (ValueError, IndexError):
                return None
    return None


def scale_for_declared_units(insunits):
    """mm-conversion factor for a declared $INSUNITS (None when undeclared/unknown)."""
    return _UNIT_TO_MM.get(insunits)


def infer_scale(dxf_width, expected_width_mm, tolerance=0.01):
    """Empirical unit detection: which standard factor maps the DXF's measured
    width onto the known real width (in mm)? Returns the factor, or None when
    nothing matches within `tolerance` (relative)."""
    if dxf_width <= 0 or expected_width_mm <= 0:
        return None
    for s in (1.0, 10.0, 25.4, 0.1, 1000.0, 2.54):
        err = abs(dxf_width * s - expected_width_mm) / expected_width_mm
        if err <= tolerance:
            return s
    return None


def to_mm(text, scale):
    """Rescale every length in the DXF by `scale` and stamp $INSUNITS = 4.

    Returns (new_text, stats) where stats counts the touched entities. The walk
    is deliberately conservative: values it does not understand pass through
    unchanged, and a parse failure on one number leaves that number as-is.
    """
    lines = text.splitlines()
    out = []
    section = None          # HEADER / ENTITIES / ...
    header_var = None       # current $VARNAME inside HEADER
    entity = None           # current entity type inside ENTITIES/BLOCKS
    saw_insunits = False
    header_end_idx = None   # position of HEADER's ENDSEC "0" line in `out`
    stats = {}

    i = 0
    while i < len(lines):
        code_raw = lines[i]
        if i + 1 >= len(lines):                # trailing unpaired line: pass through
            out.append(code_raw)
            break
        value = lines[i + 1]
        try:
            code = int(code_raw.strip())
        except ValueError:
            out.append(code_raw)
            i += 1
            continue

        if code == 0:
            if value.strip() == 'SECTION':
                section = None
            elif value.strip() == 'ENDSEC':
                if section == 'HEADER':
                    header_end_idx = len(out)
                section = None
                entity = None
            else:
                entity = value.strip()
                stats[entity] = stats.get(entity, 0) + 1
        elif code == 2 and section is None:
            section = value.strip()
        elif code == 9 and section == 'HEADER':
            header_var = value.strip()

        scaled = value
        if section == 'HEADER' and header_var in ('$EXTMIN', '$EXTMAX',
                                                  '$LIMMIN', '$LIMMAX'):
            if code in _COORD_CODES:
                scaled = _scale_number(value, scale)
        elif section == 'HEADER' and header_var == '$INSUNITS' and code == 70:
            scaled = str(INSUNITS_MM)
            saw_insunits = True
        elif section in ('ENTITIES', 'BLOCKS') and entity is not None:
            if code in _COORD_CODES:
                scaled = _scale_number(value, scale)
            elif code in _RADIUS_CODES.get(entity, ()):
                scaled = _scale_number(value, scale)

        out.append(code_raw)
        out.append(scaled)
        i += 2

    if not saw_insunits and header_end_idx is not None:
        out[header_end_idx:header_end_idx] = ['  9', '$INSUNITS', ' 70', '     4']

    stats = {k: v for k, v in stats.items()
             if k in ('LINE', 'ARC', 'CIRCLE', 'LWPOLYLINE', 'POLYLINE', 'SPLINE',
                      'ELLIPSE', 'POINT')}
    return '\n'.join(out) + '\n', stats


def _scale_number(value, scale):
    try:
        return repr(float(value.strip()) * scale)
    except ValueError:
        return value


def extents_width(text):
    """Width (x-extent) of the drawing from all entity x-coordinates (codes 10/11).
    Used for empirical unit inference against the known face width."""
    lines = text.splitlines()
    xs = []
    section = None
    i = 0
    while i + 1 < len(lines):
        try:
            code = int(lines[i].strip())
        except ValueError:
            i += 1
            continue
        value = lines[i + 1].strip()
        if code == 0 and value == 'ENDSEC':
            section = None
        elif code == 2 and section is None and value in ('HEADER', 'ENTITIES',
                                                         'BLOCKS', 'TABLES'):
            section = value
        elif section == 'ENTITIES' and code in (10, 11):
            try:
                xs.append(float(value))
            except ValueError:
                pass
        i += 2
    if len(xs) < 2:
        return 0.0
    return max(xs) - min(xs)
