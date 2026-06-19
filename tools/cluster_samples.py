"""Separate the 8 wave-bend samples spatially (connected components on shared
endpoints) and report per-sample numbers: slot length, gap (=2*cap radius),
row pitch, and the implied tab. Grounds our default ratios against G=0.6t etc.

py tools/cluster_samples.py
"""
import math, collections

PATH = "wave-bends.dxf"

def read_pairs(path):
    with open(path,"r",errors="replace") as fh:
        lines = fh.read().splitlines()
    it = iter(lines)
    for code in it:
        try: val = next(it)
        except StopIteration: break
        yield code.strip(), val.strip()

def entities(path):
    pairs = list(read_pairs(path))
    ents=[]; cur=None; name=None; on=False
    i=0
    while i < len(pairs):
        code,val = pairs[i]
        if code=="0" and val=="SECTION":
            name = pairs[i+1][1] if i+1<len(pairs) else ""
            on = (name=="ENTITIES"); i+=2; continue
        if code=="0" and val=="ENDSEC": on=False
        elif on and code=="0":
            if cur: ents.append(cur)
            cur={"type":val,"c":collections.defaultdict(list)}
        elif on and cur is not None:
            cur["c"][code].append(val)
        i+=1
    if cur: ents.append(cur)
    return ents

def n(e,c,i=0,d=None):
    v=e["c"].get(c,[]);
    return float(v[i]) if i<len(v) else d

def arc_ep(a):
    cx,cy,r=n(a,"10"),n(a,"20"),n(a,"40")
    a0,a1=math.radians(n(a,"50",0,0)),math.radians(n(a,"51",0,0))
    return (cx+r*math.cos(a0),cy+r*math.sin(a0)),(cx+r*math.cos(a1),cy+r*math.sin(a1)),r

def main():
    ents=entities(PATH)
    segs=[]
    for e in ents:
        if e["type"]=="LINE":
            p0=(n(e,"10"),n(e,"20")); p1=(n(e,"11"),n(e,"21"))
            if None not in p0 and None not in p1:
                segs.append({"k":"LINE","p0":p0,"p1":p1,
                    "L":math.hypot(p1[0]-p0[0],p1[1]-p0[1]),
                    "ang":math.degrees(math.atan2(p1[1]-p0[1],p1[0]-p0[0]))%180})
        elif e["type"]=="ARC":
            p0,p1,r=arc_ep(e)
            segs.append({"k":"ARC","p0":p0,"p1":p1,"r":r})

    # union-find on rounded endpoints
    parent={}
    def key(p): return (round(p[0],2),round(p[1],2))
    def find(x):
        parent.setdefault(x,x)
        while parent[x]!=x:
            parent[x]=parent[parent[x]]; x=parent[x]
        return x
    def uni(a,b): parent[find(a)]=find(b)
    for s in segs:
        a,b=key(s["p0"]),key(s["p1"]); uni(a,b)
    comp=collections.defaultdict(list)
    for i,s in enumerate(segs):
        comp[find(key(s["p0"]))].append(i)

    big=sorted(comp.values(), key=len, reverse=True)[:12]
    print(f"{len(comp)} components; showing largest {len(big)}\n")
    print(f"{'#':>2} {'segs':>5} {'xmin':>6} {'xmax':>6} {'ymin':>7} {'ymax':>7} "
          f"{'slotLen':>8} {'gap=2r':>7} {'rowPitch':>8} {'tab~':>6} {'#arcs':>6}")
    for ci,idxs in enumerate(big):
        ss=[segs[i] for i in idxs]
        xs=[p for s in ss for p in (s["p0"][0],s["p1"][0])]
        ys=[p for s in ss for p in (s["p0"][1],s["p1"][1])]
        arcs=[s for s in ss if s["k"]=="ARC"]
        hlines=[s for s in ss if s["k"]=="LINE" and (s["ang"]<3 or s["ang"]>177)]
        # slot length = dominant long horizontal line length
        hl=collections.Counter(round(s["L"],3) for s in hlines if s["L"]>0.05)
        slot_len = hl.most_common(1)[0][0] if hl else float("nan")
        # gap = 2 * median cap radius
        rs=sorted(s["r"] for s in arcs)
        gap = 2*rs[len(rs)//2] if rs else float("nan")
        # row pitch = spacing between the horizontal lines' y-levels (distinct ys)
        ylv=sorted(set(round(s["p0"][1],3) for s in hlines))
        diffs=[round(ylv[i+1]-ylv[i],3) for i in range(len(ylv)-1) if ylv[i+1]-ylv[i]>0.02]
        pitch = collections.Counter(diffs).most_common(1)[0][0] if diffs else float("nan")
        tab = pitch-gap if (pitch==pitch and gap==gap) else float("nan")
        print(f"{ci:>2} {len(ss):>5} {min(xs):>6.2f} {max(xs):>6.2f} {min(ys):>7.2f} {max(ys):>7.2f} "
              f"{slot_len:>8.3f} {gap:>7.4f} {pitch:>8.3f} {tab:>6.3f} {len(arcs):>6}")

if __name__=="__main__":
    main()
