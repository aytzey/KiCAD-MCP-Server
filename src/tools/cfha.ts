/** Constraint-first hybrid autorouting (CFHA) tools. */

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";
import { formatKicadResult } from "./tool-response.js";

const matchedLengthGroup = z.object({
  nets: z.array(z.string()),
  maxSkewMm: z.number().positive().optional(),
  type: z.string().optional(),
});

export const routingOrchestrationArgs = {
  boardPath: z.string().optional().describe("Path to .kicad_pcb (default: current board)"),
  strategy: z.enum(["hybrid", "critical_only", "analysis_only"]).optional(),
  seed: z.number().int().optional().describe("Deterministic routing seed"),
  timeBudgetSec: z.number().positive().optional(),
  criticalClasses: z.array(z.string()).optional(),
  placementRoutingCorridors: z
    .array(z.record(z.any()))
    .optional()
    .describe("Breakout corridor reservations returned by sync_schematic_to_board"),
  powerCurrentA: z.number().positive().optional(),
  copperOz: z.number().positive().optional(),
  tempRiseC: z.number().positive().optional(),
  maxLengthMm: z.number().positive().optional(),
  matchedLengthGroups: z.array(matchedLengthGroup).optional(),
  inferMatchedLengthGroups: z.boolean().optional(),
  autoMatchedLengthMaxSkewMm: z.number().positive().optional(),
  autoMatchedLengthMinGroupSize: z.number().int().min(2).optional(),
  autoMatchedLengthMaxGroupSize: z.number().int().min(2).optional(),
  excludeFromFreeRouting: z.array(z.string()).optional(),
  profiles: z.array(z.string()).optional(),
  interfaces: z.array(z.string()).optional(),
  qorWeights: z
    .object({
      length: z.number().optional(),
      vias: z.number().optional(),
      skew: z.number().optional(),
      uncoupled: z.number().optional(),
      returnPathRisk: z.number().optional(),
      placementCorridorRisk: z.number().optional(),
    })
    .optional(),
  freeroutingJar: z.string().optional(),
  maxPasses: z.number().int().positive().optional(),
  timeout: z.number().positive().optional(),
  attempts: z.number().int().min(1).optional(),
  targetNets: z.array(z.string()).optional(),
  passSchedule: z.array(z.number().int().positive()).min(1).optional(),
  keepArtifacts: z.boolean().optional(),
  maxReroutePasses: z.number().int().min(0).optional(),
  orthorouteExecutable: z.string().optional(),
  skipBulkRoute: z.boolean().optional(),
  refillZones: z.boolean().optional(),
  autoTuneMatchedLengths: z.boolean().optional(),
  matchedLengthMinExtraMm: z.number().nonnegative().optional(),
  matchedLengthMaxGroupSize: z.number().int().positive().optional(),
  autoHealSupportNets: z.boolean().optional(),
  healingPasses: z.number().int().min(0).optional(),
  maxHealingViasPerNet: z.number().int().min(0).optional(),
  autoCreateReferenceZones: z.boolean().optional(),
  referenceZoneNet: z.string().optional(),
  referenceZoneLayer: z.string().optional(),
  referenceZoneInsetMm: z.number().nonnegative().optional(),
  referenceZoneClearanceMm: z.number().nonnegative().optional(),
  referenceZoneMinWidthMm: z.number().positive().optional(),
  reportPath: z.string().optional(),
  qorReportPath: z.string().optional(),
};

export function registerCFHATools(server: McpServer, callKicadScript: Function): void {
  server.tool(
    "autoroute_cfha",
    "Run the complete constraint-first hybrid flow: audit the board, infer electrical intents, compile KiCad rules, reserve return paths, route critical nets first, bulk-route the remainder, tune, and verify DRC/QoR.",
    routingOrchestrationArgs,
    async (args: unknown) => formatKicadResult(await callKicadScript("autoroute_cfha", args), 2),
  );

  server.tool(
    "analyze_board_routing_context",
    "Audit stackup, copper layers, routing density, reference-plane continuity, split risks, and available routing backends without modifying the board.",
    {
      boardPath: routingOrchestrationArgs.boardPath,
      profiles: routingOrchestrationArgs.profiles,
      interfaces: routingOrchestrationArgs.interfaces,
      freeroutingJar: routingOrchestrationArgs.freeroutingJar,
      orthorouteExecutable: routingOrchestrationArgs.orthorouteExecutable,
    },
    async (args: unknown) =>
      formatKicadResult(await callKicadScript("analyze_board_routing_context", args), 2),
  );

  server.tool(
    "extract_routing_intents",
    "Classify nets as RF, differential/high-speed, analog-sensitive, DC/switching power, ground, or generic before routing.",
    {
      boardPath: routingOrchestrationArgs.boardPath,
      intentOverrides: z.record(z.string()).optional(),
      profiles: routingOrchestrationArgs.profiles,
      interfaces: routingOrchestrationArgs.interfaces,
    },
    async (args: unknown) =>
      formatKicadResult(await callKicadScript("extract_routing_intents", args), 2),
  );

  server.tool(
    "generate_routing_constraints",
    "Generate canonical JSON routing constraints from inferred intents, electrical limits, matched-length groups, and placement corridors.",
    {
      boardPath: routingOrchestrationArgs.boardPath,
      profiles: routingOrchestrationArgs.profiles,
      interfaces: routingOrchestrationArgs.interfaces,
      criticalClasses: routingOrchestrationArgs.criticalClasses,
      placementRoutingCorridors: routingOrchestrationArgs.placementRoutingCorridors,
      powerCurrentA: routingOrchestrationArgs.powerCurrentA,
      copperOz: routingOrchestrationArgs.copperOz,
      tempRiseC: routingOrchestrationArgs.tempRiseC,
      maxLengthMm: routingOrchestrationArgs.maxLengthMm,
      matchedLengthGroups: routingOrchestrationArgs.matchedLengthGroups,
      inferMatchedLengthGroups: routingOrchestrationArgs.inferMatchedLengthGroups,
      excludeFromFreeRouting: routingOrchestrationArgs.excludeFromFreeRouting,
      seed: routingOrchestrationArgs.seed,
      outputPath: z.string().optional(),
    },
    async (args: unknown) =>
      formatKicadResult(await callKicadScript("generate_routing_constraints", args), 2),
  );

  server.tool(
    "generate_kicad_dru",
    "Compile canonical routing constraints into a project-local KiCad .kicad_dru rule file.",
    {
      boardPath: routingOrchestrationArgs.boardPath,
      profiles: routingOrchestrationArgs.profiles,
      interfaces: routingOrchestrationArgs.interfaces,
      outputPath: z.string().optional(),
    },
    async (args: unknown) =>
      formatKicadResult(await callKicadScript("generate_kicad_dru", args), 2),
  );

  server.tool(
    "route_critical_nets",
    "Route critical nets before the bulk router using intent-aware widths, layers, retries, differential-pair transitions, and return-path protection.",
    {
      boardPath: routingOrchestrationArgs.boardPath,
      criticalClasses: routingOrchestrationArgs.criticalClasses,
      criticalLayer: z.string().optional(),
      criticalWidthMm: z.number().positive().optional(),
      maxReroutePasses: routingOrchestrationArgs.maxReroutePasses,
      profiles: routingOrchestrationArgs.profiles,
      interfaces: routingOrchestrationArgs.interfaces,
    },
    async (args: unknown) =>
      formatKicadResult(await callKicadScript("route_critical_nets", args), 2),
  );

  server.tool(
    "run_freerouting",
    "Run the controlled bulk-routing stage while preserving excluded power, ground, and already-routed critical nets when supported.",
    {
      boardPath: routingOrchestrationArgs.boardPath,
      freeroutingJar: routingOrchestrationArgs.freeroutingJar,
      maxPasses: routingOrchestrationArgs.maxPasses,
      timeout: routingOrchestrationArgs.timeout,
      attempts: routingOrchestrationArgs.attempts,
      targetNets: routingOrchestrationArgs.targetNets,
      passSchedule: routingOrchestrationArgs.passSchedule,
      keepArtifacts: routingOrchestrationArgs.keepArtifacts,
      seed: routingOrchestrationArgs.seed,
      excludeNets: z.array(z.string()).optional(),
      dsnPath: z.string().optional(),
      sesPath: z.string().optional(),
      extraFreeroutingArgs: z.array(z.string()).optional(),
    },
    async (args: unknown) => formatKicadResult(await callKicadScript("run_freerouting", args), 2),
  );

  server.tool(
    "post_tune_routes",
    "Tune explicit matched-length groups, refill/reference zones, rebuild connectivity, and conservatively heal residual support-net islands.",
    {
      boardPath: routingOrchestrationArgs.boardPath,
      matchedLengthGroups: routingOrchestrationArgs.matchedLengthGroups,
      autoTuneMatchedLengths: routingOrchestrationArgs.autoTuneMatchedLengths,
      matchedLengthMinExtraMm: routingOrchestrationArgs.matchedLengthMinExtraMm,
      matchedLengthMaxGroupSize: routingOrchestrationArgs.matchedLengthMaxGroupSize,
      refillZones: routingOrchestrationArgs.refillZones,
      autoCreateReferenceZones: routingOrchestrationArgs.autoCreateReferenceZones,
      referenceZoneNet: routingOrchestrationArgs.referenceZoneNet,
      referenceZoneLayer: routingOrchestrationArgs.referenceZoneLayer,
      referenceZoneInsetMm: routingOrchestrationArgs.referenceZoneInsetMm,
      referenceZoneClearanceMm: routingOrchestrationArgs.referenceZoneClearanceMm,
      referenceZoneMinWidthMm: routingOrchestrationArgs.referenceZoneMinWidthMm,
      autoHealSupportNets: routingOrchestrationArgs.autoHealSupportNets,
      healingPasses: routingOrchestrationArgs.healingPasses,
      maxHealingViasPerNet: routingOrchestrationArgs.maxHealingViasPerNet,
      healingReportPath: z.string().optional(),
    },
    async (args: unknown) => formatKicadResult(await callKicadScript("post_tune_routes", args), 2),
  );

  server.tool(
    "verify_routing_qor",
    "Run final DRC and report completion, total length, vias, differential/matched skew, coupling, return-path risk, and an aggregate QoR grade.",
    {
      boardPath: routingOrchestrationArgs.boardPath,
      reportPath: routingOrchestrationArgs.reportPath,
      qorReportPath: routingOrchestrationArgs.qorReportPath,
      profiles: routingOrchestrationArgs.profiles,
      interfaces: routingOrchestrationArgs.interfaces,
    },
    async (args: unknown) =>
      formatKicadResult(await callKicadScript("verify_routing_qor", args), 2),
  );
}
