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

5. Recover safely with a deterministic fallback.
   - If a part cannot stay inside its preferred cluster band, it falls back to a predictable grid.

## Routing Rules

1. Route critical nets in this order:
   - intent priority
   - escape complexity
   - local congestion

2. Reserve breakout channels early.
   - Nets connected to dense connectors, BGAs, and high-pin-count parts route before easy nets.

3. Apply explicit KiCad custom rules from a canonical constraint file.
   - Differential-pair gap, skew, and uncoupled length
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

## Research Mapping

- Placement and routing should be coupled through routability and congestion, not optimized independently.
  - Ruoyu Cheng and Junchi Yan, "On Joint Learning for Solving Placement and Routing in Chip Design", arXiv:2111.00234
  - Junchi Yan et al., "Towards Machine Learning for Placement and Routing in Chip Design: a Methodological Overview", arXiv:2202.13564

- Connector breakout pressure and congestion should influence routing order.
  - Classic congestion-driven ordering and negotiated-congestion ideas remain useful for deterministic routers.

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
- `autoroute`
- `autoroute_cfha`

The placement response now exposes:

- `auto_place_strategy`
- `auto_place_clusters`
- `auto_place_rules`

The routing constraint artifact now exposes:

- `compiledRules`
- `policy`
- `matchedLengthGroups`
