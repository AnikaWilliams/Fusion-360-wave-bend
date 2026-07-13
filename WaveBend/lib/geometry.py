"""Wave-bend cell + tessellation math. Pure; NO adsk imports.
Unit-agnostic: consistent units in -> consistent units out. Production passes cm."""
import math

class Pt:
    __slots__ = ("x", "y")
    def __init__(self, x, y):
        self.x = float(x); self.y = float(y)
    def __repr__(self):
        return f"Pt({self.x:.4f}, {self.y:.4f})"

def v_add(a, b): return Pt(a.x + b.x, a.y + b.y)
def v_sub(a, b): return Pt(a.x - b.x, a.y - b.y)
def v_mul(a, s): return Pt(a.x * s, a.y * s)
def v_len(a):    return math.hypot(a.x, a.y)
def v_unit(a):
    L = v_len(a)
    return Pt(a.x / L, a.y / L) if L > 1e-12 else Pt(0.0, 0.0)

def sample_segment(seg, n=14):
    if seg[0] == "line":
        _, p0, p1 = seg
        return [Pt(p0.x + (p1.x - p0.x) * i / n, p0.y + (p1.y - p0.y) * i / n)
                for i in range(n + 1)]
    _, c, r, a0, a1, _, _ = seg
    return [Pt(c.x + r * math.cos(a0 + (a1 - a0) * i / n),
               c.y + r * math.sin(a0 + (a1 - a0) * i / n)) for i in range(n + 1)]

def sample_profile(profile, n=14):
    pts = []
    for seg in profile:
        pts.extend(sample_segment(seg, n))
    return pts

def point_seg_distance(p, a, b):
    dx = b.x - a.x; dy = b.y - a.y
    L2 = dx * dx + dy * dy
    if L2 < 1e-18:
        return math.hypot(p.x - a.x, p.y - a.y)
    t = ((p.x - a.x) * dx + (p.y - a.y) * dy) / L2
    t = max(0.0, min(1.0, t))
    return math.hypot(p.x - (a.x + t * dx), p.y - (a.y + t * dy))

def _bbox(pts):
    xs = [p.x for p in pts]; ys = [p.y for p in pts]
    return min(xs), min(ys), max(xs), max(ys)

def _polyline_pair_distance(A, B, stop_below=0.0):
    """Minimum distance between two sampled polylines, checked in BOTH directions:
    A-points->B-segments AND B-points->A-segments. A one-sided check can over-report
    the true minimum when the closest feature is a vertex of one polyline projecting
    onto the interior of a segment of the other.

    stop_below: early exit — once the running minimum drops under this value the
    caller only cares THAT it is under, not by how much (feasibility checks)."""
    best = float("inf")
    for p in A:
        for k in range(len(B) - 1):
            d = point_seg_distance(p, B[k], B[k + 1])
            if d < best:
                best = d
                if best < stop_below:
                    return best
    for p in B:
        for k in range(len(A) - 1):
            d = point_seg_distance(p, A[k], A[k + 1])
            if d < best:
                best = d
                if best < stop_below:
                    return best
    return best

def min_profile_distance(profiles, n=12, stop_below=0.0):
    polys = [sample_profile(p, n) for p in profiles]
    boxes = [_bbox(p) for p in polys]
    best = float("inf")
    for i in range(len(polys)):
        for j in range(i + 1, len(polys)):
            # bbox reject: skip pairs already farther apart than current best
            bi, bj = boxes[i], boxes[j]
            gap_x = max(bi[0] - bj[2], bj[0] - bi[2], 0.0)
            gap_y = max(bi[1] - bj[3], bj[1] - bi[3], 0.0)
            if math.hypot(gap_x, gap_y) >= best:
                continue
            d = _polyline_pair_distance(polys[i], polys[j], stop_below=stop_below)
            if d < best:
                best = d
                if best < stop_below:
                    return best
    return best

def fillet_corner(A, B, C, R):
    """Tangent fillet of radius R at vertex B (edges B->A and B->C).

    Works for convex corners and for concave 'knee' corners of a closed outline --
    the construction (tangent circle on the bisector side) is the same; only the
    arc's curvature relative to the loop differs."""
    v1 = v_unit(v_sub(A, B)); v2 = v_unit(v_sub(C, B))
    cosang = max(-1.0, min(1.0, v1.x * v2.x + v1.y * v2.y))
    phi = math.acos(cosang)                      # interior angle at B
    if phi < 1e-9 or phi > math.pi - 1e-9:
        # collinear vertices: tan(0)->0 (div-by-zero) or a 180 deg "corner" (no fillet).
        raise ValueError("fillet_corner: collinear/degenerate vertices, no fillet possible")
    tan_len = R / math.tan(phi / 2.0)
    T1 = v_add(B, v_mul(v1, tan_len))            # tangent point on edge toward A
    T2 = v_add(B, v_mul(v2, tan_len))            # tangent point on edge toward C
    bis = v_unit(v_add(v1, v2))                  # bisector, points into the corner
    center = v_add(B, v_mul(bis, R / math.sin(phi / 2.0)))
    a0 = math.atan2(T1.y - center.y, T1.x - center.x)
    a1 = math.atan2(T2.y - center.y, T2.x - center.x)
    da = a1 - a0                                 # take the short sweep
    while da <= -math.pi: da += 2 * math.pi
    while da > math.pi:  da -= 2 * math.pi
    return T1, T2, center, a0, a0 + da, tan_len

def _line_intersect(p, d, q, e):
    """Intersection of the infinite lines p + t*d and q + s*e. Raises on parallel."""
    det = d.x * e.y - d.y * e.x
    if abs(det) < 1e-12:
        raise ValueError("parallel lines cannot form a knee corner")
    t = ((q.x - p.x) * e.y - (q.y - p.y) * e.x) / det
    return Pt(p.x + t * d.x, p.y + t * d.y)

def build_wave_cell(slot_len, gap, fillet_r, end_angle_deg=40.0, diag_len=0.4826,
                    orient=+1, cx=0.0, cy=0.0):
    """One wave slot: a constant-width SMILE (orient=+1) or FROWN (orient=-1).

    The cut is a swept path -- diagonal end, horizontal (length slot_len), diagonal
    end, both ends sweeping to the SAME side -- of width `gap`, with SQUARED ends
    whose two corners carry fillets of radius `fillet_r` (the same dialog Fillet
    that rounds the knees: inner knees at `fillet_r`, outer at `fillet_r + gap`).
    The squared end face sits gap/2 past the path endpoint, preserving the pill
    cap's overall extent, so fillet_r must stay below gap/2 for the corners to fit.

    Matches the SendCutSend reference DXF: horizontal ~0.65 in, diagonals ~0.19 in
    at ~40 deg; only the gap scales with material thickness. The horizontal edge of
    the slot sits ON the bend line (cy); the swept ends rise (smile) or fall (frown).
    Returns a closed list of ("line", ...) / ("arc", ...) segments.
    """
    if gap <= 0 or slot_len <= 0 or diag_len <= 0:
        raise ValueError("gap, slot_len and diag_len must all be positive")
    if fillet_r <= 0:
        raise ValueError("fillet_r must be > 0 (sharp internal corners crack when bent)")
    if fillet_r > gap / 2.0 - 1e-9:
        raise ValueError("fillet_r too large for the squared slot ends "
                         "(needs < gap/2 so both end corners fit)")
    th = math.radians(end_angle_deg)
    if not (math.radians(5.0) < th < math.radians(85.0)):
        raise ValueError("end_angle_deg out of range (5..85)")
    g2 = gap / 2.0
    h2 = slot_len / 2.0
    # Path vertices for a smile (ends up), before orient/translate:
    B = Pt(-h2, 0.0); C = Pt(+h2, 0.0)
    d1 = Pt(math.cos(th), -math.sin(th))     # direction A -> B (down-right)
    d2 = Pt(1.0, 0.0)                        # direction B -> C
    d3 = Pt(math.cos(th), +math.sin(th))     # direction C -> D (up-right)
    A = Pt(B.x - diag_len * d1.x, B.y - diag_len * d1.y)   # raised left end
    D = Pt(C.x + diag_len * d3.x, C.y + diag_len * d3.y)   # raised right end
    n1 = Pt(math.sin(th), math.cos(th))      # left normal of d1
    n3 = Pt(-math.sin(th), math.cos(th))     # left normal of d3
    # Boundary anchors: ends offset +-gap/2 across the path; knees by line intersection.
    Au = Pt(A.x + n1.x * g2, A.y + n1.y * g2); La = Pt(A.x - n1.x * g2, A.y - n1.y * g2)
    Du = Pt(D.x + n3.x * g2, D.y + n3.y * g2); Da = Pt(D.x - n3.x * g2, D.y - n3.y * g2)
    Bu = _line_intersect(Au, d1, Pt(B.x, B.y + g2), d2)
    Bl = _line_intersect(La, d1, Pt(B.x, B.y - g2), d2)
    Cu = _line_intersect(Du, d3, Pt(C.x, C.y + g2), d2)
    Cl = _line_intersect(Da, d3, Pt(C.x, C.y - g2), d2)
    r_in, r_out = fillet_r, fillet_r + gap
    fBl = fillet_corner(La, Bl, Cl, r_out)   # outer knees (below the path on a smile)
    fCl = fillet_corner(Bl, Cl, Da, r_out)
    fCu = fillet_corner(Du, Cu, Bu, r_in)    # inner knees
    fBu = fillet_corner(Cu, Bu, Au, r_in)
    # Feasibility: tangent points must stay on their edges.
    def _d(p, q): return math.hypot(q.x - p.x, q.y - p.y)
    if fBl[5] + fCl[5] > _d(Bl, Cl) - 1e-9 or fBu[5] + fCu[5] > _d(Bu, Cu) - 1e-9:
        raise ValueError("fillet_r too large for slot_len (knee fillets overlap)")
    if (fBl[5] > _d(Bl, La) - 1e-9 or fBu[5] > _d(Bu, Au) - 1e-9 or
            fCl[5] > _d(Cl, Da) - 1e-9 or fCu[5] > _d(Cu, Du) - 1e-9):
        raise ValueError("fillet_r or gap too large for diag_len (no room on the diagonal)")

    # Squared ends: the end face sits gap/2 beyond the path endpoint, its two
    # corners filleted with the SAME fillet_r as the knees. Right end corners
    # extend along +d3, left end corners along -d1 (outward at each end).
    CLr = Pt(Da.x + d3.x * g2, Da.y + d3.y * g2)   # right end, lower corner
    CUr = Pt(Du.x + d3.x * g2, Du.y + d3.y * g2)   # right end, upper corner
    CUl = Pt(Au.x - d1.x * g2, Au.y - d1.y * g2)   # left end, upper corner
    CLl = Pt(La.x - d1.x * g2, La.y - d1.y * g2)   # left end, lower corner
    flr = fillet_corner(Da, CLr, CUr, fillet_r)    # right lower corner
    fur = fillet_corner(CLr, CUr, Du, fillet_r)    # right upper corner
    ful = fillet_corner(Au, CUl, CLl, fillet_r)    # left upper corner
    fll = fillet_corner(CUl, CLl, La, fillet_r)    # left lower corner

    segs = [("line", La, fBl[0]),
            ("arc", fBl[2], r_out, fBl[3], fBl[4], fBl[0], fBl[1]),
            ("line", fBl[1], fCl[0]),
            ("arc", fCl[2], r_out, fCl[3], fCl[4], fCl[0], fCl[1]),
            ("line", fCl[1], flr[0]),
            ("arc", flr[2], fillet_r, flr[3], flr[4], flr[0], flr[1]),
            ("line", flr[1], fur[0]),
            ("arc", fur[2], fillet_r, fur[3], fur[4], fur[0], fur[1]),
            ("line", fur[1], fCu[0]),
            ("arc", fCu[2], r_in, fCu[3], fCu[4], fCu[0], fCu[1]),
            ("line", fCu[1], fBu[0]),
            ("arc", fBu[2], r_in, fBu[3], fBu[4], fBu[0], fBu[1]),
            ("line", fBu[1], ful[0]),
            ("arc", ful[2], fillet_r, ful[3], ful[4], ful[0], ful[1]),
            ("line", ful[1], fll[0]),
            ("arc", fll[2], fillet_r, fll[3], fll[4], fll[0], fll[1]),
            ("line", fll[1], La)]
    # Orient (mirror v for a frown) and translate to (cx, cy).
    s = 1.0 if orient >= 0 else -1.0
    out = []
    for seg in segs:
        if seg[0] == "line":
            _, p0, p1 = seg
            out.append(("line", Pt(cx + p0.x, cy + s * p0.y), Pt(cx + p1.x, cy + s * p1.y)))
        else:
            _, c, r, a0, a1, p0, p1 = seg
            out.append(("arc", Pt(cx + c.x, cy + s * c.y), r,
                        a0 if s > 0 else -a0, a1 if s > 0 else -a1,
                        Pt(cx + p0.x, cy + s * p0.y), Pt(cx + p1.x, cy + s * p1.y)))
    return out


# ---------------------------------------------------------------------------
# Alternative cell shapes (same closed line/arc segment format as the wave)
# ---------------------------------------------------------------------------

STYLE_WAVE = 'wave'
STYLE_SLOT = 'slot'
STYLE_ZIGZAG = 'zigzag'
STYLE_DIAMOND = 'diamond'
STYLE_SERPENTINE = 'serpentine'
STYLE_CRESCENT = 'crescent'
STYLE_DOGBONE = 'dogbone'
STYLE_STAGGER = 'stagger'
STYLE_MEANDER = 'meander'
PATTERN_STYLES = (STYLE_WAVE, STYLE_SLOT, STYLE_ZIGZAG, STYLE_DIAMOND,
                  STYLE_SERPENTINE, STYLE_CRESCENT, STYLE_DOGBONE,
                  STYLE_STAGGER, STYLE_MEANDER)

# Styles whose consecutive cells flip orientation (up/down) along the chain.
# 'stagger' flips ROWS: the pill jumps to the other side of the bend line, which
# is exactly the staggered double-row living hinge.
_ALTERNATING = {STYLE_WAVE: True, STYLE_SLOT: False, STYLE_ZIGZAG: True,
                STYLE_DIAMOND: False, STYLE_SERPENTINE: True,
                STYLE_CRESCENT: True, STYLE_DOGBONE: False,
                STYLE_STAGGER: True, STYLE_MEANDER: True}

# Research-backed shape constants (docs/pattern-research.md):
CRESCENT_SAGITTA_RATIO = 0.2     # arc depth / chord — shallow arc, large radius
DOGBONE_HOLE_RADIUS_X_GAP = 1.25  # end-hole radius = 1.25 x kerf (dia 2.5 x kerf)
STAGGER_JOG_X_GAP = 0.5          # row offset from the bend line, in gaps
MEANDER_AMPLITUDE_RATIO = 0.3    # meander half-height / slot_len


def style_alternates(style):
    return _ALTERNATING[style]


def build_slot_cell(slot_len, gap, cx=0.0, cy=0.0):
    """Straight slot (pill/stadium): total length slot_len, width gap, semicircular
    end caps. Symmetric about the bend line; fillet_r is not needed (the caps ARE
    the corner relief)."""
    if gap <= 0 or slot_len <= 0:
        raise ValueError("gap and slot_len must be positive")
    if slot_len <= 1.5 * gap:
        raise ValueError("slot_len too short for a straight slot (needs > 1.5 x gap)")
    g2 = gap / 2.0
    h = slot_len / 2.0 - g2                       # straight-run half-length
    L0, L1 = Pt(cx - h, cy - g2), Pt(cx + h, cy - g2)
    U1, U0 = Pt(cx + h, cy + g2), Pt(cx - h, cy + g2)
    return [
        ("line", L0, L1),
        ("arc", Pt(cx + h, cy), g2, -math.pi / 2.0, math.pi / 2.0, L1, U1),
        ("line", U1, U0),
        ("arc", Pt(cx - h, cy), g2, math.pi / 2.0, 3.0 * math.pi / 2.0, U0, L0),
    ]


def build_zigzag_cell(slot_len, gap, fillet_r, end_angle_deg=40.0,
                      orient=+1, cx=0.0, cy=0.0):
    """Chevron: a constant-width V (orient=+1) or caret (orient=-1) whose apex sits
    ON the bend line. Two diagonal arms at end_angle_deg from the line, width gap,
    semicircular caps at the free ends, apex knee fillets (inner fillet_r, outer
    fillet_r + gap: constant width preserved)."""
    if gap <= 0 or slot_len <= 0:
        raise ValueError("gap and slot_len must be positive")
    if fillet_r <= 0:
        raise ValueError("fillet_r must be > 0 (sharp internal corners crack when bent)")
    th = math.radians(end_angle_deg)
    if not (math.radians(5.0) < th < math.radians(85.0)):
        raise ValueError("end_angle_deg out of range (5..85)")
    g2 = gap / 2.0
    h2 = slot_len / 2.0
    rise = h2 * math.tan(th)
    A, B, C = Pt(-h2, rise), Pt(0.0, 0.0), Pt(h2, rise)   # V apex down at the line
    d1 = Pt(math.cos(th), -math.sin(th))          # A -> B
    d2 = Pt(math.cos(th), +math.sin(th))          # B -> C
    n1 = Pt(math.sin(th), math.cos(th))           # left normal of d1 (upper side)
    n2 = Pt(-math.sin(th), math.cos(th))          # left normal of d2 (upper side)
    Au, Al = v_add(A, v_mul(n1, g2)), v_sub(A, v_mul(n1, g2))
    Cu, Cl = v_add(C, v_mul(n2, g2)), v_sub(C, v_mul(n2, g2))
    Bu = _line_intersect(Au, d1, Cu, d2)          # upper (inner) knee
    Bl = _line_intersect(Al, d1, Cl, d2)          # lower (outer) knee
    r_in, r_out = fillet_r, fillet_r + gap
    fBu = fillet_corner(Cu, Bu, Au, r_in)         # traversed right-to-left on top
    fBl = fillet_corner(Al, Bl, Cl, r_out)        # traversed left-to-right below
    def _d(p, q): return math.hypot(q.x - p.x, q.y - p.y)
    if (fBl[5] > _d(Bl, Al) - 1e-9 or fBl[5] > _d(Bl, Cl) - 1e-9 or
            fBu[5] > _d(Bu, Au) - 1e-9 or fBu[5] > _d(Bu, Cu) - 1e-9):
        raise ValueError("fillet_r or gap too large for the zigzag arms "
                         "(increase slot length or reduce the fillet)")
    # End caps bulge outward along the arm direction (away from the slit body).
    capC_a0 = th - math.pi / 2.0                  # angle of (Cl - C)
    capA_a0 = math.pi / 2.0 - th                  # angle of (Au - A)
    segs = [
        ("line", Al, fBl[0]),
        ("arc", fBl[2], r_out, fBl[3], fBl[4], fBl[0], fBl[1]),
        ("line", fBl[1], Cl),
        ("arc", C, g2, capC_a0, capC_a0 + math.pi, Cl, Cu),
        ("line", Cu, fBu[0]),
        ("arc", fBu[2], r_in, fBu[3], fBu[4], fBu[0], fBu[1]),
        ("line", fBu[1], Au),
        ("arc", A, g2, capA_a0, capA_a0 + math.pi, Au, Al),
    ]
    return _orient_translate(segs, orient, cx, cy)


def build_diamond_cell(slot_len, gap, fillet_r, cx=0.0, cy=0.0):
    """Diamond opening centered on the bend line: width slot_len along the line,
    total height 2 x gap across it (gap keeps its 'cut size' meaning), all four
    corners filleted with fillet_r. Chained with solid tab ligaments tip-to-tip
    it forms the classic diamond-lattice relief row."""
    if gap <= 0 or slot_len <= 0:
        raise ValueError("gap and slot_len must be positive")
    if fillet_r <= 0:
        raise ValueError("fillet_r must be > 0 (sharp internal corners crack when bent)")
    if slot_len <= 2.0 * gap:
        raise ValueError("slot_len too short for a diamond (needs > 2 x gap)")
    w2, h2 = slot_len / 2.0, gap
    L, T, R, Bo = Pt(-w2, 0.0), Pt(0.0, h2), Pt(w2, 0.0), Pt(0.0, -h2)
    corners = [(Bo, L, T), (L, T, R), (T, R, Bo), (R, Bo, L)]  # CCW: L, T, R, Bo
    fs = []
    for prev, at, nxt in corners:
        f = fillet_corner(prev, at, nxt, fillet_r)
        fs.append(f)
    # Feasibility: adjacent tangent lengths must fit on the shared edge.
    edge = math.hypot(w2, h2)
    for i in range(4):
        if fs[i][5] + fs[(i + 1) % 4][5] > edge - 1e-9:
            raise ValueError("fillet_r too large for the diamond tips "
                             "(reduce fillet or lengthen slots)")
    segs = []
    for i in range(4):
        f, fn = fs[i], fs[(i + 1) % 4]
        segs.append(("arc", f[2], fillet_r, f[3], f[4], f[0], f[1]))
        segs.append(("line", f[1], fn[0]))
    return _orient_translate(segs, +1, cx, cy)


def build_serpentine_cell(slot_len, gap, orient=+1, cx=0.0, cy=0.0):
    """Serpentine: an S-shaped slit (orient=-1 mirrors it) of width gap whose spine
    is two tangent semicircles of radius slot_len/4 -- the deepest-flexing pattern.
    All-arc boundary (concentric offsets + semicircular caps); fillet_r is not
    needed (everything is tangent-continuous)."""
    if gap <= 0 or slot_len <= 0:
        raise ValueError("gap and slot_len must be positive")
    R = slot_len / 4.0
    g2 = gap / 2.0
    if R - g2 < 0.05 * gap:
        raise ValueError("slot_len too short for a serpentine (needs > ~2.2 x gap)")
    C1, C2 = Pt(-R, 0.0), Pt(R, 0.0)
    P0, P3 = Pt(-2.0 * R, 0.0), Pt(2.0 * R, 0.0)
    r_o, r_i = R + g2, R - g2
    pi = math.pi
    segs = [
        # upper-outer sweep of the left lobe: (-2R-g2,0) -> (g2,0) over the top
        ("arc", C1, r_o, pi, 0.0, Pt(-2.0 * R - g2, 0.0), Pt(g2, 0.0)),
        # lower-inner sweep of the right lobe: (g2,0) -> (2R-g2,0) under the bottom
        ("arc", C2, r_i, pi, 2.0 * pi, Pt(g2, 0.0), Pt(2.0 * R - g2, 0.0)),
        # right cap bulges up-right, away from the lower lobe
        ("arc", P3, g2, pi, 0.0, Pt(2.0 * R - g2, 0.0), Pt(2.0 * R + g2, 0.0)),
        # lower-outer sweep of the right lobe, traced back right-to-left
        ("arc", C2, r_o, 0.0, -pi, Pt(2.0 * R + g2, 0.0), Pt(-g2, 0.0)),
        # upper-inner sweep of the left lobe, traced back over the top
        ("arc", C1, r_i, 0.0, pi, Pt(-g2, 0.0), Pt(-2.0 * R + g2, 0.0)),
        # left cap bulges down-left, closing the loop
        ("arc", P0, g2, 0.0, -pi, Pt(-2.0 * R + g2, 0.0), Pt(-2.0 * R - g2, 0.0)),
    ]
    return _orient_translate(segs, orient, cx, cy)


def build_crescent_cell(slot_len, gap, orient=+1, cx=0.0, cy=0.0):
    """Crescent: one shallow arc slit of width gap (US 7,032,426: arcuate slits,
    convex side toward the bend line, enlarged-radius profile resists cracking).
    Chord = slot_len, sagitta = CRESCENT_SAGITTA_RATIO x chord; the cell is
    vertically centered on the bend line and alternates bulge direction."""
    if gap <= 0 or slot_len <= 0:
        raise ValueError("gap and slot_len must be positive")
    s = CRESCENT_SAGITTA_RATIO * slot_len
    c2 = slot_len / 2.0
    R = (c2 * c2 + s * s) / (2.0 * s)             # circumradius of the spine arc
    g2 = gap / 2.0
    if R - g2 <= 0.05 * gap:
        raise ValueError("slot_len too short for a crescent (needs > ~0.8 x gap)")
    # Spine: midpoint at (0, -s/2), endpoints at (+-c2, +s/2); center above.
    Cn = Pt(0.0, R - s / 2.0)
    alpha = math.asin(min(1.0, c2 / R))
    a_mid = -math.pi / 2.0                        # bottom of the circle
    a_l, a_r = a_mid - alpha, a_mid + alpha
    r_o, r_i = R + g2, R - g2                     # outer (lower) / inner boundaries
    EL = Pt(Cn.x + R * math.cos(a_l), Cn.y + R * math.sin(a_l))   # left spine end
    ER = Pt(Cn.x + R * math.cos(a_r), Cn.y + R * math.sin(a_r))   # right spine end
    def on(rr, ang):
        return Pt(Cn.x + rr * math.cos(ang), Cn.y + rr * math.sin(ang))
    # End caps bulge outward along the spine tangents (midpoint away from the slit).
    segs = [
        ("arc", Cn, r_o, a_l, a_r, on(r_o, a_l), on(r_o, a_r)),
        ("arc", ER, g2, a_r, a_r + math.pi, on(r_o, a_r), on(r_i, a_r)),
        ("arc", Cn, r_i, a_r, a_l, on(r_i, a_r), on(r_i, a_l)),
        ("arc", EL, g2, a_l + math.pi, a_l + 2.0 * math.pi,
         on(r_i, a_l), on(r_o, a_l)),
    ]
    return _orient_translate(segs, orient, cx, cy)


def build_dogbone_cell(slot_len, gap, cx=0.0, cy=0.0):
    """Dogbone: a straight slot of width gap with enlarged round end holes
    (radius DOGBONE_HOLE_RADIUS_X_GAP x gap). The enlarged openings cut peak
    bend-line stress ~22% vs a plain slot (FEA, docs/pattern-research.md) and
    resist micro-crack propagation (US 7,032,426). Symmetric about the line."""
    if gap <= 0 or slot_len <= 0:
        raise ValueError("gap and slot_len must be positive")
    g2 = gap / 2.0
    rh = DOGBONE_HOLE_RADIUS_X_GAP * gap
    h = slot_len / 2.0 - rh                       # end-hole centers at +-h
    q = math.sqrt(max(rh * rh - g2 * g2, 0.0))    # slot-edge / hole junction offset
    if h <= q + 1e-9:
        raise ValueError("slot_len too short for dogbone end holes "
                         "(needs > ~4.8 x gap)")
    beta = math.atan2(g2, q)
    CL, CR = Pt(cx - h, cy), Pt(cx + h, cy)
    jRB = Pt(cx + h - q, cy - g2)                 # right hole, bottom junction
    jRT = Pt(cx + h - q, cy + g2)
    jLB = Pt(cx - h + q, cy - g2)
    jLT = Pt(cx - h + q, cy + g2)
    return [
        ("line", jLB, jRB),
        ("arc", CR, rh, -math.pi + beta, math.pi - beta, jRB, jRT),
        ("line", jRT, jLT),
        ("arc", CL, rh, beta, 2.0 * math.pi - beta, jLT, jLB),
    ]


def build_stagger_cell(slot_len, gap, orient=+1, cx=0.0, cy=0.0):
    """Staggered-row slot: a plain pill offset off the bend line by
    STAGGER_JOG_X_GAP x gap; consecutive cells flip rows, forming the classic
    two-row living hinge. The jog stays within the patent's preferred
    <= 0.5 x thickness once gap is sized to ~1 x thickness (US 7,032,426)."""
    jog = STAGGER_JOG_X_GAP * gap
    return build_slot_cell(slot_len, gap, cx=cx, cy=cy + orient * jog)


def build_meander_cell(slot_len, gap, fillet_r, orient=+1, cx=0.0, cy=0.0):
    """Square meander: a constant-width squared-off arch (orient=+1 opens down,
    -1 opens up) — the rectangular serpentine. Vertical ends, one horizontal
    run, all four knees filleted (inner fillet_r, outer fillet_r + gap): the
    FEA identifies small corner radii as THE fracture driver, so the fillets
    are structural here, not cosmetic."""
    if gap <= 0 or slot_len <= 0:
        raise ValueError("gap and slot_len must be positive")
    if fillet_r <= 0:
        raise ValueError("fillet_r must be > 0 (sharp internal corners crack when bent)")
    g2 = gap / 2.0
    h2 = slot_len / 2.0
    a = MEANDER_AMPLITUDE_RATIO * slot_len
    r_in, r_out = fillet_r, fillet_r + gap
    if 2.0 * r_out >= slot_len - 2.0 * g2 - 1e-9:
        raise ValueError("fillet_r or gap too large for the meander top run")
    if a <= r_out + g2 + 1e-9:
        raise ValueError("slot_len too short for meander arms (needs > ~5 x gap)")
    # Arch path: A(-h2,-a) up to B(-h2,+a), across to C(+h2,+a), down to D(+h2,-a).
    Ao, Ai = Pt(-h2 - g2, -a), Pt(-h2 + g2, -a)   # outer / inner cap anchors, left
    Do, Di = Pt(h2 + g2, -a), Pt(h2 - g2, -a)
    Bo, Co = Pt(-h2 - g2, a + g2), Pt(h2 + g2, a + g2)   # outer knees
    Bi, Ci = Pt(-h2 + g2, a - g2), Pt(h2 - g2, a - g2)   # inner knees
    fBo = fillet_corner(Ao, Bo, Co, r_out)
    fCo = fillet_corner(Bo, Co, Do, r_out)
    fCi = fillet_corner(Di, Ci, Bi, r_in)
    fBi = fillet_corner(Ci, Bi, Ai, r_in)
    segs = [
        ("line", Ao, fBo[0]),
        ("arc", fBo[2], r_out, fBo[3], fBo[4], fBo[0], fBo[1]),
        ("line", fBo[1], fCo[0]),
        ("arc", fCo[2], r_out, fCo[3], fCo[4], fCo[0], fCo[1]),
        ("line", fCo[1], Do),
        ("arc", Pt(h2, -a), g2, 0.0, -math.pi, Do, Di),
        ("line", Di, fCi[0]),
        ("arc", fCi[2], r_in, fCi[3], fCi[4], fCi[0], fCi[1]),
        ("line", fCi[1], fBi[0]),
        ("arc", fBi[2], r_in, fBi[3], fBi[4], fBi[0], fBi[1]),
        ("line", fBi[1], Ai),
        ("arc", Pt(-h2, -a), g2, 0.0, -math.pi, Ai, Ao),
    ]
    return _orient_translate(segs, orient, cx, cy)


def _orient_translate(segs, orient, cx, cy):
    """Mirror in v (orient=-1) then translate -- the same transform the wave applies."""
    s = 1.0 if orient >= 0 else -1.0
    out = []
    for seg in segs:
        if seg[0] == "line":
            _, p0, p1 = seg
            out.append(("line", Pt(cx + p0.x, cy + s * p0.y), Pt(cx + p1.x, cy + s * p1.y)))
        else:
            _, c, r, a0, a1, p0, p1 = seg
            out.append(("arc", Pt(cx + c.x, cy + s * c.y), r,
                        a0 if s > 0 else -a0, a1 if s > 0 else -a1,
                        Pt(cx + p0.x, cy + s * p0.y), Pt(cx + p1.x, cy + s * p1.y)))
    return out


def build_cell(style, slot_len, gap, fillet_r, end_angle_deg=40.0, diag_len=0.4826,
               orient=+1, cx=0.0, cy=0.0):
    """Style-dispatching cell builder: one closed line/arc loop, any pattern style."""
    if style == STYLE_WAVE:
        return build_wave_cell(slot_len, gap, fillet_r, end_angle_deg, diag_len,
                               orient=orient, cx=cx, cy=cy)
    if style == STYLE_SLOT:
        return build_slot_cell(slot_len, gap, cx=cx, cy=cy)
    if style == STYLE_ZIGZAG:
        return build_zigzag_cell(slot_len, gap, fillet_r, end_angle_deg,
                                 orient=orient, cx=cx, cy=cy)
    if style == STYLE_DIAMOND:
        return build_diamond_cell(slot_len, gap, fillet_r, cx=cx, cy=cy)
    if style == STYLE_SERPENTINE:
        return build_serpentine_cell(slot_len, gap, orient=orient, cx=cx, cy=cy)
    if style == STYLE_CRESCENT:
        return build_crescent_cell(slot_len, gap, orient=orient, cx=cx, cy=cy)
    if style == STYLE_DOGBONE:
        return build_dogbone_cell(slot_len, gap, cx=cx, cy=cy)
    if style == STYLE_STAGGER:
        return build_stagger_cell(slot_len, gap, orient=orient, cx=cx, cy=cy)
    if style == STYLE_MEANDER:
        return build_meander_cell(slot_len, gap, fillet_r, orient=orient, cx=cx, cy=cy)
    raise ValueError(f"unknown pattern style: {style!r}")


def cell_halfwidth(style, slot_len, gap, fillet_r, end_angle_deg=40.0,
                   diag_len=0.4826):
    """Half the cell's horizontal extent (probe-based; style-agnostic)."""
    probe = sample_profile(build_cell(style, slot_len, gap, fillet_r,
                                      end_angle_deg, diag_len), n=4)
    return (max(p.x for p in probe) - min(p.x for p in probe)) / 2.0


def min_slot_len(style, gap, fillet_r):
    """Smallest slot_len that yields a BUILDABLE cell for `style`, plus a small
    margin. Each floor mirrors the feasibility check in that style's builder, so
    the dialog can auto-lengthen the slot instead of erroring. Fillet-limited
    styles (wave, zigzag, diamond) fall through to the generic 4 x fillet floor."""
    base = max(4.0 * fillet_r, 0.2)
    if style in (STYLE_SLOT, STYLE_STAGGER):
        return max(base, 1.55 * gap)             # build_slot_cell: slot > 1.5 x gap
    if style == STYLE_DIAMOND:
        return max(base, 2.05 * gap)             # build_diamond_cell: slot > 2 x gap
    if style == STYLE_SERPENTINE:
        return max(base, 2.25 * gap)             # R - g2 >= ~0.05 x gap
    if style == STYLE_CRESCENT:
        return max(base, 0.85 * gap)             # R - g2 > ~0.05 x gap
    if style == STYLE_DOGBONE:
        rh = DOGBONE_HOLE_RADIUS_X_GAP * gap
        q = math.sqrt(max(rh * rh - (gap / 2.0) ** 2, 0.0))
        return max(base, 2.0 * (rh + q) * 1.02)  # h > q: slot > 2(rh+q)
    if style == STYLE_MEANDER:
        r_out = fillet_r + gap
        floor_arms = (r_out + gap / 2.0) / MEANDER_AMPLITUDE_RATIO  # a > r_out+g2
        floor_top = 2.0 * r_out + gap                                # top run fits
        return max(base, floor_arms, floor_top) * 1.02
    return base


# ---------------------------------------------------------------------------
# Tessellation: a single cell chain along the bend line
# ---------------------------------------------------------------------------

# Solver probe sampling (chords per segment). Styles with large-radius or
# large-sweep arcs need finer chords to keep the sampling-error margin (and
# thus the safety padding added to the solved pitch) small.
_PROBE_N = {STYLE_SERPENTINE: 10, STYLE_CRESCENT: 10, STYLE_DOGBONE: 10}
_FINAL_N = 12                     # generate_pattern's reporting density


def _probe_n(style):
    return _PROBE_N.get(style, 6)


def _sampling_margin(cell, n_probe, n_final=_FINAL_N):
    """Upper bound on how much chord-sampling can misreport an arc-to-arc
    distance, combined for the probe and the final measurement densities.
    A chord deviates from its arc by at most the sagitta r*(1-cos(sweep/2n));
    two facing arcs can each contribute one sagitta, at either density."""
    m = 0.0
    for seg in cell:
        if seg[0] == "arc":
            _, _c, r, a0, a1, _p0, _p1 = seg
            sweep = abs(a1 - a0)
            sag = lambda n: r * (1.0 - math.cos(sweep / (2.0 * n)))
            m = max(m, 2.0 * sag(n_probe) + 2.0 * sag(n_final))
    return m


def _min_ligament_for_pitch(pitch, slot_len, gap, tab, fillet_r, th, diag_len,
                            style=STYLE_WAVE, stop_below=0.0):
    """Three consecutive slots at this per-slot pitch; tightest gap between any two.

    Three cells cover every neighbour class of the periodic chain: both junction
    types for alternating styles ((0,1) up-down and (1,2) down-up) and the
    same-orientation second-neighbour pair (0,2) — our alternating cells are
    exact mirrors, so the mirrored second-neighbour pair has the same distance
    by symmetry. Straight-edge ligaments are exact at any sampling density;
    arc-to-arc ligaments carry a bounded chord error that solve_pitch covers
    with _sampling_margin.
    """
    alt = style_alternates(style)
    cells = [build_cell(style, slot_len, gap, fillet_r, th, diag_len,
                        orient=+1 if (not alt or i % 2 == 0) else -1,
                        cx=i * pitch, cy=0.0)
             for i in range(3)]
    return min_profile_distance(cells, n=_probe_n(style), stop_below=stop_below)


def solve_pitch(slot_len, gap, tab, fillet_r, end_angle_deg=40.0, samples=48,
                diag_len=0.4826, style=STYLE_WAVE):
    """Smallest per-slot pitch whose every ligament is >= tab (densest valid chain).

    Feasibility is monotone in pitch (spreading slots apart only widens every
    ligament), so the search brackets the feasibility boundary by doubling and
    then bisects it — ~15 ligament evaluations instead of the 48-per-window
    linear scan this replaces, and each evaluation aborts as soon as any
    ligament drops under `tab`. `samples` is kept for signature compatibility.
    Raises ValueError only past a hard cap (degenerate cell geometry).
    """
    th = end_angle_deg
    sin_th = math.sin(math.radians(th))
    # Degenerate cell inputs (bad fillet/gap/slot) must surface immediately —
    # the cell does not depend on pitch, so one probe build validates them all.
    probe_cell = build_cell(style, slot_len, gap, fillet_r, th, diag_len)
    # Solve against tab PLUS the chord-sampling error bound, so the finely
    # sampled ligament generate_pattern reports still clears tab.
    threshold = tab + _sampling_margin(probe_cell, _probe_n(style))

    def feasible(p):
        return _min_ligament_for_pitch(p, slot_len, gap, tab, fillet_r, th,
                                       diag_len, style=style,
                                       stop_below=threshold) >= threshold - 1e-6

    if style_alternates(style) and style != STYLE_SERPENTINE:
        # Below roughly (tab+gap)/sin(th) the diagonal ligament cannot reach `tab`.
        lo = 0.7 * (tab + gap) / sin_th
    else:
        # Non-interleaving cells sit side by side: pitch >= cell width + tab.
        lo = max(0.5 * slot_len, tab)
    hi = max(2.0 * slot_len, (tab + gap) / sin_th * 2.0, lo * 1.5)
    cap = 64.0 * (slot_len + tab + gap)  # backstop against an unbounded loop
    while not feasible(hi):
        if hi >= cap:
            raise ValueError(
                "no feasible pitch found below cap (degenerate cell geometry?)")
        lo, hi = hi, min(hi * 2.0, cap)
    if feasible(lo):
        return lo
    for _ in range(60):                  # bisect the boundary; hi stays feasible
        if hi - lo <= 1e-4:
            break
        mid = (lo + hi) / 2.0
        if feasible(mid):
            hi = mid
        else:
            lo = mid
    return hi


def fit_count(bend_len, pitch, margin):
    usable = bend_len - 2.0 * margin
    if usable <= 0:
        return 0
    return max(1, int(usable // pitch) + 1)


def fit_slot_len(bend_len, count, gap, tab, fillet_r, end_angle_deg, margin,
                 diag_len=0.4826, style=STYLE_WAVE):
    """Invert fit_count: pick the slot_len whose solved pitch yields ~`count` cells.

    Raises ValueError when `count` cannot fit in `bend_len` -- i.e. the requested count
    needs a pitch below the smallest achievable one (asking for more slots than the
    geometry can pack into the bend), or the implied slot is too short to form a cell.
    """
    usable = max(bend_len - 2.0 * margin, 1e-6)
    target_pitch = usable / max(count, 1)
    # binary search slot_len so solve_pitch(slot_len) ~= target_pitch (pitch grows with slot_len)
    lo, hi = 4.0 * fillet_r + 1e-3, 4.0 * bend_len
    for _ in range(40):
        mid = (lo + hi) / 2.0
        try:
            p = solve_pitch(mid, gap, tab, fillet_r, end_angle_deg, diag_len=diag_len,
                            style=style)
        except ValueError:
            lo = mid; continue
        if p < target_pitch:
            lo = mid
        else:
            hi = mid
    result = (lo + hi) / 2.0
    # Verify the requested count actually fits at the resulting slot length.
    try:
        p = solve_pitch(result, gap, tab, fillet_r, end_angle_deg, diag_len=diag_len,
                        style=style)
    except ValueError:
        raise ValueError(f"cannot fit {count} slots in bend_len={bend_len:.4f} "
                         f"(implied slot too short to form a cell)")
    achievable = fit_count(bend_len, p, margin)
    if achievable < count:
        raise ValueError(f"cannot fit {count} slots in bend_len={bend_len:.4f} "
                         f"(smallest pitch {p:.4f} fits at most {achievable})")
    return result


def generate_pattern(bend_len, gap, tab, slot_len, fillet_r, end_angle_deg=40.0,
                     diag_len=0.4826, style=STYLE_WAVE):
    """A single cell chain along the bend line (any pattern style).

    Alternating styles (wave, zigzag, serpentine) flip orientation slot to slot;
    symmetric styles (straight slot, diamond) repeat unchanged. Every cell is
    centered on the user's selected line by construction, and the per-slot pitch
    is solved so NO ligament is narrower than `tab`.

    Returns dict with keys:
      - profiles: list of closed cell outlines, left to right
      - count: total slots in the chain
      - pitch: solved per-slot x-advance
      - row_offset: 0.0 (kept for API stability; single-chain layout has no rows)
      - central_tab: the tab target the pitch was solved for (== tab)
      - min_ligament: narrowest measured gap between any two placed slots
      - style: the pattern style the profiles were built with
    """
    th = end_angle_deg
    pitch = solve_pitch(slot_len, gap, tab, fillet_r, th, diag_len=diag_len,
                        style=style)
    # Solid end margins: the end slots must sit fully inside the bend span.
    half_w = cell_halfwidth(style, slot_len, gap, fillet_r, th, diag_len)
    margin = half_w + gap
    count = fit_count(bend_len, pitch, margin)
    if count == 0:
        raise ValueError(
            f"no slots fit: bend_len={bend_len:.4f} too short for slot width "
            f"{2 * half_w:.4f} plus margins; use a longer bend line or shorter slots")
    span = (count - 1) * pitch
    start = (bend_len - span) / 2.0                   # center the chain
    alt = style_alternates(style)
    profiles = [build_cell(style, slot_len, gap, fillet_r, th, diag_len,
                           orient=+1 if (not alt or i % 2 == 0) else -1,
                           cx=start + i * pitch, cy=0.0)
                for i in range(count)]
    return {
        "profiles": profiles,
        "count": count,
        "pitch": pitch,
        "row_offset": 0.0,
        "central_tab": tab,
        "min_ligament": min_profile_distance(profiles) if count > 1 else float("inf"),
        "style": style,
    }
