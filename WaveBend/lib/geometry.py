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

def _polyline_pair_distance(A, B):
    """Minimum distance between two sampled polylines, checked in BOTH directions:
    A-points->B-segments AND B-points->A-segments. A one-sided check can over-report
    the true minimum when the closest feature is a vertex of one polyline projecting
    onto the interior of a segment of the other."""
    best = float("inf")
    for p in A:
        for k in range(len(B) - 1):
            d = point_seg_distance(p, B[k], B[k + 1])
            if d < best:
                best = d
    for p in B:
        for k in range(len(A) - 1):
            d = point_seg_distance(p, A[k], A[k + 1])
            if d < best:
                best = d
    return best

def min_profile_distance(profiles, n=12):
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
            d = _polyline_pair_distance(polys[i], polys[j])
            if d < best:
                best = d
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
    end, both ends sweeping to the SAME side -- of width `gap`, with semicircular
    caps (r = gap/2) at the free ends, inner knee fillets of radius `fillet_r`, and
    outer knee fillets of radius `fillet_r + gap` (constant width preserved).

    Matches the SendCutSend reference DXF: horizontal ~0.65 in, diagonals ~0.19 in
    at ~40 deg; only the gap scales with material thickness. The horizontal edge of
    the slot sits ON the bend line (cy); the swept ends rise (smile) or fall (frown).
    Returns a closed list of ("line", ...) / ("arc", ...) segments.
    """
    if gap <= 0 or slot_len <= 0 or diag_len <= 0:
        raise ValueError("gap, slot_len and diag_len must all be positive")
    if fillet_r <= 0:
        raise ValueError("fillet_r must be > 0 (sharp internal corners crack when bent)")
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

    def cap(center, from_pt):
        # 180-degree end cap, CCW from from_pt; midpoint bulges away from the slot.
        a0 = math.atan2(from_pt.y - center.y, from_pt.x - center.x)
        a1 = a0 + math.pi
        to_pt = Pt(center.x + g2 * math.cos(a1), center.y + g2 * math.sin(a1))
        return ("arc", center, g2, a0, a1, from_pt, to_pt), to_pt

    segs = [("line", La, fBl[0]),
            ("arc", fBl[2], r_out, fBl[3], fBl[4], fBl[0], fBl[1]),
            ("line", fBl[1], fCl[0]),
            ("arc", fCl[2], r_out, fCl[3], fCl[4], fCl[0], fCl[1]),
            ("line", fCl[1], Da)]
    cap_r, du = cap(D, Da)
    segs.append(cap_r)
    segs += [("line", du, fCu[0]),
             ("arc", fCu[2], r_in, fCu[3], fCu[4], fCu[0], fCu[1]),
             ("line", fCu[1], fBu[0]),
             ("arc", fBu[2], r_in, fBu[3], fBu[4], fBu[0], fBu[1]),
             ("line", fBu[1], Au)]
    cap_l, _ = cap(A, Au)
    segs.append(cap_l)
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
# Tessellation: a single wave chain along the bend line
# ---------------------------------------------------------------------------

def _min_ligament_for_pitch(pitch, slot_len, gap, tab, fillet_r, th, diag_len):
    """Four alternating smile/frown slots at this per-slot pitch; tightest gap.

    Covers both junction types (smile->frown, frown->smile) and the same-orientation
    second-neighbour clearance. Coarse sampling (n=6) is safe: the binding ligaments
    are between parallel straight edges (the paired end diagonals, and same-level
    horizontals), where point-to-segment distance is exact at any density.
    """
    cells = [build_wave_cell(slot_len, gap, fillet_r, th, diag_len,
                             orient=+1 if i % 2 == 0 else -1, cx=i * pitch, cy=0.0)
             for i in range(4)]
    return min_profile_distance(cells, n=6)


def solve_pitch(slot_len, gap, tab, fillet_r, end_angle_deg=40.0, samples=48,
                diag_len=0.4826):
    """Smallest per-slot pitch whose every ligament is >= tab (densest valid chain).

    Feasibility is monotone in pitch (spreading slots apart only widens every
    ligament), so the search window GROWS until a feasible pitch is found.
    Raises ValueError only past a hard cap (degenerate cell geometry).
    """
    th = end_angle_deg
    sin_th = math.sin(math.radians(th))
    # Below roughly (tab+gap)/sin(th) the diagonal ligament cannot reach `tab`.
    lo = 0.7 * (tab + gap) / sin_th
    hi = max(2.0 * slot_len, (tab + gap) / sin_th * 2.0)
    cap = 64.0 * (slot_len + tab + gap)  # backstop against an unbounded loop
    while True:
        step = (hi - lo) / samples
        feasible = []
        p = lo
        while p <= hi + 1e-12:
            if _min_ligament_for_pitch(p, slot_len, gap, tab, fillet_r, th,
                                       diag_len) >= tab - 1e-6:
                feasible.append(p)
            p += step
        if feasible:
            return min(feasible)         # smallest feasible pitch = densest chain
        if hi >= cap:
            raise ValueError(
                "no feasible pitch found below cap (degenerate cell geometry?)")
        lo, hi = hi, min(hi * 2.0, cap)  # feasibility is above -> search the next window


def fit_count(bend_len, pitch, margin):
    usable = bend_len - 2.0 * margin
    if usable <= 0:
        return 0
    return max(1, int(usable // pitch) + 1)


def fit_slot_len(bend_len, count, gap, tab, fillet_r, end_angle_deg, margin,
                 diag_len=0.4826):
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
            p = solve_pitch(mid, gap, tab, fillet_r, end_angle_deg, diag_len=diag_len)
        except ValueError:
            lo = mid; continue
        if p < target_pitch:
            lo = mid
        else:
            hi = mid
    result = (lo + hi) / 2.0
    # Verify the requested count actually fits at the resulting slot length.
    try:
        p = solve_pitch(result, gap, tab, fillet_r, end_angle_deg, diag_len=diag_len)
    except ValueError:
        raise ValueError(f"cannot fit {count} slots in bend_len={bend_len:.4f} "
                         f"(implied slot too short to form a cell)")
    achievable = fit_count(bend_len, p, margin)
    if achievable < count:
        raise ValueError(f"cannot fit {count} slots in bend_len={bend_len:.4f} "
                         f"(smallest pitch {p:.4f} fits at most {achievable})")
    return result


def generate_pattern(bend_len, gap, tab, slot_len, fillet_r, end_angle_deg=40.0,
                     diag_len=0.4826):
    """A single wave chain along the bend line: slots alternate smile / frown.

    The slots' horizontal edges sit ON the bend line (v=0), so the pattern is centered
    on the user's selected line by construction. Consecutive slots' swept ends form
    parallel diagonal pairs; the material strip between each pair is the "angled tab".
    The per-slot pitch is solved so NO ligament is narrower than `tab`.

    Returns dict with keys:
      - profiles: list of build_wave_cell outlines (closed loops), left to right
      - count: total slots in the chain
      - pitch: solved per-slot x-advance
      - row_offset: 0.0 (kept for API stability; single-chain layout has no rows)
      - central_tab: the tab target the pitch was solved for (== tab)
      - min_ligament: narrowest measured gap between any two placed slots
    """
    th = end_angle_deg
    pitch = solve_pitch(slot_len, gap, tab, fillet_r, th, diag_len=diag_len)
    # Solid end margins: the end slots must sit fully inside the bend span.
    probe = sample_profile(build_wave_cell(slot_len, gap, fillet_r, th, diag_len), n=4)
    half_w = (max(p.x for p in probe) - min(p.x for p in probe)) / 2.0
    margin = half_w + gap
    count = fit_count(bend_len, pitch, margin)
    if count == 0:
        raise ValueError(
            f"no slots fit: bend_len={bend_len:.4f} too short for slot width "
            f"{2 * half_w:.4f} plus margins; use a longer bend line or shorter slots")
    span = (count - 1) * pitch
    start = (bend_len - span) / 2.0                   # center the chain
    profiles = [build_wave_cell(slot_len, gap, fillet_r, th, diag_len,
                                orient=+1 if i % 2 == 0 else -1,
                                cx=start + i * pitch, cy=0.0)
                for i in range(count)]
    return {
        "profiles": profiles,
        "count": count,
        "pitch": pitch,
        "row_offset": 0.0,
        "central_tab": tab,
        "min_ligament": min_profile_distance(profiles) if count > 1 else float("inf"),
    }
