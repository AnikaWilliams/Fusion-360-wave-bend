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
