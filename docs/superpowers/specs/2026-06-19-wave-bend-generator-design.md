# Wave-Bend Generator for Fusion 360 — Phase 1 Design Spec

**Date:** 2026-06-19
**Status:** Design approved (Approach A + fillet-radius input); pending spec review.

A Fusion 360 add-in (Python) that draws SendCutSend-style "wave bend" relief-cut
patterns along a chosen bend line in flat sheet metal, so a part can be folded by
hand without a press brake. The pattern math was previously built in
Grasshopper/Kangaroo; the new work is the Fusion API surface and packaging.

---

## 1. Ground truth extracted from the reference DXF

Parsed `wave-bends.dxf` (AutoCAD R12, decimal/inch, ~33k lines) with plain-Python
tools in `tools/` (no `adsk` needed). The file is a **parametric catalog**: 8 block
references (`AIGNBL0301xxxx` / `AIGNBL0601xxxx`) plus directly-drawn artwork —
several gauge samples on one sheet, not a single pattern.

| Finding | Value | Consequence for our design |
|---|---|---|
| Slot length `Ls` | **≈ 0.651″, constant across all 9 samples** | SendCutSend fixes cell length and varies the *gap* per gauge. We seed `Ls ≈ 0.65″` as default. |
| Gap (≈ 2 × corner-fillet radius)¹ | ranges **0.031″ → 0.135″** | Per-gauge; consistent with `G ≈ 0.6·t` for `t ≈ 0.05″–0.22″`. |
| Cell ends | **angled (±≈40°), pointed, rounded corners** — NOT semicircular | The slot is an elongated angled-end cell, not a plain obround. The angled end is what forms the diagonal "angled tab." |
| Corner fillets | present on every cell, r ≈ `G/2` in samples | Confirms the "no sharp internal corner" rule; grounds the fillet-radius default. |
| Tessellation | two brick-staggered rows straddling the line; constant-width diagonal ligaments | Matches the article's method; the diagonal ligament IS the tab `T`. |

¹ The arcs measured are the **corner fillets**; the gap (slot width) is the cell
height. In these samples the fillet radius ≈ `G/2`, so `2 × fillet ≈ G` — the figures
are a good approximation, not an exact gap read. The port's cell math sets `G` directly.

**Reproducer tools (committed under `tools/`):** `parse_dxf.py` (entity census),
`extract_one_slot.py` (chains one cell loop + block layout), `cluster_samples.py`
(separates the samples, reports per-sample `Ls`/gap/pitch). These also serve as the
proof that the pure-Python half of the project runs on this machine.

---

## 2. The slot cell (Approach A — faithful reproduction)

The generator reproduces the real SendCutSend cell, **not** an obround:

- An elongated cell whose long axis runs **along the bend line** (`u`).
- Two long edges parallel to `u`; each end formed by **angled edges (~40°)**
  converging toward a point.
- **All corners filleted** by radius `R` (user input), so there are no sharp
  internal corners (the crack-prevention rule).
- The exact cell vertex math is the **ported Grasshopper/Kangaroo logic** — that
  is why it lives isolated in `geometry.py`.

Two rows of these cells straddle the bend line (`v = +d` and `v = −d`), brick-
staggered along `u` so the leftover material between a cell's angled end and its
neighbour's angled end is a **constant-width diagonal strip = the tab `T`**.

**Invariant (non-negotiable):** no ligament — straight or diagonal — is ever
narrower than `T`. The tessellation parameters (`d`, stagger, count) are solved to
honour this.

---

## 3. Parameters, defaults, rules

| Param | Meaning | Default / prefill | Rule |
|---|---|---|---|
| `t` thickness | sheet gauge | **measured from the body**, override editable | drives the others |
| `mat` material | physical material family | **read from the body**, override dropdown | sets the gap multiplier `m` |
| `G` gap | slot cut width | `m · t` (m from `mat`) | soft alu `m=0.6`; harder steel/Ti `m≈0.7` |
| `T` tab | narrowest remaining material | `= t` | `≥ t`, straight-line |
| `Ls` slot length | cell length along `u` | `≈ 0.65″` (from DXF) | user choice |
| `N` slot count | cells across the bend | computed from `B` | interlinked with `Ls` |
| `R` fillet radius | corner rounding radius | `G / 2` | `> 0` (no sharp corners); small enough that no ligament `< T` |
| `θ` end angle | angle of the cell's pointed ends | **fixed at 40°** (v1) | constant; not a v1 input |
| margins | solid material at each band end | computed | band never ends on a slot |

`B` = bend-line length (read from the selected edge/line). The gap multiplier `m`
comes from the detected material family (table in `config.py`): aluminum/soft → 0.6,
steel/stainless/titanium/hard → 0.7, unknown → 0.6 fallback.

---

## 4. `geometry.py` contract (pure, no `adsk`)

Isolated, unit-testable with plain `py` outside Fusion. Works in document units
(inch/mm) — unit→cm conversion happens later, in the Fusion layer only.

```
generate_pattern(bend_length, t, gap, tab, slot_len, fillet_r, end_angle=40.0)
    -> list[Profile]          # closed cell profiles in local (u, v) frame
fit_count(bend_length, slot_len, ...)   -> int      # for interlinked inputs
fit_slot_len(bend_length, count, ...)   -> float    # for interlinked inputs
```

`Profile` = ordered list of segments, each `Line(p0, p1)` or `Arc(p0, p1, center, r)`,
forming a **closed** loop. The Fusion layer maps the local `(u, v)` frame onto the
selected face and emits sketch geometry.

---

## 5. Architecture & build order

Per the "prototype-as-script-first" rule, Phase 1 ships in two stages that share
`geometry.py`:

- **Stage 1a — run-once script** (`wave_bend_script.py`): hard-coded inputs, calls
  `geometry.py`, builds one sketch + one extrude-cut. Fast to re-run while we get the
  cell math and the cut pipeline right. **This is what gets tested first.**
- **Stage 1b — packaged add-in** (`WaveBend/` tree below): same `geometry.py`,
  wrapped in the `commandCreated` (build dialog) / `execute` (build geometry)
  handlers. Built only after the geometry is proven in Stage 1a.

**De-risking move:** wire the full Fusion pipeline end-to-end *first* (select line →
sketch → single extrude-cut) using any compiling profile, then drop in the exact
cell math. This separates "is the Fusion plumbing right" from "is the cell shape
right" — two distinct failure modes.

```
WaveBend/
  WaveBend.py            # entry: run() / stop()
  WaveBend.manifest      # name, author, auto-load
  config.py              # defaults + material→gap-multiplier table
  commands/waveBendCmd/entry.py   # commandCreated + execute
  lib/fusion360utils/    # template helpers
  lib/geometry.py        # ported Grasshopper math (pure)
tools/                   # DXF analysis scripts (already built)
wave_bend_script.py      # Stage 1a prototype
```

---

## 6. The dialog (Phase 1) — interlinked inputs

Fields: **bend-line selection** (edge or sketch line) · **thickness `t`** (value, w/
units — *prefilled from the measured body*, editable override) · **material** (dropdown
— *preset to the detected family*, editable override) · **gap `G`** (prefill `m·t`) ·
**tab `T`** (prefill `t`) · **fillet radius `R`** (prefill `G/2`) · **slot length
`Ls`** ↔ **slot count `N`** (interlinked).

On `commandCreated`, before showing the dialog: resolve the host body from the
selected bend line, **measure `t`** (extent perpendicular to the bend face) and **read
its material**, then seed `t`, `material`, and `G` accordingly. If either can't be
determined, fall back to sensible defaults and let the user type the override.

`Ls` ↔ `N` behaviour via an `inputChanged` handler: editing `Ls` recomputes `N`
(`fit_count`); editing `N` recomputes `Ls` (`fit_slot_len`); **last-edited-wins**,
both stay editable. Defaults seed `Ls ≈ 0.65″` → typically 6+ cells across a bend.

---

## 7. Non-obvious technical decisions (plain language)

- **Units — the #1 plugin killer.** The Fusion API stores *all* lengths in
  **centimeters** regardless of document units. `geometry.py` stays in document
  units; conversion to cm happens in **exactly one place** — the boundary where the
  Fusion layer creates points — so the factor can't silently spread through the math.
- **Where the cut goes.** We sketch on the planar face that contains the selected
  bend line and **extrude-cut through the full thickness**.
- **Reading thickness & material from the file.** A generic solid has no stored
  "sheet thickness" property, so we *measure* it: take the body's extent along the
  normal of the bend face (distance between the two large parallel faces). Material is
  read from the body's assigned **physical material name** and mapped to a family →
  gap multiplier `m` via a small table in `config.py` (substring match on
  alumin/steel/stainless/titanium; unknown → 0.6). Both are seeds only — the typed
  overrides always win. (Method names — `BRepBody.physicalProperties`, `.material`,
  bounding box — get verified against the API docs, not memory.)
- **Closed profiles, one cut.** All cells go into a single sketch as closed loops;
  one extrude-cut consumes them all → clean timeline, fast. Open loops won't cut.
- **Non-destructive.** Added as a normal rollback-able timeline feature; the user's
  body is never deleted.
- **Verification loop.** Fusion runs the code, not the dev tool. Every entry point is
  wrapped in `try/except` that prints the full traceback to the **Text Commands**
  palette; the user runs it in Fusion and pastes errors back. Optional file logging.

---

## 8. Scope

**In (Phase 1):** select bend line → `t` and material **auto-read from the body**
(editable overrides) → editable `G`, `T`, `R`, `Ls`/`N` → generate brick-staggered
angled-end cells straddling the line → one extrude-cut through thickness → flat part
ready to bend. Stage 1a script then Stage 1b add-in. **Material detection + auto gap
multiplier are now in v1** (pulled forward from Phase 2) via the `config.py` family
table and the material override dropdown.

**Out (later phases):** 3-D folding · DXF export · OSSB length compensation · live
preview · rich inline validation warnings.

---

## 9. Risks / open items

- **Exact cell topology** (hexagonal angled-end vs. rounded-point) comes from the
  ported Grasshopper math; the DXF confirms the *family*, the port fixes the details.
- **Fillet vs. tab interaction:** large `R` can pinch a ligament below `T`. Phase 1
  computes/validates; rich inline warnings are Phase 2.
- **End angle** — **fixed at 40° for v1** (decided); expose as input only if needed later.
- **Thickness measurement** depends on the host being a flat plate with two large
  parallel faces; degenerate/curved bodies fall back to the typed `t`.
- **Material name → family mapping** is heuristic (substring match); unrecognised
  materials fall back to `m = 0.6` and the user can override the dropdown.
- **Face/edge selection robustness** (non-planar host, line not on a face edge) —
  handle with clear errors in the `execute` handler.
