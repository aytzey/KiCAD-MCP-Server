# Schematic Readability Rules

This file captures the KiCad-aligned readability rules that the MCP schematic
harness now enforces.

## Source

Primary source: KiCad official schematic editor manual

- https://docs.kicad.org/8.0/en/eeschema/eeschema.html

Relevant guidance from the manual, paraphrased into MCP rules:

1. Symbols and wires should be placed on the recommended 50 mil / 1.27 mm grid.
2. Only wire ends create connections; wire crossings do not connect unless a junction is added.
3. Power and ground nets should use power symbols.
4. Pins that are intentionally unused should be marked with no-connect flags.
5. Visible symbol fields should remain outside crowded symbol bodies so the schematic stays readable.

## MCP Enforcement

The MCP harness checks for:

- overlapping symbols, labels, and duplicate wire segments
- wires crossing through symbol bodies
- visible fields placed inside symbol bodies
- off-grid symbol and wire endpoint placement

Mutations that introduce new violations are reverted automatically so the
calling agent must retry with a cleaner placement or routing strategy.
