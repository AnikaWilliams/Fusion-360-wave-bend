"""Defaults and material->gap-multiplier table. Pure; no adsk imports."""

DEFAULT_END_ANGLE_DEG = 40.0
DEFAULT_SLOT_LEN_CM = 1.651   # ~0.65 in, constant SendCutSend cell length (from DXF)

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

def default_gap_cm(t_cm, material_name):
    return t_cm * gap_multiplier_for(material_name)

def default_tab_cm(t_cm):
    return t_cm

def default_fillet_cm(gap_cm):
    # Must stay strictly below gap/2 or the angled cell ends collapse (see geometry.build_cell).
    # 0.3*gap rounds the corners well while keeping the angled ends intact.
    return gap_cm * 0.3
