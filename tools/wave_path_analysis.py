"""Full closed-loop reconstruction of the wave-bend slots in wave-bends.dxf.

Walks complete slot outlines (not partial chains), classifies each loop as
smile / frown / straight, and reports per-sample: gap, end angle, diagonal
length, cap radius, slot length, row spacing d, pitch, and stagger.

This settles the true cell shape: pointed hexagon (what we built) vs
constant-width wave/smile slot (what the article shows).

py tools/wave_path_analysis.py
"""
import math, collections

PATH = "wave-bends.dxf"
TOL = 3  # endpoint rounding decimals for connectivity


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


def entities(path):
    pairs = list(read_pairs(path))
    ents = []
    cur = None
    on = False
    i = 0
    while i < len(pairs):
        code, val = pairs[i]
        if code == "0" and val == "SECTION":
            name = pairs[i + 1][1] if i + 1 < len(pairs) else ""
            on = (name == "ENTITIES")
            i += 2
            continue
        if code == "0" and val == "ENDSEC":
            on = False
        elif on and code == "0":
            if cur:
                ents.append(cur)
            cur = {"type": val, "c": collections.defaultdict(list)}
        elif on and cur is not None:
            cur["c"][code].append(val)
        i += 1
    if cur:
        ents.append(cur)
    return ents


def num(e, c, i=0, d=None):
    v = e["c"].get(c, [])
    return float(v[i]) if i < len(v) else d


def arc_ep(a):
    cx, cy, r = num(a, "10"), num(a, "20"), num(a, "40")
    a0, a1 = math.radians(num(a, "50", 0, 0)), math.radians(num(a, "51", 0, 0))
    return ((cx + r * math.cos(a0), cy + r * math.sin(a0)),
            (cx + r * math.cos(a1), cy + r * math.sin(a1)), r)


def key(p):
    return (round(p[0], TOL), round(p[1], TOL))


def main():
    ents = entities(PATH)
    segs = []
    for e in ents:
        if e["type"] == "LINE":
            p0 = (num(e, "10"), num(e, "20")); p1 = (num(e, "11"), num(e, "21"))
            if None not in p0 and None not in p1:
                segs.append({"k": "LINE", "p0": p0, "p1": p1})
        elif e["type"] == "ARC":
            p0, p1, r = arc_ep(e)
            segs.append({"k": "ARC", "p0": p0, "p1": p1, "r": r})

    adj = collections.defaultdict(list)
    for i, s in enumerate(segs):
        adj[key(s["p0"])].append(i)
        adj[key(s["p1"])].append(i)

    used = set()
    loops = []
    for start in range(len(segs)):
        if start in used:
            continue
        chain = [start]
        used.add(start)
        start_pt = key(segs[start]["p0"])
        cur_pt = key(segs[start]["p1"])
        ok = False
        for _ in range(40):
            if cur_pt == start_pt:
                ok = True
                break
            nxts = [j for j in adj[cur_pt] if j not in used]
            if not nxts:
                break
            j = nxts[0]
            used.add(j)
            chain.append(j)
            s = segs[j]
            cur_pt = key(s["p1"]) if key(s["p0"]) == cur_pt else key(s["p0"])
        if ok and 4 <= len(chain) <= 24:
            loops.append(chain)

    print(f"{len(loops)} closed loops reconstructed\n")

    slots = []
    for chain in loops:
        ss = [segs[i] for i in chain]
        xs = [p for s in ss for p in (s["p0"][0], s["p1"][0])]
        ys = [p for s in ss for p in (s["p0"][1], s["p1"][1])]
        w = max(xs) - min(xs); h = max(ys) - min(ys)
        if not (0.25 < w < 2.5 and 0.02 < h < 0.6):
            continue  # not slot-sized (borders, blocks, text)
        horiz, diag = [], []
        arcs = [s for s in ss if s["k"] == "ARC"]
        for s in ss:
            if s["k"] != "LINE":
                continue
            dx = s["p1"][0] - s["p0"][0]; dy = s["p1"][1] - s["p0"][1]
            L = math.hypot(dx, dy)
            if L < 0.01:
                continue
            ang = math.degrees(math.atan2(dy, dx)) % 180.0
            if ang < 8 or ang > 172:
                horiz.append((s, L))
            elif 25 < ang < 65 or 115 < ang < 155:
                diag.append((s, L, ang))
        if len(horiz) < 2:
            continue
        horiz.sort(key=lambda t: -t[1])
        hy = [(h0["p0"][1] + h0["p1"][1]) / 2 for h0, _ in horiz[:2]]
        gap = abs(hy[0] - hy[1])
        y_h = sum(hy) / 2
        if diag:
            dmid = sum((d0["p0"][1] + d0["p1"][1]) / 2 for d0, _, _ in diag) / len(diag)
            orient = "SMILE" if dmid > y_h + 0.01 else ("FROWN" if dmid < y_h - 0.01 else "FLAT")
            dlen = sum(L for _, L, _ in diag) / len(diag)
            angs = [a if a < 90 else 180 - a for _, _, a in diag]
            dang = sum(angs) / len(angs)
        else:
            orient, dlen, dang = "STRAIGHT", 0.0, 0.0
        rmin = min((s["r"] for s in arcs), default=0.0)
        rmax = max((s["r"] for s in arcs), default=0.0)
        slots.append({
            "cx": (max(xs) + min(xs)) / 2, "cy": (max(ys) + min(ys)) / 2,
            "w": w, "h": h, "gap": gap, "orient": orient, "nseg": len(chain),
            "ndiag": len(diag), "nhoriz": len(horiz), "narc": len(arcs),
            "dlen": dlen, "dang": dang, "rmin": rmin, "rmax": rmax,
        })

    print(f"{len(slots)} slot-sized loops\n")
    oc = collections.Counter(s["orient"] for s in slots)
    print(f"orientation census: {dict(oc)}\n")

    # cluster slots into samples by proximity
    slots.sort(key=lambda s: (round(s["cy"], 0), s["cx"]))
    samples = []
    for s in slots:
        placed = False
        for smp in samples:
            if (abs(s["cy"] - smp["cy"]) < 0.8 and
                    min(abs(s["cx"] - o["cx"]) for o in smp["slots"]) < 2.5):
                smp["slots"].append(s)
                smp["cy"] = sum(o["cy"] for o in smp["slots"]) / len(smp["slots"])
                placed = True
                break
        if not placed:
            samples.append({"cy": s["cy"], "slots": [s]})

    for k, smp in enumerate(s for s in samples if len(s["slots"]) >= 3):
        sl = smp["slots"]
        print(f"=== sample {k}: {len(sl)} slots  (cy~{smp['cy']:.2f}) ===")
        # rows within the sample
        rows = []
        for s in sorted(sl, key=lambda t: t["cy"]):
            for r in rows:
                if abs(s["cy"] - r["cy"]) < max(0.6 * s["gap"], 0.03):
                    r["slots"].append(s)
                    r["cy"] = sum(o["cy"] for o in r["slots"]) / len(r["slots"])
                    break
            else:
                rows.append({"cy": s["cy"], "slots": [s]})
        for ri, r in enumerate(rows):
            rs = sorted(r["slots"], key=lambda t: t["cx"])
            xs = [t["cx"] for t in rs]
            pitches = [round(xs[i + 1] - xs[i], 3) for i in range(len(xs) - 1)]
            o = collections.Counter(t["orient"] for t in rs)
            g = sum(t["gap"] for t in rs) / len(rs)
            dl = sum(t["dlen"] for t in rs) / len(rs)
            da = sum(t["dang"] for t in rs) / len(rs)
            wv = sum(t["w"] for t in rs) / len(rs)
            rmn = sum(t["rmin"] for t in rs) / len(rs)
            rmx = sum(t["rmax"] for t in rs) / len(rs)
            print(f"  row {ri} cy={r['cy']:.3f}: n={len(rs)} orient={dict(o)} "
                  f"gap={g:.3f} slotW={wv:.3f} diagL={dl:.3f}@{da:.0f}deg "
                  f"caps r=[{rmn:.4f}..{rmx:.4f}] pitches={pitches[:6]}")
        if len(rows) >= 2:
            for i in range(len(rows) - 1):
                d = rows[i + 1]["cy"] - rows[i]["cy"]
                a = sorted(t["cx"] for t in rows[i]["slots"])
                b = sorted(t["cx"] for t in rows[i + 1]["slots"])
                if a and b and len(a) > 1:
                    pitch = (a[-1] - a[0]) / (len(a) - 1)
                    stag = min(abs(b[0] - x) % pitch for x in a)
                    print(f"  rows {i}->{i+1}: dy={d:.3f}  stagger~{stag:.3f} of pitch {pitch:.3f}")
        print()


if __name__ == "__main__":
    main()
