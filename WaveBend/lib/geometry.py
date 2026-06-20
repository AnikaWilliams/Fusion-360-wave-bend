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
            A, B = polys[i], polys[j]
            for p in A:
                for k in range(len(B) - 1):
                    d = point_seg_distance(p, B[k], B[k + 1])
                    if d < best:
                        best = d
    return best

def fillet_corner(A, B, C, R):
    """Tangent fillet of radius R at vertex B (edges B->A and B->C). Convex corners."""
    v1 = v_unit(v_sub(A, B)); v2 = v_unit(v_sub(C, B))
    cosang = max(-1.0, min(1.0, v1.x * v2.x + v1.y * v2.y))
    phi = math.acos(cosang)                      # interior angle at B
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

def filleted_polygon(verts, R):
    """Closed profile: for each vertex emit its arc (T1->T2) then a line to the
    next vertex's entry tangent point. Returns [arc, line, arc, line, ...]."""
    n = len(verts)
    f = [fillet_corner(verts[(i - 1) % n], verts[i], verts[(i + 1) % n], R)
         for i in range(n)]
    segs = []
    for i in range(n):
        T1, T2, c, a0, a1, _ = f[i]
        segs.append(("arc", c, R, a0, a1, T1, T2))
        next_T1 = f[(i + 1) % n][0]
        segs.append(("line", T2, next_T1))
    return segs

def build_cell(slot_len, gap, fillet_r, end_angle_deg=40.0, cx=0.0, cy=0.0):
    """Filleted angled-end hexagon cell centered at (cx, cy), long axis along x."""
    th = math.radians(end_angle_deg)
    # The angled-end straight segment has length proportional to (gap/2 - fillet_r)
    # for ANY end angle, so fillet_r == gap/2 collapses the ends to zero-length
    # segments and fillet_r > gap/2 makes them self-intersect. Reject both.
    if fillet_r >= gap / 2.0:
        raise ValueError(
            f"fillet_r={fillet_r:.4f} must be < gap/2={gap / 2.0:.4f} (cell ends degenerate)")
    ext = (gap / 2.0) / math.tan(th)          # how far each pointed end extends past the flats
    a = slot_len / 2.0 - ext                   # half-length of the flat top/bottom edges
    if a <= fillet_r * 1.05:
        raise ValueError(
            f"slot_len={slot_len:.4f} too short for fillet_r={fillet_r:.4f} at {end_angle_deg} deg")
    h = gap / 2.0
    verts = [
        Pt(cx - a, cy + h),        # top-left
        Pt(cx + a, cy + h),        # top-right
        Pt(cx + slot_len / 2.0, cy),  # right point
        Pt(cx + a, cy - h),        # bottom-right
        Pt(cx - a, cy - h),        # bottom-left
        Pt(cx - slot_len / 2.0, cy),  # left point
    ]
    return filleted_polygon(verts, fillet_r)


# ---------------------------------------------------------------------------
# Tessellation helpers
# ---------------------------------------------------------------------------

def _row_offset(gap, tab):
    """v-distance of each row center from the bend line so the central tab == tab."""
    return (tab + gap) / 2.0


def _min_ligament_for_pitch(pitch, slot_len, gap, tab, fillet_r, th):
    """Build a small 2-row x 3-col patch at this pitch and measure the tightest gap."""
    d = _row_offset(gap, tab)
    cells = []
    for v, off in ((+d, 0.0), (-d, pitch / 2.0)):
        for i in range(3):
            cells.append(build_cell(slot_len, gap, fillet_r, th, off + i * pitch, v))
    return min_profile_distance(cells)


def solve_pitch(slot_len, gap, tab, fillet_r, end_angle_deg=40.0, samples=48):
    th = end_angle_deg
    ext = (gap / 2.0) / math.tan(math.radians(th))
    lo = 2.0 * ext + 0.05 * slot_len     # below this, pointed ends collide
    hi = 1.6 * slot_len
    step = (hi - lo) / samples
    feasible = []
    p = lo
    while p <= hi + 1e-12:
        if _min_ligament_for_pitch(p, slot_len, gap, tab, fillet_r, th) >= tab - 1e-6:
            feasible.append(p)
        p += step
    if not feasible:
        raise ValueError(
            "no feasible pitch: tab is too large for this slot length / gap / fillet")
    return min(feasible)                  # smallest feasible pitch = densest pattern


def fit_count(bend_len, pitch, margin):
    usable = bend_len - 2.0 * margin
    if usable <= 0:
        return 0
    return max(1, int(usable // pitch) + 1)


def fit_slot_len(bend_len, count, gap, tab, fillet_r, end_angle_deg, margin):
    """Invert fit_count: pick the slot_len whose solved pitch yields ~count cells.

    Returns a slot_len such that solve_pitch(result) yields a feasible pitch, or raises
    ValueError if no feasible pitch exists in the search range (e.g., tab too large).
    """
    usable = max(bend_len - 2.0 * margin, 1e-6)
    target_pitch = usable / max(count, 1)
    # binary search slot_len so solve_pitch(slot_len) ~= target_pitch (pitch grows with slot_len)
    lo, hi = 4.0 * fillet_r + 1e-3, 4.0 * bend_len
    for _ in range(40):
        mid = (lo + hi) / 2.0
        try:
            p = solve_pitch(mid, gap, tab, fillet_r, end_angle_deg)
        except ValueError:
            lo = mid; continue
        if p < target_pitch:
            lo = mid
        else:
            hi = mid
    result = (lo + hi) / 2.0
    # Guard: verify result actually yields a feasible pitch
    try:
        solve_pitch(result, gap, tab, fillet_r, end_angle_deg)
    except ValueError:
        raise ValueError(
            f"cannot fit {count} slots: tab too large for this bend length / gap / fillet")
    return result


def generate_pattern(bend_len, gap, tab, slot_len, fillet_r, end_angle_deg=40.0):
    """Tessellate cells along a bend in two brick-staggered rows.

    Args: bend_len (float) - total bend length to tessellate
          gap, tab, slot_len, fillet_r, end_angle_deg - cell geometry params

    Returns dict with keys:
      - profiles: list of build_cell profiles (filleted polygons)
      - count: cells in the UPPER row (representative 'cells per row'; lower row may
               differ by ±1 due to brick offset)
      - pitch: solved pitch (x-spacing between cells within a row)
      - row_offset: y-distance from bend center to each row
      - central_tab: clearance between rows == tab (by construction)
      - min_ligament: narrowest gap between any two placed cells

    Note: len(result["profiles"]) is TOTAL cells placed; count is upper-row count.
    """
    th = end_angle_deg
    d = _row_offset(gap, tab)
    pitch = solve_pitch(slot_len, gap, tab, fillet_r, th)
    margin = pitch / 2.0                              # solid end margins, half a pitch
    count = fit_count(bend_len, pitch, margin)
    span = (count - 1) * pitch
    start = (bend_len - span) / 2.0                   # center the band
    profiles = []
    for v, row_off in ((+d, 0.0), (-d, pitch / 2.0)):
        u = start + row_off
        while u <= bend_len - margin + 1e-9:
            if u >= margin - 1e-9:
                profiles.append(build_cell(slot_len, gap, fillet_r, th, u, v))
            u += pitch
    return {
        "profiles": profiles,
        "count": count,
        "pitch": pitch,
        "row_offset": d,
        "central_tab": 2.0 * d - gap,                 # == tab by construction
        "min_ligament": min_profile_distance(profiles) if len(profiles) > 1 else float("inf"),
    }
