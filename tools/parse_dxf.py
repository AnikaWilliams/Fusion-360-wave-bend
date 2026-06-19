"""Parse the SendCutSend wave-bends.dxf and report the slot geometry as numbers.

Plain-Python (no adsk). Run:  py tools/parse_dxf.py
Goal: learn the exact slot shape, stagger, and spacing so we can reproduce it.
"""
import sys, math, collections

PATH = "wave-bends.dxf"

def read_pairs(path):
    with open(path, "r", errors="replace") as fh:
        lines = fh.read().splitlines()
    # DXF = (group code, value) pairs on consecutive lines
    it = iter(lines)
    for code in it:
        try:
            val = next(it)
        except StopIteration:
            break
        yield code.strip(), val.strip()

def parse_entities(path):
    pairs = list(read_pairs(path))
    # find ENTITIES section
    ents = []
    cur = None
    in_entities = False
    i = 0
    while i < len(pairs):
        code, val = pairs[i]
        if code == "0" and val == "SECTION":
            sec_name = pairs[i+1][1] if i+1 < len(pairs) else ""
            in_entities = (sec_name == "ENTITIES")
        elif code == "0" and val == "ENDSEC":
            in_entities = False
        elif in_entities and code == "0":
            if cur is not None:
                ents.append(cur)
            cur = {"type": val, "codes": collections.defaultdict(list)}
        elif in_entities and cur is not None:
            cur["codes"][code].append(val)
        i += 1
    if cur is not None:
        ents.append(cur)
    return ents

def f(ent, code, idx=0, default=None):
    vals = ent["codes"].get(code, [])
    if idx < len(vals):
        try:
            return float(vals[idx])
        except ValueError:
            return default
    return default

def main():
    ents = parse_entities(PATH)
    counts = collections.Counter(e["type"] for e in ents)
    print("=== ENTITY TYPE COUNTS ===")
    for t, c in counts.most_common():
        print(f"  {t:14s} {c}")
    print()

    lines = [e for e in ents if e["type"] == "LINE"]
    arcs  = [e for e in ents if e["type"] == "ARC"]
    circs = [e for e in ents if e["type"] == "CIRCLE"]
    plines = [e for e in ents if e["type"] in ("POLYLINE", "LWPOLYLINE")]

    # ARC radii distribution -> tells us the cap radius (G/2)
    if arcs:
        radii = collections.Counter(round(f(a, "40"), 4) for a in arcs)
        print("=== ARC RADII (count) -> cap radius candidates ===")
        for r, c in sorted(radii.items()):
            print(f"  r={r:.4f}  x{c}")
        print()

    if circs:
        cradii = collections.Counter(round(f(c, "40"), 4) for c in circs)
        print("=== CIRCLE RADII (count) ===")
        for r, c in sorted(cradii.items()):
            print(f"  r={r:.4f}  x{c}")
        print()

    # LINE lengths + angles -> straight slot sides + tab/stagger geometry
    if lines:
        print("=== LINE segments (length, angle deg) ===")
        seglens = collections.Counter()
        angles = collections.Counter()
        for ln in lines:
            x1, y1 = f(ln, "10"), f(ln, "20")
            x2, y2 = f(ln, "11"), f(ln, "21")
            if None in (x1, y1, x2, y2):
                continue
            L = math.hypot(x2 - x1, y2 - y1)
            ang = math.degrees(math.atan2(y2 - y1, x2 - x1)) % 180.0
            seglens[round(L, 4)] += 1
            angles[round(ang, 1)] += 1
        print("  -- distinct lengths --")
        for L, c in sorted(seglens.items()):
            print(f"     L={L:.4f}  x{c}")
        print("  -- distinct angles (mod 180) --")
        for a, c in sorted(angles.items()):
            print(f"     {a:6.1f} deg  x{c}")
        print()

    # POLYLINE analysis: vertices + bulge (group 42) reveal obround slot loops
    if plines:
        print(f"=== {len(plines)} POLYLINEs ===")
        for k, p in enumerate(plines[:6]):
            xs = [float(v) for v in p['codes'].get('10', [])]
            ys = [float(v) for v in p['codes'].get('20', [])]
            bulges = p['codes'].get('42', [])
            print(f"  pline[{k}] verts={len(xs)} bulges={len(bulges)} closed_flag70={p['codes'].get('70')}")

    # Overall bounding box of everything
    allx, ally = [], []
    for e in ents:
        for c in ("10", "11"):
            allx += [float(v) for v in e["codes"].get(c, []) if _num(v)]
        for c in ("20", "21"):
            ally += [float(v) for v in e["codes"].get(c, []) if _num(v)]
    if allx and ally:
        print()
        print("=== GEOMETRY BOUNDS ===")
        print(f"  x: {min(allx):.4f} .. {max(allx):.4f}  (w={max(allx)-min(allx):.4f})")
        print(f"  y: {min(ally):.4f} .. {max(ally):.4f}  (h={max(ally)-min(ally):.4f})")

def _num(v):
    try:
        float(v); return True
    except ValueError:
        return False

if __name__ == "__main__":
    main()
