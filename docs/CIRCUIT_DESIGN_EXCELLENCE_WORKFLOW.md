# Circuit Design Excellence Workflow

This workflow is the operating rulebook for Claude, Codex, or any MCP client using KiCad MCP for real circuit/PCB work. It is exposed as:

- MCP prompt: `circuit_design_excellence_workflow`
- MCP resource: `kicad://workflow/circuit-design-excellence`

## Why This Exists

Recent EDA/LLM research is consistent on one point: an LLM should not be trusted as a one-shot circuit generator. Better results come from domain context, structured prompts, tool feedback, and explicit verification gates.

Key evidence:

- SmartonAI showed that LLM task planning can simplify KiCad-style EDA interaction, but it still relies on executing concrete subtasks in EDA software.
- ChipNeMo showed domain-adapted retrieval, pretraining, and instruction tuning improve chip-design tasks over generic LLM usage.
- Large Circuit Models research argues that circuit agents need multimodal context: specifications, netlists, schematic structure, and physical layout.
- Hardware-generation evaluations show that proper prompting and fine-grained checklists help, but complex circuits still fail without verification loops.
- AnalogTester highlights that analog automation needs generated testbenches/simulation plans, not just schematic capture.
- PCBSchemaGen is early evidence that LLMs can emit KiCad-oriented schematic/netlist artifacts, but its own framing is automation through structured workflows.

References:

- SmartonAI / GPT for complex EDA software: https://arxiv.org/abs/2307.14740
- ChipNeMo: https://research.nvidia.com/publication/2023-10_chipnemo-domain-adapted-llms-chip-design
- Large Circuit Models / AI-native EDA: https://arxiv.org/abs/2403.07257
- Machine Learning for EDA survey: https://arxiv.org/abs/2102.03357
- Hierarchical hardware circuit and testbench generation: https://doi.org/10.1145/3742430
- AnalogTester: https://arxiv.org/abs/2507.09965
- PCBSchemaGen: https://arxiv.org/abs/2602.00510

## Required Agent Behavior

The schematic is the source of truth. The PCB is the synchronized physical implementation of that schematic. Any agent that edits a board must keep this invariant true:

```
schematic netlist == PCB footprint/pad net assignment
```

After every schematic edit that affects symbols, footprints, or nets, run:

```
sync_schematic_to_board
validate_schematic_pcb_sync
```

If `validate_schematic_pcb_sync` does not return `inSync=true`, stop layout work and fix the schematic/footprint mismatch first.

## Design Gates

Use this order for fabrication-quality work:

1. Requirements contract: function, voltages, current, board size, layer count, package style, supplier, enclosure, and manufacturing limits.
2. Topology decision: topology rationale, critical calculations, power budget, expected signal levels, and failure modes.
3. Component sourcing: supplier SKU/link, manufacturer/MPN, value, tolerance/rating, package, footprint, and substitute risk.
4. Schematic implementation: functional blocks, readable flow, short labels, junctions visible, power/ground conventions consistent.
5. ERC gate: `annotate_schematic`, then `run_erc`; fix real errors before PCB sync.
6. Readability gate: `polish_schematic_readability` once connectivity is stable.
7. Sync gate: `sync_schematic_to_board`, then `validate_schematic_pcb_sync`.
8. Placement gate: connectors/mechanics first, then functional blocks, then noise/current-loop separation.
9. Routing gate: set design rules, route critical nets first, preserve return paths, use ground strategy appropriate to layer count.
10. Final verification: `run_erc`, `validate_schematic_pcb_sync`, `run_drc`, BOM/export checks, and explicit residual-risk notes.

## Final Output Standard

The agent must report objective pass/fail results, not subjective claims. A final answer should include:

- Tools run and gate status.
- BOM/source status and any missing links.
- ERC, DRC, and schematic/PCB sync result.
- Simulation/testbench result, or a clear note that analog simulation was not run.
- Remaining assumptions and risks.

Do not say a design is "perfect." Say which measurable checks passed and what remains unverified.
