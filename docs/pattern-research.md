# Research: bend-relief patterns in metal — validation and sizing rules

Verified 2026-07-11. Every claim below was checked against the primary source
(quotes fetched directly, thesis read from the PDF). Sources at the bottom.

## Do the candidate patterns work in metal?

| Pattern | Validated in metal? | Evidence |
|---|---|---|
| Wave (current) | Yes — field-proven | SendCutSend wave-bending guide [1]; curved profiles fracture-safe at all tested kerfs in AA-6061-O FEA [3] |
| Crescent / arc slits | Yes — strongest literature support | US patent 7,032,426 (Industrial Origami): slits "preferably arcuate with convex side facing the bend line"; commercial use in steel, aluminum, titanium [4]. Large-radius curved cuts never fractured at any tested kerf or thickness [3] |
| Dogbone slots | Yes — quantified | Enlarged circular end openings cut peak Von Mises stress 22.1% vs the same slot without them [3]; patent teaches "enlarged end openings … resist micro-crack propagation" [4] |
| Staggered / offset slot rows | Yes, with a caveat | Patent gives the offset (jog) rule and validates slit rows in metal [4]; SendCutSend notes straight dashed perforations distribute stress worse than curved cuts [1] — usable, but the crack-prone choice in hard alloys |
| Square meander | Indirect only | No direct metal source found. Its corners are small-radius features, which the FEA identifies as the fracture driver [3] — generous corner fillets are mandatory, treat like a slot pattern |
| Honeycomb / lattice openings | NO metal validation found | Lattice living-hinge literature is plywood/acrylic [5]. The one off-line opening pattern in the FEA (MD-10) was the WORST performer (+77.3% peak stress) [3]. Decorative use only; do not promote as a working hinge |

## Dimensional rules (t = material thickness)

| Dimension | Rule | Source |
|---|---|---|
| Kerf (slot width), curved patterns (wave, crescent, serpentine) | ≥ 0.2 t is fracture-safe; SendCutSend uses ~0.5–0.7 t in practice (worked examples: 0.60 t aluminum, 0.695 t steel) and 1.0 t for wave cutouts | [1][2][3] |
| Kerf, dogbone slots | ≥ 0.7 t (safe scale for t ≤ 2.3 mm in 6061-O) | [3] |
| Kerf, plain straight slots | ≥ 1 t practical (SendCutSend wave guidance); FEA worst case demands 2 t in 6061-O below 2.3 mm | [1][3] |
| Ligament (tab) between cuts | ≥ 1 t minimum (both SendCutSend guides); preferred band 0.7–2.5 t (patent), 1–1.5 t for strength (SendCutSend tolerances guide gives 0.5 t as the absolute laser-cut floor) | [1][2][4][6] |
| Row offset (jog) from bend line, staggered rows | ≤ 1.0 t, preferred ≤ 0.5 t (≈ 0.3 t in the preferred embodiment) | [4] |
| Dogbone end-hole | "enlarged" relative to slit — no ratio published; 2–3 x kerf diameter is the conventional interpretation | [4] |
| Crescent orientation | Convex side toward the bend line, so ligaments widen away from their midpoint | [4] |
| Relief depth past the bend zone | t + bend radius + 0.5 mm | [7] |
| Max thickness for hand-bend relief patterns | ~3 mm (0.187 in): SendCutSend says wave bending "gets tricky" above this; FEA predicts fracture at 3.2 mm for straight-slot patterns | [1][3] |
| General trends | Wider kerf monotonically reduces fracture risk; thicker sheet raises it for every pattern; more material removed = less bending force (29–59% reduction measured) and less springback | [3][8] |

## Current plugin rules — verdict

- gap = 0.6 t (aluminum) / 0.7 t (steel, stainless, titanium): CONFIRMED for the
  wave and other curved patterns (matches SendCutSend's hand-bend worked examples
  exactly; far above the 0.2 t fracture floor for curved cuts). NOT sufficient for
  plain straight slots — those want ≥ 1 t.
- tab = 1 t: CONFIRMED by every source that states a number. It is the minimum,
  not a conservative pick — the strength-preferred band starts here.
- fillet = 0.3 x gap: no source states a fillet ratio, but the FEA's core finding
  (small curvature radius drives fracture) supports maximizing it. Keep.
- Applicability ceiling: add a warning above ~3 mm thickness — both the
  manufacturer guide and the FEA agree reliability drops there. The current
  dialog accepts any thickness silently.

## Sources

1. SendCutSend, "Wave bending sheet metal" — sendcutsend.com/blog/wave-bending-sheet-metal/
2. SendCutSend, "Hand bend laser cut metal" — sendcutsend.com/blog/hand-bend-laser-cut-metal/
3. Ali Mehari, *Origami-based sheet metal bending* (PhD thesis, FEA + experiments,
   AA-6061-O at 1.6/2.3/3.2 mm; wiping-die config) — escholarship.org qt6r68d3q8.
   Key tables: BF reduction 29.5–59% (Table 3.1), peak stress by pattern
   (Table 3.3), fracture scale limits (§7.6).
4. US Patent 7,032,426 "Techniques for designing and manufacturing precision-folded,
   high strength, fatigue-resistant structures" (Industrial Origami) —
   patents.google.com/patent/US7032426B2
5. Missouri S&T, living-hinge study (plywood; explicitly not metal) — scholarsmine.mst.edu
6. SendCutSend, "Basic tolerances and cut feature relationships" —
   sendcutsend.com/blog/basic-tolerances-and-cut-feature-relationships/
7. SendCutSend, "Guide to designing bend reliefs" —
   sendcutsend.com/blog/guide-to-designing-bend-reliefs/
8. "Bending force and spring-back in V-die-bending of perforated sheet-metal
   components" (low-carbon steel, experimental) — researchgate.net/262448085
   (abstract-level check only)
