/** Two-layer fabrication and assembly readiness tools. */

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";
import { logger } from "../logger.js";
import { formatKicadResult } from "./tool-response.js";

type CommandFunction = (command: string, params: Record<string, unknown>) => Promise<unknown>;

const fabLimits = z
  .object({
    minTrackWidthMm: z.number().positive().optional(),
    minClearanceMm: z.number().positive().optional(),
    minDrillMm: z.number().positive().optional(),
    minAnnularRingMm: z.number().positive().optional(),
    minCopperEdgeMm: z.number().positive().optional(),
  })
  .optional()
  .describe("Fabricator limits; conservative hobby-friendly defaults are used when omitted");

const readinessArgs = {
  boardPath: z.string().optional().describe("Board path; defaults to the currently loaded board"),
  assemblyMode: z
    .enum(["hand", "smt"])
    .optional()
    .describe("Hand assembly (default) or outsourced SMT assembly"),
  requirePartNumbers: z
    .boolean()
    .optional()
    .describe("Require MPN/supplier fields for SMT assembly (default true)"),
  handSolderMinPitchMm: z
    .number()
    .positive()
    .optional()
    .describe("Warn below this pad pitch in hand-assembly mode (default 0.65 mm)"),
  handSolderMinPadFeatureMm: z
    .number()
    .positive()
    .optional()
    .describe("Warn below this pad feature in hand-assembly mode (default 0.35 mm)"),
  fabLimits,
  checkPlacement: z.boolean().optional().describe("Check courtyards and board boundary"),
  courtyardMarginMm: z.number().nonnegative().optional(),
  runDrc: z.boolean().optional().describe("Run KiCad DRC (default true)"),
  reportPath: z.string().optional().describe("Optional DRC report path"),
  timeoutSec: z.number().positive().optional().describe("DRC timeout (default 600 seconds)"),
  blockOnWarnings: z
    .boolean()
    .optional()
    .describe("Treat readiness warnings as blockers for strict review"),
};

export function registerManufacturingTools(
  server: McpServer,
  callKicadScript: CommandFunction,
): void {
  logger.info("Registering manufacturing readiness tools");

  server.tool(
    "analyze_manufacturing_readiness",
    "Run a non-destructive two-layer fabrication/assembly preflight: stackup, outline, annotation, footprints, fab limits, courtyards, boundary, DRC, and hand-solder or SMT-specific checks.",
    readinessArgs,
    async (args) =>
      formatKicadResult(await callKicadScript("analyze_manufacturing_readiness", args), 2),
  );

  server.tool(
    "prepare_manufacturing_package",
    "Save and gate a two-layer PCB, then atomically generate Gerbers, Excellon drill/map, BOM, placement CSV, readiness report, assembly notes, SHA-256 manifest, and ZIP. Existing output is never overwritten.",
    {
      ...readinessArgs,
      outputDir: z
        .string()
        .optional()
        .describe("Unique output directory; defaults to a timestamped manufacturing folder"),
      schematicPath: z.string().optional().describe("Schematic used for the preferred BOM export"),
      gerberLayers: z
        .array(z.string())
        .optional()
        .describe("Gerber layers; defaults to two copper, masks, silks, and Edge.Cuts"),
      gerberPrecision: z.number().int().min(5).max(6).optional(),
      saveBeforeExport: z
        .boolean()
        .optional()
        .describe("Save the current board before invoking file-based exporters (default true)"),
      allowUnsafe: z
        .boolean()
        .optional()
        .describe(
          "Explicitly export despite blockers; manifest and notes record the unsafe override",
        ),
    },
    async (args) =>
      formatKicadResult(await callKicadScript("prepare_manufacturing_package", args), 2),
  );
}
