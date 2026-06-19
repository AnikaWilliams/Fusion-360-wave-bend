"""Reconstruct ONE slot loop from the DXF by chaining LINE/ARC endpoints,
and report the BLOCK/INSERT layout so we understand the multi-sample sheet.

py tools/extract_one_slot.py
"""
import math, collections

PATH = "wave-bends.dxf"

def read_pairs(path):
    with open(path, "r", errors="replace") as fh:
        lines = fh.read().splitlines()
    it = iter(lines)
    for code in it:
        try:
            val = next(it)
        except StopIteration:
            break
        yield code.strip(), val.strip()

def sections(path):
    pairs = list(read_pairs(path))
    secs = collections.defaultdict(list)
    name = None
    i = 0
    while i < len(pairs):
        code, val = pairs[i]
        if code == "0" and val == "SECTION":
            name = pairs[i+1][1] if i+1 < len(pairs) else ""
            i += 2
            continue
        if code == "0" and val == "ENDSEC":
            name = None
        elif name:
            secs[name].append((code, val))
        i += 1
    return secs

def to_entities(pairs):
    ents = []
    cur = None
    for code, val in pairs:
        if code == "0":
            if cur is not None and cur["type"] not in ("SECTION",):
                ents.append(cur)
            cur = {"type": val, "codes": collections.defaultdict(list)}
        elif cur is not None:
            cur["codes"][code].append(val)
    if cur is not None:
        ents.append(cur)
    return ents

def num(e, c, i=0, d=None):
    v = e["codes"].get(c, [])
    return float(v[i]) if i < len(v) else d

def arc_endpoints(a):
    cx, cy, r = num(a,"10"), num(a,"20"), num(a,"40")
    a0, a1 = math.radians(num(a,"50",0,0)), math.radians(num(a,"51",0,0))
    p0 = (cx + r*math.cos(a0), cy + r*math.sin(a0))
    p1 = (cx + r*math.cos(a1), cy + r*math.sin(a1))
    return p0, p1, (cx,cy), r

def main():
    secs = sections(PATH)
    ents = to_entities(secs["ENTITIES"])

    # --- INSERT layout ---
    inserts = [e for e in ents if e["type"] == "INSERT"]
    print(f"=== {len(inserts)} INSERTS ===")
    for e in inserts:
        print(f"  block={e['codes'].get('2')} at ({num(e,'10')},{num(e,'20')}) "
              f"xscale={num(e,'41',0,1)} rot={num(e,'50',0,0)}")
    # --- BLOCK definitions ---
    if "BLOCKS" in secs:
        bents = to_entities(secs["BLOCKS"])
        blocks = collections.Counter(e["codes"].get("2",[None])[0]
                                     for e in bents if e["type"]=="BLOCK")
        print(f"\n=== BLOCK names ===")
        for b,c in blocks.items():
            print(f"  {b}")

    # --- collect drawable segments with endpoints ---
    segs = []  # (p0, p1, kind, meta)
    for e in ents:
        if e["type"] == "LINE":
            p0 = (num(e,"10"), num(e,"20")); p1 = (num(e,"11"), num(e,"21"))
            if None not in p0 and None not in p1:
                segs.append((p0, p1, "LINE", None))
        elif e["type"] == "ARC":
            p0, p1, c, r = arc_endpoints(e)
            segs.append((p0, p1, "ARC", r))

    # --- pick a starting slot: the leftmost-lowest ARC, chain its loop ---
    def key(p): return (round(p[0],3), round(p[1],3))
    adj = collections.defaultdict(list)
    for idx,(p0,p1,k,m) in enumerate(segs):
        adj[key(p0)].append(idx)
        adj[key(p1)].append(idx)

    # find a region with small arcs (a slot cap), start there
    arcs = [(i,s) for i,s in enumerate(segs) if s[2]=="ARC"]
    arcs.sort(key=lambda t: (t[1][0][1], t[1][0][0]))  # lowest y first
    start = arcs[len(arcs)//2][0]  # a middle arc, avoid border artifacts

    used = set()
    loop = []
    cur = start
    cur_pt = key(segs[cur][1])
    loop_pts = [segs[cur][0], segs[cur][1]]
    used.add(cur)
    for _ in range(64):
        nxts = [j for j in adj[cur_pt] if j not in used]
        if not nxts:
            break
        j = nxts[0]
        p0,p1,k,m = segs[j]
        # orient: continue from cur_pt
        if key(p0) == cur_pt:
            nxt_pt = key(p1); loop_pts.append(p1)
        else:
            nxt_pt = key(p0); loop_pts.append(p0)
        loop.append((k, m, p0, p1))
        used.add(j)
        cur_pt = nxt_pt
        if cur_pt == key(loop_pts[0]):
            break

    print(f"\n=== ONE RECONSTRUCTED LOOP (start arc idx {start}) ===")
    print(f"  segments in loop: {len(loop)}  (LINE/ARC kinds: "
          f"{collections.Counter(k for k,_,_,_ in loop)})")
    xs = [p[0] for p in loop_pts]; ys = [p[1] for p in loop_pts]
    if xs:
        print(f"  loop bbox: w={max(xs)-min(xs):.4f}  h={max(ys)-min(ys):.4f}")
    for k,m,p0,p1 in loop:
        if k == "LINE":
            L = math.hypot(p1[0]-p0[0], p1[1]-p0[1])
            ang = math.degrees(math.atan2(p1[1]-p0[1], p1[0]-p0[0])) % 360
            print(f"  LINE  L={L:.4f}  ang={ang:6.1f}  {tuple(round(v,3) for v in p0)}->{tuple(round(v,3) for v in p1)}")
        else:
            print(f"  ARC   r={m:.4f}  {tuple(round(v,3) for v in p0)}->{tuple(round(v,3) for v in p1)}")

if __name__ == "__main__":
    main()
