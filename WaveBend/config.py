"""Defaults and material->gap-multiplier table. Pure; no adsk imports.

Also carries the add-in identity constants the vendored fusionAddInUtils and the
command entry expect (template convention: config.py at the add-in package root).
"""
import os

# -- add-in identity (template convention) --------------------------------------
DEBUG = True                     # write debug logs to the Text Commands palette
ADDIN_NAME = os.path.basename(os.path.dirname(__file__))   # "WaveBend"
COMPANY_NAME = 'AnikaW'

# -- fabrication defaults --------------------------------------------------------
DEFAULT_END_ANGLE_DEG = 40.0
DEFAULT_SLOT_LEN_CM = 1.651   # ~0.65 in: the slot's HORIZONTAL run, constant across gauges (DXF)
DEFAULT_DIAG_LEN_CM = 0.4826  # ~0.19 in: swept diagonal end length, constant across gauges (DXF)

# -- pattern styles ---------------------------------------------------------------
# (geometry style key, dialog label). Keys match geometry.PATTERN_STYLES.
PATTERN_STYLE_LABELS = (
    ('wave', 'Wave (SendCutSend)'),
    ('crescent', 'Crescent arcs'),
    ('serpentine', 'Serpentine'),
    ('meander', 'Square meander'),
    ('zigzag', 'Zigzag'),
    ('dogbone', 'Dogbone slots'),
    ('stagger', 'Staggered slots'),
    ('slot', 'Straight slots'),
    ('diamond', 'Diamond'),
)
DEFAULT_PATTERN_STYLE = 'wave'

# Per-style kerf floors, in material thicknesses (docs/pattern-research.md):
# curved profiles are fracture-safe at any practical kerf, so they use the
# family multiplier as-is; dogbones are safe from 0.7 t (the enlarged end
# holes carry the stress); straight-slot geometries want a full 1.0 t.
STYLE_GAP_FLOOR_X_T = {
    'dogbone': 0.7,
    'stagger': 1.0,
    'slot': 1.0,
    'meander': 1.0,
    'diamond': 1.0,
}

# Hand-bend relief patterns get unreliable above ~3 mm: SendCutSend caps wave
# bending at 0.187 in, and fracture is predicted at 3.2 mm in the 6061-O FEA.
MAX_RELIABLE_THICKNESS_CM = 0.3


def pattern_style_for_label(label):
    for key, lbl in PATTERN_STYLE_LABELS:
        if lbl == label:
            return key
    return DEFAULT_PATTERN_STYLE


def pattern_label_for_style(style):
    for key, lbl in PATTERN_STYLE_LABELS:
        if key == style:
            return lbl
    return PATTERN_STYLE_LABELS[0][1]

# substring (lowercased) -> gap multiplier m
MATERIAL_MULTIPLIERS = {
    "alumin": 0.6,
    "steel": 0.7,
    "stainless": 0.7,
    "titanium": 0.7,
}
_DEFAULT_MULTIPLIER = 0.6

def gap_multiplier_for(material_name):
    name = (material_name or "").lower()
    for key, mult in MATERIAL_MULTIPLIERS.items():
        if key in name:
            return mult
    return _DEFAULT_MULTIPLIER


# Family names double as the dialog's material dropdown items.
FAMILY_ALUMINUM = 'Aluminum'
FAMILY_MILD_STEEL = 'Mild Steel'
FAMILY_STAINLESS = 'Stainless Steel'
FAMILY_TITANIUM = 'Titanium'
MATERIAL_FAMILIES = (FAMILY_ALUMINUM, FAMILY_MILD_STEEL, FAMILY_STAINLESS, FAMILY_TITANIUM)

# Common alloy designations that identify a family even when the name carries no
# family word (e.g. a sheet-metal rule named '.063" 5052').
_ALUMINUM_ALLOYS = ("5052", "6061", "7075", "3003", "2024", "5083")
_STAINLESS_ALLOYS = ("304", "316", "410", "430", "17-4")
_TITANIUM_ALLOYS = ("ti-6al", "grade 5", "6al-4v")


def material_family(name):
    """Map a material or sheet-metal-rule name to a family, or None if unrecognized.

    Order matters: 'stainless' must win over 'steel', and explicit family words win
    over alloy-number hints.
    """
    n = (name or "").lower()
    if not n:
        return None
    if "alumin" in n:
        return FAMILY_ALUMINUM
    if "stainless" in n:
        return FAMILY_STAINLESS
    if "titanium" in n:
        return FAMILY_TITANIUM
    if "steel" in n:
        return FAMILY_MILD_STEEL
    if any(a in n for a in _ALUMINUM_ALLOYS):
        return FAMILY_ALUMINUM
    if any(a in n for a in _TITANIUM_ALLOYS):
        return FAMILY_TITANIUM
    if any(a in n for a in _STAINLESS_ALLOYS):
        return FAMILY_STAINLESS
    return None

def default_gap_cm(t_cm, material_name, style=DEFAULT_PATTERN_STYLE):
    """Kerf default: family multiplier, raised to the style's research floor."""
    gap = t_cm * gap_multiplier_for(material_name)
    floor = STYLE_GAP_FLOOR_X_T.get(style)
    if floor:
        gap = max(gap, t_cm * floor)
    return gap

def default_tab_cm(t_cm):
    return t_cm

def default_fillet_cm(gap_cm):
    # Must stay strictly below gap/2 or the angled cell ends collapse (see geometry.build_cell).
    # 0.3*gap rounds the corners well while keeping the angled ends intact.
    return gap_cm * 0.3
