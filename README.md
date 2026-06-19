# Wave-Bend Generator for Fusion 360

A Fusion 360 add-in (Python) that draws SendCutSend-style **"wave bend" relief-cut
patterns** along a chosen bend line in flat sheet metal, so a part can be folded by
hand without a press brake.

## Status

Design phase complete. See the spec:
[`docs/superpowers/specs/2026-06-19-wave-bend-generator-design.md`](docs/superpowers/specs/2026-06-19-wave-bend-generator-design.md).

## Layout

| Path | What it is |
|---|---|
| `docs/superpowers/specs/` | Design spec(s) |
| `tools/` | Plain-Python DXF analysis scripts (run with `py`, no Fusion needed) |
| `wave-bends.dxf` | SendCutSend reference pattern (ground truth for the cell shape) |

## DXF tools

```
py tools/parse_dxf.py        # entity census + radius/length/angle distributions
py tools/extract_one_slot.py # chains one cell loop + lists the block layout
py tools/cluster_samples.py  # separates the 9 gauge samples, reports per-sample numbers
```

Key finding: the SendCutSend cell is an **elongated angled-end cell with filleted
corners** (not a plain obround); slot length is ~0.65″ across all samples while the
**gap** varies per gauge (consistent with `G ≈ 0.6·t`).
