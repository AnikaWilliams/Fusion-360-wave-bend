# Codex review instructions for WaveBend

## Review guidelines

- Independently recompute every changed dimension, pitch, ligament, radius, margin, count,
  transform, unit conversion, and material-derived default. Do not accept the implementation
  or its tests as the only oracle.
- When shared geometry, configuration, Fusion mapping, persistence, or export code changes,
  check its effect on every pattern style and every user-visible dimension, including
  unchanged callers and boundary cases.
- Treat any defect that can change a generated cut, overstate remaining material, select the
  wrong material/thickness, or extrapolate a physical rule beyond its evidence as P1.
- Do not approve claims of bendability, crack resistance, hand force, fatigue life, or safety
  from two-dimensional geometry alone. Require the evidence and validation described below.
- Keep GitHub comments focused on actionable P0/P1 defects. Do not inflate a speculative or
  purely stylistic concern into P1; state unverified physical validation as a residual risk
  when it is not a defect in the changed code.

## Scope and mission

These instructions apply to the entire repository. Review this project as both:

1. a Fusion 360 geometry add-in, and
2. a generator of manufacturing geometry that can materially weaken sheet metal.

The review goal is to find calculation, geometry, unit, API, and evidence errors before a
pattern is cut. It is **not** to certify a part, a material, or a fabrication process as safe.
A passing software review means that the implemented geometry satisfies its stated,
testable contract. It does not mean that a person can safely bend the resulting part or that
the part is suitable for structural, fatigue, pressure, lifting, vehicle, aerospace, medical,
or other safety-critical service.

Review findings first. Cite the smallest useful file and line range, explain the failure mode,
and name the input range that triggers it. Do not approve a physical claim merely because
the unit tests pass or a generated sketch looks plausible.

## Non-negotiable safety boundary

Always keep these four claims separate:

- **Geometrically valid:** closed, non-self-intersecting, buildable profiles with the reported
  spacing and dimensions.
- **Manufacturable:** compatible with a named cutting process, machine capability,
  tolerances, material product, and post-processing route.
- **Bendable:** reaches a specified angle with a specified tool/fixture and force without an
  unacceptable crack, tear, buckle, or amount of springback.
- **Fit for service:** retains adequate static strength, stiffness, fatigue life, corrosion
  resistance, and damage tolerance after bending.

Evidence for one level does not establish the next. Report a blocking finding when code,
documentation, tests, or UI wording collapses these levels into words such as `safe`,
`fracture-safe`, `works for all metals`, `guaranteed`, or `validated` without scope-specific
evidence.

The current values such as `tab = 1*t`, family gap multipliers, a positive fillet, or a
roughly 3 mm advisory ceiling are design heuristics. They are not universal allowables.
Likewise, a computed `min_ligament >= tab` proves a two-dimensional spacing condition only;
it does not prove bendability, residual strength, or fatigue life.

Do not silently weaken a guardrail. If a requested behavior cannot be justified, preserve a
warning or return an explicit `unsupported/not validated` result. Never invent material
properties, gauge conversions, K-factors, forming limits, stress-concentration factors, or
cutting tolerances.

## Repository map and high-risk paths

- `WaveBend/lib/geometry.py`: pure, unit-agnostic profile construction, pitch solving, cell
  placement, and reported minimum ligament. Treat every change here as calculation-critical.
- `WaveBend/config.py`: material-family defaults and pattern-specific heuristics. Treat these
  as suggestions, never material certification.
- `WaveBend/lib/fusion_build.py`: maps mathematical profiles into Fusion, finds bodies,
  reads thickness/material metadata, checks clearance, and creates cuts.
- `WaveBend/commands/waveBendCmd/entry.py`: user inputs, automatic defaults, cached pitch
  model, warnings, preview, persistence, editing, and material-change rebuilds.
- `WaveBend/lib/dxf_post.py` and DXF tools/tests: exported manufacturing dimensions and unit
  conversions.
- `tests/`: the executable geometry contract. New formulas and new input domains need tests.
- `docs/pattern-research.md`: research notes, not a normative material specification. Flag
  any statement that generalizes a limited experiment, patent, or vendor rule of thumb.

Trace a changed input through all of these layers. In particular, check that preview, final
build, edit, rebuild, DXF export, saved payloads, status text, and tests use the same values,
units, style, and interpretation.

## Required online research for mechanics-affecting reviews

For every change that introduces or changes a material rule, thickness limit, force/strain
formula, bend radius, springback estimate, relief topology, curved-path behavior, or safety
claim, do fresh online research before approving it.

Use this evidence order:

1. the applicable current material/product standard and bend-test standard;
2. the exact mill or producer data sheet for the alloy, temper/condition, product form, and
   thickness under review;
3. peer-reviewed experiments or a thesis with stated specimens, tooling, boundary
   conditions, and validation data;
4. the cutting/forming vendor's current capability and tolerance documentation;
5. patents and trade guides only as topology ideas or starting heuristics.

Prefer primary sources. Record the URL, revision/publication date, access date, material,
condition, thickness range, bend orientation, process, and test configuration in the PR or a
repository research note. A search snippet, unsourced calculator, marketing claim, forum,
or AI-generated table is not evidence. Use at least one exact-material source and one
independent mechanics/test source for a physical rule. General claims spanning material
families require family-specific sources; one aluminum experiment cannot validate steel,
stainless, titanium, copper, nickel, or magnesium.

Check that a source actually supports the number being encoded. Do not transfer a ratio
between different relief topologies: a narrow slit designed to create a virtual fulcrum is
not equivalent to an open wave cutout, dogbone, straight slot, diamond, or meander. Do not
transfer press-brake results directly to hand folding of perforated material.

If authoritative data cannot be found for the exact case, the expert result is
`unsupported—coupon test/engineering analysis required`, not interpolation from a material
family dropdown.

## Material and gauge guardrails

Never reason from `Aluminum`, `Mild Steel`, `Stainless Steel`, or `Titanium` alone. Before a
physical recommendation, require or explicitly state that these inputs are missing:

- governing material specification and exact grade/alloy;
- temper, heat treatment, cold-worked/annealed condition, hardness, and coating/cladding;
- product form and actual thickness with tolerance;
- rolling/grain direction relative to the local bend direction;
- certified or producer data for yield strength, tensile strength, elastic modulus, and
  applicable ductility/formability properties;
- target bend angle, final inside radius, flange/lever geometry, and one-time versus cyclic
  use;
- cutting process, nominal kerf, kerf/profile tolerance, taper, heat-affected zone, burr,
  dross, edge roughness, and post-cut edge treatment;
- temperature, strain rate, prior forming, welds, holes, scratches, corrosion, and service
  loads where relevant.

`Gauge` is not a material-independent dimension. Convert a gauge designation only through
the governing product/vendor table for that material, then carry a real thickness and its
tolerance through the calculations. Reject a single universal gauge-to-thickness table.
Prefer measured body thickness or the exact Fusion sheet-metal rule, and make any mismatch
between user entry, rule thickness, measured thickness, and stock tolerance visible.

Material-specific review posture:

- **Aluminum:** alloy and temper are mandatory. Bendability can change radically between an
  annealed temper and a precipitation-hardened temper. Check grain orientation, bend angle,
  thickness, minimum radius, surface/coating condition, and the exact product specification.
- **Carbon, HSLA, AHSS, spring, tool, and wear steels:** do not let the word `steel` select a
  common radius or springback. Strength level, microstructure, rolling direction, edge
  quality, prior cold work, and thermal-cut condition matter.
- **Stainless steel:** distinguish austenitic, ferritic, martensitic, precipitation-hardening,
  and duplex grades. Their work hardening, minimum radius, edge sensitivity, and springback
  differ.
- **Titanium:** distinguish commercially pure grades from alpha/beta alloys and their
  conditions. Do not apply a generic titanium multiplier; some titanium alloys need much
  larger radii and exhibit substantial springback or require warm forming.
- **Copper, brass, bronze, nickel alloys, and spring strip:** require exact alloy and temper.
  Tensile elongation alone is not a bendability criterion; use producer minimum-bend-radius
  data for the bend direction.
- **Magnesium, coated/clad stock, foil, cast material, tubes, welded products, and any
  unlisted family:** unsupported by default. Require a product-specific forming source and a
  separate validation plan. This add-in's flat-sheet rules must not be generalized to tubes,
  castings, or weld bend tests.

## Mechanics and calculation checks

### Dimensions and units

- Fusion API internal lengths are centimeters. Confirm every API boundary, UI expression,
  DXF unit, JSON value, cache key, and test fixture explicitly preserves the intended unit.
- Pure geometry must remain unit-agnostic: scaling every length by `q > 0` must scale every
  returned point, radius, pitch, margin, and ligament by `q`, without changing counts except
  at a documented boundary.
- Do not compare a length to a unitless ratio or hide tolerances in magic epsilons. Give each
  tolerance a physical/numerical purpose and test both sides of it.
- Reject ambiguous angle conventions. State radians versus degrees and bend angle versus
  included/open angle at each formula boundary.

### Conventional solid-sheet bending

For a uniform cylindrical bend, the linear K-factor model is:

`R_n = R_i + K*t`

`BA = theta * (R_i + K*t)`

where `R_n` is neutral-axis radius, `R_i` is final inside radius, `t` is actual thickness,
`theta` is the bend angle in radians, and `K` is the neutral-axis offset divided by
thickness. Under the same idealized geometry, nominal outer-fiber engineering strain is

`epsilon_outer = (1 - K)*t / (R_i + K*t)`.

Use these only when their assumptions match. Verify `0 <= K <= 1`, the angle convention,
and whether `R_i` is loaded-tool radius or final unloaded radius. K-factor must come from an
applicable Fusion rule, bend table, calibrated coupon, or justified source for the actual
material/process. A convenient default K-factor is not a safety limit. Conventional bend
allowance/deduction and solid-sheet minimum-radius tables generally do not predict a
perforated hinge whose ligaments bend and twist in combined modes.

For a first-pass uniform rectangular-section check, first yield and fully plastic moments
are respectively `M_y = sigma_y*b*t^2/6` and `M_p = sigma_y*b*t^2/4`, and an ideal hand
force estimate is `F = M/L` for lever arm `L`. These are screening bounds only. Do not scale
them by open-area percentage and call the result a verified wave-bend force: discrete tabs,
torsion, contact, large rotations, notches, work hardening, and load sharing invalidate that
shortcut.

### Material-subtraction / living-hinge mechanics

- Removing material lowers the load path and bending force but also lowers stiffness,
  residual section, strength, and often fatigue life. Require both an actuation calculation
  and a post-bend service calculation.
- Distinguish designed finished opening width from machine kerf. A DXF closed contour,
  cutter centerline, and single slit have different compensation. The UI, math, and export
  must use one documented meaning.
- Compute the true minimum remaining ligament between finished cut boundaries, including
  non-neighboring cells, same-orientation second neighbors, row interactions, part edges,
  other holes/cuts, and pattern endpoints. Centerline distance is not ligament width.
- Apply worst-case manufacturing stack-up. If two opposing cut boundaries can each move
  outward by `e`, a nominal ligament can lose up to `2*e`, before registration and material
  effects. Use the vendor's profile/kerf/taper tolerances and the adverse thickness limit.
- A sampled polyline distance is not exact merely because the sample count is high. Prove a
  conservative chord/sagitta error bound for every arc/spline, or use exact curve-distance
  methods. Test that the reported `min_ligament` and the pitch solver cannot overstate the
  manufactured ligament.
- Verify each profile is closed, finite, consistently oriented, nonzero-area,
  non-self-intersecting, and free of duplicate/zero-length segments. Verify line/arc endpoint
  continuity and intended tangency. Check fillet feasibility on both incident edges and
  offset-curve singularities.
- A fillet or enlarged end hole can reduce a stress concentration, but `fillet > 0` does not
  prevent cracking. Reject comments or errors that claim it does. A published dogbone or
  fillet ratio is not portable across slot shapes, materials, thicknesses, or cut processes.
- Check net section, tear-out paths, local bearing/contact, post-bend angle, edge contact,
  and whether tabs see bending, torsion, tension, or shear. Minimum Euclidean spacing alone
  misses all of these.
- Do not claim `hand bendable` without a stated target angle, flange/lever length, maximum
  acceptable hand/tool force, fixture, direction, rate, and temperature. A warning based on
  thickness alone is insufficient.
- One-time assembly folds and repeatedly flexed hinges are different products. Any cyclic
  claim requires a load spectrum, mean stress, environment, surface/cut condition, desired
  reliability, fatigue test plan, and inspection/failure criterion. Static bend success is
  not fatigue validation.
- Check the final joint, not just the flat blank. More/larger openings usually make folding
  easier while weakening the seam. UI optimization must expose that tradeoff and must not
  optimize only for minimum force or maximum slot count.

### Material data and numerical models

- Use lower-bound/upper-bound properties consistently. For force, fracture, springback, and
  residual strength, the adverse bound may be different; document it.
- A stress above yield is not automatically fracture, and von Mises stress is not a ductile
  fracture criterion. Conversely, stress below ultimate strength at a singular notch is not
  proof against cracking.
- If FEA is used, require the actual stress-strain curve, plasticity/anisotropy model,
  damage/fracture calibration where fracture is claimed, cut geometry and edge condition,
  contact/friction, forming history, appropriate shell/solid resolution through thickness,
  local mesh convergence, and validation against coupons. Screenshots of colored contours
  are not validation.
- Springback depends on material state, geometry, tooling/contact, and the removed-material
  pattern. Perforated-sheet experiments show that handbook values for solid stock cannot be
  assumed. Require experiment or a validated model for precision angle claims.

## Curved bend-path mechanics

A curved line in a flat blank is not a straight bend with rotated copies of the same cell.
Review curved-path work with the following contract.

Parameterize the planar bend path by arc length `s`:

`x(s, v) = r(s) + v*n(s)`, with `|r'(s)| = 1`.

Here `n(s)` is a continuous in-plane normal and `v` is signed offset from the path. The
mapping's along-path scale is `|1 - kappa(s)*v|` (the sign depends on the normal convention).
Therefore:

- place cell centers by centerline arc length, not chord length, x-coordinate, parameter
  fraction, or bounding-box length;
- map every boundary point through the local path frame; translating a straight-cell outline
  without accounting for curvature gives the wrong inner/outer spacing;
- enforce the local non-collapse condition across the full pattern half-width, conservatively
  `max(|kappa|)*v_max < 1`, and separately test global offset-curve self-intersection;
- recompute finished ligament distances in mapped world geometry. On the inside of a curve,
  arc length contracts and cells crowd; on the outside it expands;
- use a continuous normal/frame through inflections and path reversal. Test reversal
  invariance and prevent orientation flips;
- bound curve tessellation error using curvature/sagitta, and include that bound in spacing
  and edge-clearance decisions;
- handle endpoints, closed-path phase/seam closure, short residual spans, high-curvature
  regions, cusps, and nearby nonadjacent portions of the path explicitly;
- reject nonplanar or non-developable input paths for a flat-cut workflow unless a separate
  flattening model defines the mapping and distortion.

For a circular path of radius `rho`, use it as an analytic oracle: centerline length is
`rho*DeltaPhi`, an offset radius is `rho +/- v`, and its length is
`(rho +/- v)*DeltaPhi`. Tests must catch code that gives equal inner, center, and outer arc
lengths.

Folding along a curved crease creates geometric frustration: the adjacent panels generally
cannot remain two rigid planar faces joined by a uniform dihedral angle. Curvature, torsion,
out-of-plane buckling, and membrane strain can result. Do not use a straight-bend K-factor,
bend allowance, or constant-angle assumption to promise the folded 3-D shape. A target
curved-fold shape or strength claim needs nonlinear shell/plastic analysis and physical
prototype validation with stated boundary conditions.

## Fusion and data-integrity checks

- Confirm the selected entity is straight and planar wherever `local_frame` assumes a
  `Line3D`. Do not accept arc/spline support that reads only start/end points.
- Thickness fallback `volume / largest planar face area` is valid only for a constant-
  thickness plate with an appropriate face. Make fallback/uncertainty visible; do not present
  it as exact for arbitrary bodies.
- Material-name substring matching is a convenience for UI seeding only. Ambiguous numeric
  grades (for example `304`) must not silently determine a family without contextual proof.
- Auto-derived values and user overrides must survive preview, execute, edit, undo/redo,
  serialization, version migration, and material-change rebuilds without changing meaning.
- Cached/linearized pitch models must be verified over the full accepted domain. If the
  approximation can change slot count or violate a ligament boundary, use the exact solver
  at validation and final build.
- Preview geometry must be disposable and final geometry must be deterministic. Check profile
  filtering does not accidentally cut unrelated sketch profiles or omit valid small profiles.
- Reject NaN, infinity, negative/zero physical values, nonfinite points, and unreasonable
  counts before creating Fusion entities. A one-cell pattern has no inter-cell ligament; do
  not display infinity as a physical clearance.

## Required verification for calculation changes

Run the repository suite:

```text
py -m unittest discover -s tests -p "test_*.py" -v
```

Then require focused tests appropriate to the change. Calculation-critical changes normally
need:

- exact or independently derived examples, not expected values copied from the function
  under test;
- boundary tests immediately below/at/above each inequality and tolerance;
- invalid, zero, negative, nonfinite, extremely small, and extremely large inputs;
- scale, translation, rotation, mirror, and path-reversal invariance where applicable;
- all pattern styles and both alternating orientations;
- non-neighbor and endpoint clearance cases;
- randomized/property tests comparing the optimized solver with a slower independent oracle;
- manufactured-tolerance sweeps using worst-case cut width, position, taper, fillet, and
  stock thickness;
- DXF round-trip checks for units, closed loops, dimensions, and intended kerf semantics;
- curved-path line-limit and circular-oracle tests before any curved path is supported;
- regression tests for every reported calculation bug.

Do not replace physical validation with unit tests. For a new material/topology/thickness
claim, require representative coupons cut by the intended process from the intended stock,
in adverse grain directions and tolerance conditions. Record actual thickness and kerf,
bending fixture and lever arm, peak force, loaded and unloaded angles, springback, visible
and penetrant-inspected cracking as appropriate, residual strength/stiffness, and cycles if
the feature will flex repeatedly. Define acceptance criteria before testing. Safety-critical
applications require review by a qualified engineer and the governing code/standard.

## Finding severity

- **P0:** a default or claim can plausibly direct users into an immediate severe hazard, or a
  calculation is presented as safety certification without required engineering evidence.
- **P1:** wrong units/dimensions, invalid profiles, overstated ligament, incorrect material
  mapping, stale rebuilds, unsafe extrapolation, or a defect likely to produce a bad cut,
  fracture, or unusable part for accepted inputs.
- **P2:** a real but narrower validation, tolerance, compatibility, performance, or
  maintainability defect that should be fixed but does not usually invalidate the generated
  part.

Do not raise a finding merely because a heuristic exists. Raise it when the heuristic is
misrepresented, silently applied outside its evidence, defeats an explicit guardrail, or can
produce incorrect geometry/results. When no defect is found, say so and state any untested
Fusion/manual/physical validation that remains.

## Research baseline (revalidate when used)

Checked 2026-07-13. These sources establish review principles and limited test data; none is
a universal design table.

- [ISO 7438:2020 — Metallic materials, bend test](https://www.iso.org/standard/72187.html):
  standardized evaluation of plastic deformation in bending; product-specific requirements
  still govern.
- [ASTM E290-22 — Bend testing for ductility](https://store.astm.org/e0290-22.html):
  guided, semi-guided, free, and bend-and-flatten test configurations and crack evaluation.
- [ASTM E466-21 — Force-controlled axial fatigue testing](https://store.astm.org/e0466-21.html)
  and [ISO 12107:2012 — fatigue test planning/statistics](https://www.iso.org/standard/50242.html):
  fatigue evidence must preserve material, geometry, surface, loading, and statistical scope.
- [Autodesk Fusion sheet-metal rule reference](https://help.autodesk.com/cloudhelp/ENU/Fusion-Sheet-Metal/files/SM-RULES-REF.htm)
  and [Autodesk Inventor unfold equations](https://help.autodesk.com/cloudhelp/2024/ENU/Inventor-Help/files/GUID-7B2525E4-8191-46F2-8CC3-FF422114EAE5.htm):
  K-factor definition, bend allowance equation, angle convention, units, and bend tables.
- [Aluminum Association — Designing Aluminum Structures FAQ](https://www.aluminum.org/sites/default/files/2021-09/DesigningAluminumStructuresFAQs20201012_0.pdf):
  minimum radius depends on alloy, temper, thickness, angle, and grain orientation.
- [SSAB — Bending Hardox wear plate](https://www.ssab.com/-/media/files/en/hardox/bending-hardox-wear-plate-105-en-v3-2024.pdf):
  strength, rolling direction, tooling, springback, cut-edge condition, and trial bends matter.
- [Outokumpu — Forming stainless steel](https://www.outokumpu.com/en/expertise/stainless-basics/forming):
  grade groups have different radius ratios/springback and cut-edge quality affects cracking.
- [TIMET — Titanium design and fabrication handbook](https://www.timet.com/assets/local/documents/technicalmanuals/DesignandFabrication.pdf):
  grade- and thickness-specific bend radii, temperature effects, and substantial springback.
- [Copper Development Association — Formability](https://www.copper.org/applications/industrial/DesignGuide/selection/form02.html):
  use alloy/temper/direction-specific `R/t`; tensile elongation alone does not establish
  bendability.
- [Haynes International — Cold working nickel alloys](https://haynesintl.com/en/alloys/welding-and-fabrication/cold-working/):
  thickness- and alloy-dependent forming guidance and possible intermediate annealing.
- [SendCutSend — Wave bending sheet metal](https://sendcutsend.com/blog/wave-bending-sheet-metal/):
  practical starting heuristics, explicit strength/force tradeoff, thickness caution, and a
  recommendation to prototype. Treat it as vendor guidance, not a standard.
- [Nuryar, *Mechanics of Origami-Based Sheet Metal Bending*](https://escholarship.org/uc/item/6r68d3q8):
  experiments and models for specific material-discontinuity topologies and test conditions;
  fracture depends on topology, scale, and thickness.
- [Farsi and Arezoo, perforated-sheet V-die bending](https://doi.org/10.1590/S1678-58782011000100007):
  holes change both force and springback, complicating analytical prediction.
- [US 7,032,426 B2 — precision-folded slit sheet](https://patents.google.com/patent/US7032426B2/en):
  topology concepts such as oblique straps, curved ends, jog, and empirical material-specific
  design. Patent ratios are not universal validation.
- [Dias et al., *Geometric Mechanics of Curved Crease Origami*](https://doi.org/10.1103/PhysRevLett.109.114301):
  curved creases couple fold geometry to buckled curvature/torsion through geometric
  frustration; they are not straight hinges laid along an arc.
