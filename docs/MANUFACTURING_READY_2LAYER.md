# Production-Ready Two-Layer PCB Workflow

This workflow is the recommended path from a schematic to a fabrication package
for a two-copper-layer board. It favors conservative, inspectable decisions over
an opaque one-shot layout and defaults to hand assembly.

No automated flow can certify that a circuit is electrically fit for its
purpose. The readiness gate certifies the checks it can measure: stackup,
outline, footprints, references, fabrication limits, courtyard/boundary
clearance, KiCad DRC, and assembly metadata. Always review polarity, pin 1,
connector orientation, current/thermal margins, and the final Gerber render.

## Recommended Sequence

1. Create or open the project and define a closed `Edge.Cuts` outline. New
   projects default to 100 mm x 100 mm and exactly `F.Cu` / `B.Cu`; an explicit
   template stackup is preserved unless the caller overrides it.
2. Finish annotation, footprint assignment, ERC, and
   `sync_schematic_to_board`. On an empty board, sync uses connectivity, part
   roles, signal domains, connector edge slots, local decoupling, and reserved
   breakout corridors for its initial placement.
3. Preview `suggest_placement` with `apply: false`, `starts: 3` or more, and
   `rotation_passes: 2` or more. Lock connectors, mounting-constrained parts,
   antennas, and controls. Inspect the selected candidate's boundary,
   courtyard, and pad-level HPWL scores, then repeat the same call with
   `apply: true`.
4. Run `autoroute_cfha` with `attempts: 3` to `5` for a dense design. It
   classifies net intent, compiles KiCad rules, protects critical routes and
   return paths, runs best-of-N Freerouting for bulk nets, tunes matched-length
   groups, and finishes with DRC/QoR verification.
5. Resolve every DRC error and review every warning. A high QoR score is useful
   comparison evidence, not an electrical sign-off.
6. Run `analyze_manufacturing_readiness` with the intended assembly mode and
   the actual limits published by the chosen fabricator.
7. Run `prepare_manufacturing_package` only after readiness reports
   `ready: true`. Leave `allowUnsafe` false for orderable output.

Example agent request:

```text
Optimize the current two-layer PCB placement with five deterministic starts.
Keep J1, J2, the antenna and mounting holes fixed. Apply the winning placement,
run CFHA with five Freerouting attempts, resolve DRC blockers, then analyze
manufacturing readiness in hand-assembly mode. Generate the manufacturing
package only if the board is ready; never use allowUnsafe.
```

## Conservative Default Fabrication Profile

| Check                            | Default |
| -------------------------------- | ------: |
| Minimum track width              | 0.20 mm |
| Minimum clearance                | 0.20 mm |
| Minimum finished drill           | 0.30 mm |
| Minimum annular ring             | 0.15 mm |
| Minimum copper-to-edge clearance | 0.25 mm |

These are portable hobby-board defaults, not a substitute for a fabricator's
capability table. Pass `fabLimits` to make the gate match the selected process;
the board rules and observed copper must both meet that profile.

## Hand Assembly and SMT Assembly

`assemblyMode: "hand"` is the default. Fine-pitch SMD parts below the configured
comfortable pitch or pad-feature thresholds are warnings so a mixed THT/SMD
hobby board can still pass after review.

`assemblyMode: "smt"` additionally requires a supplier or manufacturer part
number for each BOM item by default. Accepted fields include LCSC/JLCPCB part
numbers and common MPN field names. Use `requirePartNumbers: false` only when
the assembler has a separately reviewed mapping.

## Package Contents

The package command stages all files, creates and checks the archive, then
publishes a new output directory and sibling ZIP. Existing output is never
overwritten, and a failed export or archive build is rolled back.

```text
<outputDir>/
  ASSEMBLY_NOTES.txt
  manifest.json
  fabrication/
    gerbers/
    drill/
  assembly/
    <board>-bom.csv
    <board>-positions.csv
  reports/
    manufacturing-readiness.json
    <optional DRC report>
<outputDir>.zip
```

`manifest.json` records the profile, assembly mode, readiness summary, unsafe
override state, file sizes, and SHA-256 digest of every generated payload file.

## Release Checklist

- Board is saved and has exactly two copper layers.
- `Edge.Cuts` is closed and non-zero.
- Every physical footprint has a unique reference and library identifier.
- Courtyards do not overlap and no footprint crosses the board boundary.
- Critical connectors, polarity, pin 1, antenna keepouts, and DNP choices were
  visually reviewed.
- Track, clearance, drill, annular-ring, and copper-edge rules match the actual
  fabricator.
- KiCad DRC has zero errors; all warnings have an explicit disposition.
- Gerbers and drill files were rendered in a viewer before upload.
- BOM and placement CSV agree with the chosen hand/SMT assembly plan.
- The ZIP's SHA-256 manifest was retained with the order revision.

See also [Placement and Routing Rulebook](PLACEMENT_ROUTING_RULEBOOK.md) for the
algorithms and telemetry behind placement, routing, reference-plane planning,
and QoR scoring.
