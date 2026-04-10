# Placement And Routing Rulebook

This document captures the deterministic engineering rules now used by the KiCAD MCP server for auto-placement and constraint-first routing. The goal is not to imitate a black-box ML placer/router, but to translate the strongest recurring ideas from recent literature into transparent, controllable behavior.

## Placement Rules

1. Cluster by weighted connectivity, not raw net count.
   - High-speed and RF point-to-point links are weighted more heavily than global power and ground nets.
   - This keeps local signal loops tight without letting shared rails collapse the whole board into one giant cluster.

2. Keep connectors on edges.
   - High-speed and generic connectors prefer left/right edge breakout lanes.
   - Analog connectors bias toward the top edge.
   - Power and switching-power connectors bias toward the bottom edge.

3. Keep decoupling and support parts local to their anchor.
   - Decouplers are placed closest to the anchor inside each cluster.
   - This reduces loop area and preserves cleaner breakout channels for critical anchors.

4. Separate sensitive and noisy profiles.
   - RF and analog clusters are biased away from switching-power regions.
   - High-speed clusters stay edge-friendly so routing can reserve lower-conflict corridors early.

5. Apply local net-separation legalization after clustering.
   - Preserve the cluster structure, then shift movable core clusters to increase margin between analog/RF and noisy power-switching regions.
   - This approximates the margin-maximization idea from routability-driven placement without turning the placer into an opaque optimizer.

6. Recover safely with a deterministic fallback.
   - If a part cannot stay inside its preferred cluster band, it falls back to a predictable grid.

## Routing Rules

1. Route critical nets in this order:
   - intent priority
   - escape complexity
   - breakout pressure
   - local congestion

2. Reserve breakout channels early.
   - Nets connected to dense connectors, BGAs, and high-pin-count parts route before easy nets.

3. Apply explicit KiCad custom rules from a canonical constraint file.
   - Differential-pair skew always
   - Differential-pair gap and uncoupled length only when the endpoint geometry is actually eligible for coupled routing
   - High-speed via limits
   - RF via limits
   - Power minimum width
   - Edge clearance for RF/high-speed nets
   - Crosstalk guard spacing
   - Analog isolation
   - RF clearance corridors
   - Switching-net isolation

4. Synthesize power widths from physics when current is known.
   - `powerCurrentA`, `copperOz`, and `tempRiseC` feed IPC-2221-derived minimum width calculation.

5. Support explicit matched-length groups.
   - Differential pairs are auto-detected.
   - Wider bus groups such as DDR can be passed explicitly through `matchedLengthGroups`.

6. Heal residual support-net disconnects after routing.
   - If post-route DRC still reports same-net disconnects on `GROUND` or `POWER_DC`, the tuner first tries a same-layer bridge between the reported copper islands.
   - The bridge path is routed on an obstacle-aware orthogonal lane instead of a naive straight segment.
   - Only if same-layer bridging is not applicable does it fall back to zone-backed stitching vias.
   - This keeps the repair deterministic and avoids unsafe automatic vias on switching nodes.

7. Make full-pipeline post-tune self-healing by default.
   - `autoroute_cfha` now turns on zone refill and support-net healing automatically during the post-tune stage unless the caller explicitly overrides it.
   - This makes one-shot routing runs behave much closer to a real “finish and verify” automation flow.

8. Score matched-length groups, not just diff pairs.
   - QoR now tracks explicit `matchedLengthGroups` and flags groups whose observed skew exceeds their declared limit.
   - This keeps bus-level timing visible even when routing itself is deterministic and conservative.

9. Replace straight bus segments with deterministic post-route meanders when the skew gap is materially large.
   - `post_tune_routes` now attempts matched-length compensation on explicit non-diff-pair groups before support-net healing.
   - It only targets already-routed nets, only rewrites one orthogonal segment at a time, and skips tiny corrections below the configured compensation floor.
   - Endpoint footprints are excluded from obstacle collection so the planner can legally replace pad-to-pad segments instead of falsely blocking itself.
   - The goal is conservative bus equalization, not aggressive SI-perfect serpentine synthesis.

10. Infer DDR-style matched-length groups automatically, but keep their skew defaults real.
   - `extract_routing_intents` now infers `bus_auto` groups for interface-aware stems such as `DQ`, `ADDR`, `BA`, and `BG`.
   - Auto-inferred groups inherit the active profile/interface skew budget, so a DDR4 bus defaults to `0.08 mm` instead of an accidental zero-or-loose fallback.
   - Explicit `maxSkewMm: 0.0` is preserved as an exact-match request; it is no longer silently widened by numeric `or` fallbacks in post-tune or QoR verification.

11. Synthesize a deterministic ground reference zone when high-speed nets have no plane.
   - `post_tune_routes` can now create a board-inset `GROUND` zone automatically before refill and verification.
   - On multilayer boards it prefers the first inner copper layer; on 2-layer boards it prefers the lower-pressure side, biased toward `B.Cu`.
   - The automation only runs when high-speed nets exist, no ground zone exists yet, and a ground net is actually present on the board.
   - This is intended to restore return-path continuity, not to invent power intent where no ground net exists.

12. Plan the reference plane before critical routing, not only after routing.
   - `generate_routing_constraints` now emits `referencePlanning`, including `groundNet`, `preferredZoneLayer`, `preferredSignalLayer`, `splitRiskLayers`, and whether an automatic zone should be synthesized at all.
   - `autoroute_cfha` runs a `preRouteReference` stage before `route_critical_nets` so the preferred signal layer and any missing ground reference zone are established before high-speed routing decisions are made.
   - The critical router now falls back to `referencePlanning.preferredSignalLayer` when the caller does not force `criticalLayer` explicitly.
   - This couples placement-era plane continuity hints to routing-time layer choice and avoids creating the plane only after the important traces are already committed.

13. Give ground-coupled high-speed connectors their own quiet edge corridors during placement.
   - `sync_schematic_to_board` now tags clusters with a `referenceProfile` so connectors carrying both `GROUND` and high-speed or RF nets are recognized as return-path-sensitive.
   - Those connectors are assigned first to the most central side-edge slots, get slightly deeper inward breakout corridors, and are separated more aggressively from power and switching clusters.
   - The goal is to preserve a cleaner future reference corridor for the breakout region instead of treating every side-edge connector as equally interchangeable.

14. Choose the reference ground domain locally, not by global net name folklore.
   - `generate_routing_constraints` now selects `referencePlanning.groundNet` by shared endpoint locality first: the preferred ground net is the one that overlaps most strongly with the high-speed or RF nets' component refs and pad neighborhood.
   - Existing zones are now evaluated per selected ground domain. A pre-existing `GND` plane no longer suppresses automatic `AGND` reference synthesis if the local interface is tied to `AGND`.
   - When another ground domain already owns a useful plane layer, that layer can still be reused as the preferred target for the newly synthesized local reference zone.
   - This is meant to avoid broken return paths across split or mismatched ground domains, especially near connectors and mixed-signal boundaries.

15. Partition quiet and noisy ground domains already during connector placement.
   - `sync_schematic_to_board` now records both `referenceProfile` and `referenceDomain` for placement clusters.
   - Side-edge connectors tied to quiet domains such as `AGND` or chassis-earth are prioritized for the central breakout corridor, while `PGND`-coupled connectors are pushed toward more peripheral side slots.
   - The breakout corridor depth is also domain-aware: quiet ground domains get the deepest inward corridor, noisy domains get the weakest preference.
   - Cluster legalization now increases spacing when quiet-reference clusters drift too close to noisy ground-domain or switching-power clusters.

16. If the board already has zones, align the connector edge with the matching reference plane.
   - `sync_schematic_to_board` now inspects existing ground-domain zones and derives a left/right side affinity from their geometry.
   - Connectors with `AGND`, `GND`, or `PGND` continuity are steered toward the edge that preserves the strongest local reference-plane area instead of alternating blindly.
   - This does not force placement when the zone is balanced; it only biases edge choice when one side clearly dominates.
   - The resulting cluster now records the preferred edge and whether it actually aligned with the existing zone geometry.

17. Carry the same reference-topology cue into critical routing order.
   - `generate_routing_constraints` now emits `referencePlanning.preferredEntryEdge`, `entryEdgeBias`, `referenceContinuityScore`, and `topologyCueSource`.
   - If the selected ground domain already has usable zone geometry, that cue comes from zone affinity; otherwise it falls back to the combined centroid of the high-speed endpoints and the selected local ground domain.
   - `route_critical_nets` now inserts `reference_alignment` between breakout pressure and congestion so edge-near nets that match the selected reference side reserve that corridor earlier.
   - The routing result now exposes an `ordering` array so agents can inspect the exact escape/breakout/reference/congestion scores that drove the deterministic route order.

18. Score the preferred signal layer with reference continuity, split risk, and real board pressure.
   - `analyze_board_routing_context` now emits `trackPressureByLayer` and `edgePressureByLayer` in its summary.
   - `generate_routing_constraints` uses those pressure summaries together with `preferredEntryEdge` and `referenceContinuityScore` to rank candidate signal layers instead of always defaulting to `F.Cu`.
   - The chosen layer still prefers adjacency to the selected reference plane and avoids split-risk layers first, but when those are equal it now favors the layer with the cleaner breakout corridor on the selected reference side.
   - `referencePlanning.signalLayerCandidates` exposes the full candidate ranking so agents can inspect why `preferredSignalLayer` was chosen.

19. Allow actual critical routing to override the global layer per net.
   - `route_critical_nets` now computes a `selectedLayer` for each high-speed or RF net instead of blindly applying one global `criticalLayer`.
   - The per-net decision uses the net's own left/right/center position, the board's `edgePressureByLayer`, and the global `signalLayerCandidates` ranking from `referencePlanning`.
   - This means a left-edge breakout can stay on the globally preferred layer while a right-edge breakout on the same board can intentionally switch to a cleaner alternative layer.
   - The `ordering` telemetry and routed-net records now expose the chosen layer and its source so agents can audit real routing behavior instead of just the planning artifact.

20. Lock differential pairs to one shared signal layer and penalize avoidable transitions.
   - `route_critical_nets` now resolves one common `selectedLayer` per `HS_DIFF` pair instead of letting the positive and negative nets drift onto different layers.
   - The shared decision reuses the same `signalLayerCandidates` and reference-side scoring, but it evaluates the combined pair geometry and reports `selectedLayerSource = diff_pair_locked`.
   - Candidate layers now also carry an endpoint-layer mismatch penalty so the router resists gratuitous outer-layer flips and especially unnecessary internal-layer detours when both pads already live on another layer.
   - The same locked layer is reused during reroute passes, so a failed diff-pair retry no longer silently degenerates into two unrelated single-net layer choices.

21. Make the diff-pair layer lock backend-safe and budget-aware.
   - Candidate telemetry now exposes `estimatedViaCountTotal` and `estimatedViaCountPerNet` so agents can see how many synchronized transitions a chosen pair layer would require.
   - The diff-pair selector now prefers zero-transition candidates first and records `transitionPolicy = stay_on_endpoint_layer` when it deliberately sacrifices a lower-pressure alternative to keep the pair on an endpoint-compatible layer.
   - If no zero-transition layer exists, the decision is still annotated with whether the required paired transitions would exceed the configured high-speed via budget.
   - When the selected layer stays within the configured pair via budget, the diff-pair router now synthesizes synchronized start/end paired transitions instead of silently degrading the pair into an unsafe off-layer route.

22. Emit synchronized paired vias for diff-pair layer changes.
   - `route_differential_pair` now receives the real endpoint pad geometry and site layers, not just midpoint hints.
   - If the selected pair layer differs from the endpoint layer, it routes short same-layer access legs, drops one via per polarity at the start and/or end site, then continues the coupled segment on the target layer.
   - The transition is still deterministic: paired via sites are chosen from a bounded candidate set scored by obstacle hits and total Manhattan detour, and the final report exposes `startTransition`, `endTransition`, and total pair `viaCount`.
   - This keeps the layer planner and the physical router aligned: a pair layer is only considered practically useful when the backend can now instantiate the synchronized transitions it implies.

## Research Mapping

- Placement and routing should be coupled through routability and congestion, not optimized independently.
  - Ruoyu Cheng and Junchi Yan, "On Joint Learning for Solving Placement and Routing in Chip Design", arXiv:2111.00234
  - Junchi Yan et al., "Towards Machine Learning for Placement and Routing in Chip Design: a Methodological Overview", arXiv:2202.13564

- Connector breakout pressure and congestion should influence routing order.
  - Classic congestion-driven ordering and negotiated-congestion ideas remain useful for deterministic routers.
  - Haiyun Li et al., "FanoutNet: A Neuralized PCB Fanout Automation Method Using Deep Reinforcement Learning", DOI: 10.1609/aaai.v37i7.26030
  - Ting-Chou Lin et al., "A Unified Printed Circuit Board Routing Algorithm With Complicated Constraints and Differential Pairs", DOI: 10.1145/3394885.3431568
  - Weijie Fang et al., "Obstacle-Aware Length-Matching Routing for Any-Direction Traces in Printed Circuit Board", DOI: 10.48550/arXiv.2407.19195

- Net-separation between sensitive/noisy regions materially improves downstream routability, via count, and DRV rate.
  - Chung-Kuan Cheng et al., "Net Separation-Oriented Printed Circuit Board Placement via Margin Maximization", DOI: 10.1109/ASP-DAC52403.2022.9712480

- Rule synthesis should come from measurable signal-integrity constraints, not fixed folklore alone.
  - Alexandre Plot, Benoit Goral, Philippe Besnier, "Machine Learning Techniques for Defining Routing Rules for PCB Design", DOI: 10.1109/SPI57109.2023.10145545

- Open, modular EDA flows work best when analysis, rule generation, placement, routing, and verification stay separate but composable.
  - Tutu Ajayi et al., "Toward an Open-Source Digital Flow", DOI: 10.1145/3316781.3326334

## MCP Surface

The relevant MCP entrypoints are:

- `sync_schematic_to_board`
- `generate_routing_constraints`
- `generate_kicad_dru`
- `route_critical_nets`
- `post_tune_routes`
- `autoroute`
- `autoroute_cfha`

The placement response now exposes:

- `auto_place_strategy`
- `auto_place_clusters`
- `auto_place_rules`

The routing constraint artifact now exposes:

- `compiledRules`
- `policy`
- `referencePlanning`
- `matchedLengthGroups`

The post-route tuner now exposes:

- `matchedLengthTuning`
- `matchedLengthTuning.tunedNets`
- `matchedLengthTuning.skipped`

The full autorouter now also exposes:

- `stages.preRouteReference`
- `stages.preRouteReference.referencePlanning`
- `stages.preRouteReference.referenceZone`
