/**
 * Research-backed workflow text for high-quality circuit design agents.
 */

export const CIRCUIT_DESIGN_EXCELLENCE_WORKFLOW = `Circuit Design Excellence Workflow for KiCad MCP

Purpose:
Use KiCad MCP as a verified EDA workflow, not as a one-shot drawing tool. The schematic is the source of truth. The PCB is the synchronized physical view of that schematic. Never let schematic connectivity and PCB pad nets diverge.

Research basis:
- LLM-assisted EDA works best when the model has domain-specific context, retrieval, and task-specific prompts instead of generic free-form generation.
- Hardware/circuit-generation studies show that proper prompts and fine-grained checklists improve results, but complex designs still need tool-verified feedback loops.
- AI-native EDA research argues for multimodal circuit context: requirements, schematic/netlist, layout, rules, and verification artifacts must be considered together.
- Analog-design automation research treats testbench/simulation generation as a bottleneck; agents must either run a simulation or explicitly report that the simulation gate is missing.

Reference sources:
- SmartonAI / GPT for complex EDA software: https://arxiv.org/abs/2307.14740
- ChipNeMo domain-adapted LLMs for chip design: https://research.nvidia.com/publication/2023-10_chipnemo-domain-adapted-llms-chip-design
- AI-native EDA and Large Circuit Models: https://arxiv.org/abs/2403.07257
- Machine Learning for Electronic Design Automation survey: https://arxiv.org/abs/2102.03357
- LLMs for hierarchical hardware circuit/testbench generation: https://doi.org/10.1145/3742430
- AnalogTester LLM analog testbench generation: https://arxiv.org/abs/2507.09965
- PCBSchemaGen netlist/schematic generation: https://arxiv.org/abs/2602.00510

Non-negotiable rules:
1. Start from an explicit requirements contract: function, voltage/current limits, board size, layer count, package style, assembly method, supplier constraints, target cost, connectors, controls, enclosure, and manufacturing limits.
2. Use sourced components only. Record manufacturer/MPN, supplier SKU or URL, package, footprint, value, tolerance/rating, and substitution risk before committing the schematic.
3. Keep the schematic readable enough for a human review: left-to-right signal flow, power at top, ground at bottom, functional blocks, short local labels, visible junctions, and no decorative wire spaghetti.
4. Treat PCB layout as implementation of the schematic. After every schematic edit that changes components, footprints, or nets, run sync_schematic_to_board and then validate_schematic_pcb_sync.
5. Do not route or place a PCB that has no validated schematic netlist. Do not manually patch PCB pad nets to hide schematic errors.
6. Prefer measurable quality gates over claims. A design is not done until ERC, sync validation, DRC, BOM, fabrication exports, and known-risk notes are produced.

Required agent loop:
1. Requirements and constraints:
   - Write the requirements contract.
   - Identify missing assumptions and choose conservative defaults only when safe.
   - Define acceptance criteria before drawing.

2. Topology and calculations:
   - Select topology with a short rationale.
   - Calculate critical values: bias points, gain, filters, current draw, thermal margin, impedance-sensitive paths, and power ratings.
   - For analog/audio work, state expected signal levels, headroom, clipping mechanism, input/output impedance, and noise-sensitive nodes.

3. Component sourcing:
   - Query the configured component database or supplier integration before fixing values/footprints.
   - Prefer through-hole/DIP only when requested or manufacturability justifies it.
   - If an exact part is unavailable, choose a compatible substitute and record why it is electrically and mechanically safe.

4. Schematic implementation:
   - Create the schematic as functional blocks: input/protection, power, bias/reference, core circuit, controls, output, connectors, mounting/mechanical.
   - Annotate with annotate_schematic.
   - Run run_erc and fix errors before PCB sync.
   - Run polish_schematic_readability after connectivity is stable.
   - Export a schematic PDF/SVG for visual review.

5. Schematic-to-PCB sync:
   - Run sync_schematic_to_board.
   - Immediately run validate_schematic_pcb_sync.
   - If validate_schematic_pcb_sync is not inSync, stop layout work and fix the schematic/footprint mismatch first.

6. PCB placement:
   - Place connectors and controls from mechanical requirements first.
   - Keep functional blocks physically recognizable from the schematic.
   - Keep high-impedance/noise-sensitive analog nodes short and away from switching/current loops.
   - Keep decoupling capacitors close to their load pins.
   - Reserve board-edge access for jacks, power, switches, potentiometers, LEDs, and test points.

7. Routing and copper:
   - Set design rules before routing.
   - Route critical/noise-sensitive nets first.
   - Use route_pad_to_pad for named pad-to-pad routing and autoroute only after constraints exist.
   - Maintain return-path continuity. Use ground fills/zones where appropriate and avoid isolated copper.
   - For two-layer analog boards, keep a clean ground strategy more important than dense routing aesthetics.

8. Verification gates:
   - run_erc must pass or have explicitly justified warnings.
   - validate_schematic_pcb_sync must return inSync=true.
   - run_drc must pass or have explicitly justified, non-electrical/non-manufacturing exceptions.
   - generate_netlist or export_netlist should be archived for non-trivial designs.
   - For analog circuits, run or generate a SPICE/testbench when available. If not available, list the missing simulation as residual risk.

9. Manufacturing package:
   - Export BOM with supplier links and alternates.
   - Export Gerbers/drills, position files when useful, PDF/SVG review artifacts, and 3D model when requested.
   - Include a build note: polarity, IC orientation, calibration/trimmer setup, first-power checks, and expected voltages.

10. Final answer discipline:
   - Report the tools run and the pass/fail status of each gate.
   - State any assumptions, unverified items, and remaining risks.
   - Do not say the design is perfect. Say exactly which objective checks passed.`;
