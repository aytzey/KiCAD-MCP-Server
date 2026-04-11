/**
 * Hybrid autorouting and Freerouting tools for KiCAD MCP server.
 */

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";

export function registerFreeroutingTools(server: McpServer, callKicadScript: Function) {
  const orchestrationArgs = {
    boardPath: z.string().optional().describe("Path to .kicad_pcb file (default: current board)"),
    strategy: z
      .enum(["hybrid", "critical_only", "analysis_only"])
      .optional()
      .describe("Routing strategy (default: hybrid)"),
    seed: z.number().optional().describe("Deterministic seed for ordering and backend selection"),
    timeBudgetSec: z.number().optional().describe("Overall routing time budget in seconds"),
    criticalClasses: z
      .array(z.string())
      .optional()
      .describe("Critical intent classes routed before bulk routing"),
    placementRoutingCorridors: z
      .array(z.record(z.any()))
      .optional()
      .describe("Numeric breakout corridor reservations returned by sync_schematic_to_board as auto_place_routing_corridors"),
    powerCurrentA: z
      .number()
      .optional()
      .describe("Optional DC current in amps used to derive IPC-2221 minimum power trace widths"),
    copperOz: z
      .number()
      .optional()
      .describe("Copper weight in oz used for IPC-2221 power-width synthesis (default: 1.0 oz)"),
    tempRiseC: z
      .number()
      .optional()
      .describe("Allowed temperature rise in Celsius for IPC-2221 power-width synthesis (default: 10 C)"),
    maxLengthMm: z
      .number()
      .optional()
      .describe("Optional absolute length ceiling for HS single-ended nets"),
    matchedLengthGroups: z
      .array(
        z.object({
          nets: z.array(z.string()).describe("Net names that should be matched together"),
          maxSkewMm: z.number().optional().describe("Maximum skew inside the group in mm"),
          type: z.string().optional().describe("Group type label such as diff_pair or bus"),
        }),
      )
      .optional()
      .describe("Optional explicit matched-length groups such as DDR or address/data buses"),
    inferMatchedLengthGroups: z
      .boolean()
      .optional()
      .describe("Infer bus-style matched-length groups automatically from interface-aware net naming"),
    autoMatchedLengthMaxSkewMm: z
      .number()
      .optional()
      .describe("Override the default skew target used for auto-inferred matched-length groups"),
    autoMatchedLengthMinGroupSize: z
      .number()
      .int()
      .optional()
      .describe("Minimum net count for an auto-inferred matched-length bus group"),
    autoMatchedLengthMaxGroupSize: z
      .number()
      .int()
      .optional()
      .describe("Maximum net count for an auto-inferred matched-length bus group"),
    excludeFromFreeRouting: z
      .array(z.string())
      .optional()
      .describe("Net names that bulk routing should leave untouched. Pass [] to exclude nothing explicitly."),
    profiles: z
      .array(z.string())
      .optional()
      .describe("Board profiles such as generic_2layer, power, high_speed_digital"),
    interfaces: z
      .array(z.string())
      .optional()
      .describe("Interface overlays such as USB2, USB3, PCIe, DDR4"),
    qorWeights: z
      .object({
        length: z.number().optional(),
        vias: z.number().optional(),
        skew: z.number().optional(),
        uncoupled: z.number().optional(),
        returnPathRisk: z.number().optional(),
        placementCorridorRisk: z.number().optional(),
      })
      .optional()
      .describe("QoR weighting for reporting and future optimization loops"),
    freeroutingJar: z
      .string()
      .optional()
      .describe(
        "Path to freerouting.jar (default: ~/.kicad-mcp/freerouting.jar or FREEROUTING_JAR env)",
      ),
    maxPasses: z.number().optional().describe("Maximum Freerouting passes for the bulk stage"),
    timeout: z.number().optional().describe("Freerouting timeout in seconds"),
    maxReroutePasses: z
      .number()
      .optional()
      .describe("Number of retry passes for failed critical nets after the main routing pass"),
    orthorouteExecutable: z
      .string()
      .optional()
      .describe("Optional external OrthoRoute executable path"),
    refillZones: z
      .boolean()
      .optional()
      .describe("Refill copper zones during post-route cleanup"),
    autoCreateReferenceZones: z
      .boolean()
      .optional()
      .describe("Create a deterministic ground reference zone automatically when high-speed nets exist but no ground plane is present"),
    referenceZoneNet: z
      .string()
      .optional()
      .describe("Optional ground net name to use for an automatically created reference zone"),
    referenceZoneLayer: z
      .string()
      .optional()
      .describe("Optional layer override for an automatically created reference zone"),
    referenceZoneInsetMm: z
      .number()
      .optional()
      .describe("Inset from the board edge used for an automatically created reference zone"),
    referenceZoneClearanceMm: z
      .number()
      .optional()
      .describe("Clearance used for an automatically created reference zone"),
    referenceZoneMinWidthMm: z
      .number()
      .optional()
      .describe("Minimum copper width used for an automatically created reference zone"),
    reportPath: z
      .string()
      .optional()
      .describe("Optional DRC report output path used by QoR verification"),
    qorReportPath: z
      .string()
      .optional()
      .describe("Optional JSON QoR report output path"),
  };

  // Default autoroute now points to the hybrid CFHA orchestrator.
  server.tool(
    "autoroute",
    "Default autorouter. Runs the constraint-first hybrid orchestrator: analyze board, classify net intents, compile .kicad_dru rules, route critical nets first, optionally delegate remaining bulk routing to Freerouting, then verify DRC and QoR.",
    orchestrationArgs,
    async (args: any) => {
      const result = await callKicadScript("autoroute", args);
      return {
        content: [
          {
            type: "text",
            text: JSON.stringify(result, null, 2),
          },
        ],
      };
    },
  );

  server.tool(
    "autoroute_cfha",
    "Run the full constraint-first hybrid autorouting orchestrator explicitly, including pre-route reference planning before critical routing.",
    orchestrationArgs,
    async (args: any) => {
      const result = await callKicadScript("autoroute_cfha", args);
      return {
        content: [
          {
            type: "text",
            text: JSON.stringify(result, null, 2),
          },
        ],
      };
    },
  );

  server.tool(
    "analyze_board_routing_context",
    "Stage 0 preflight audit. Reports stackup, copper layers, plane continuity hints, split-risk layers, density hot spots, backend availability, and inferred board profiles before any routing work starts.",
    {
      boardPath: z.string().optional().describe("Path to .kicad_pcb file (default: current board)"),
      profiles: z.array(z.string()).optional().describe("Optional explicit board profiles"),
      interfaces: z.array(z.string()).optional().describe("Optional interface overlays"),
      freeroutingJar: z.string().optional().describe("Optional freerouting.jar path for backend audit"),
      orthorouteExecutable: z.string().optional().describe("Optional external OrthoRoute executable"),
    },
    async (args: any) => {
      const result = await callKicadScript("analyze_board_routing_context", args);
      return {
        content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
      };
    },
  );

  server.tool(
    "extract_routing_intents",
    "Stage 1 intent extraction. Classifies nets into RF, HS_DIFF, HS_SINGLE, ANALOG_SENSITIVE, POWER_DC, POWER_SWITCHING, GROUND, and GENERIC using explicit overrides, metadata, and naming heuristics.",
    {
      boardPath: z.string().optional().describe("Path to .kicad_pcb file (default: current board)"),
      intentOverrides: z
        .record(z.string())
        .optional()
        .describe("Explicit net-to-intent overrides"),
      profiles: z.array(z.string()).optional(),
      interfaces: z.array(z.string()).optional(),
    },
    async (args: any) => {
      const result = await callKicadScript("extract_routing_intents", args);
      return {
        content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
      };
    },
  );

  server.tool(
    "generate_routing_constraints",
    "Stage 2 constraint synthesis. Builds the canonical JSON routing schema that becomes the single source of truth for runtime intents, KiCad custom rules, backend orchestration defaults, and pre-route reference planning.",
    {
      boardPath: z.string().optional().describe("Path to .kicad_pcb file (default: current board)"),
      profiles: z.array(z.string()).optional(),
      interfaces: z.array(z.string()).optional(),
      criticalClasses: z.array(z.string()).optional(),
      placementRoutingCorridors: z
        .array(z.record(z.any()))
        .optional()
        .describe("Numeric breakout corridor reservations returned by sync_schematic_to_board as auto_place_routing_corridors"),
      powerCurrentA: z.number().optional().describe("Optional DC current in amps for IPC-2221 power-width synthesis"),
      copperOz: z.number().optional().describe("Copper weight in oz for IPC-2221 power-width synthesis"),
      tempRiseC: z.number().optional().describe("Allowed temperature rise in Celsius for IPC-2221 power-width synthesis"),
      maxLengthMm: z.number().optional().describe("Optional length ceiling for HS single-ended nets"),
      matchedLengthGroups: z
        .array(
          z.object({
            nets: z.array(z.string()),
            maxSkewMm: z.number().optional(),
            type: z.string().optional(),
          }),
        )
        .optional()
        .describe("Optional matched-length groups such as buses that need bounded skew"),
      excludeFromFreeRouting: z.array(z.string()).optional(),
      seed: z.number().optional(),
      outputPath: z.string().optional().describe("Optional path for the generated constraints JSON"),
    },
    async (args: any) => {
      const result = await callKicadScript("generate_routing_constraints", args);
      return {
        content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
      };
    },
  );

  server.tool(
    "generate_kicad_dru",
    "Stage 3 rule compilation. Compiles the canonical routing constraints into a KiCad .kicad_dru custom-rule artifact placed next to the board/project.",
    {
      boardPath: z.string().optional().describe("Path to .kicad_pcb file (default: current board)"),
      profiles: z.array(z.string()).optional(),
      interfaces: z.array(z.string()).optional(),
      outputPath: z.string().optional().describe("Optional output path for the .kicad_dru file"),
    },
    async (args: any) => {
      const result = await callKicadScript("generate_kicad_dru", args);
      return {
        content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
      };
    },
  );

  server.tool(
    "route_critical_nets",
    "Stage 4 critical routing. Uses the embedded orthoroute-compatible critical router with IPC-first application when available, falling back to SWIG only when live IPC control is not available, and inherits the preferred critical layer from reference planning when the caller does not force one.",
    {
      boardPath: z.string().optional().describe("Path to .kicad_pcb file (default: current board)"),
      criticalClasses: z.array(z.string()).optional().describe("Critical classes to route in this stage"),
      criticalLayer: z.string().optional().describe("Preferred layer for critical routing (default: F.Cu)"),
      criticalWidthMm: z.number().optional().describe("Preferred width override for critical routing"),
      maxReroutePasses: z.number().optional().describe("Retry count for critical nets that fail in the first pass"),
      profiles: z.array(z.string()).optional(),
      interfaces: z.array(z.string()).optional(),
    },
    async (args: any) => {
      const result = await callKicadScript("route_critical_nets", args);
      return {
        content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
      };
    },
  );

  server.tool(
    "run_freerouting",
    "Stage 5 bulk routing backend. Exports DSN, runs Freerouting as a controlled bulk router, imports SES, and preserves excluded power/ground/critical nets when the backend supports those filters.",
    {
      boardPath: z.string().optional().describe("Path to .kicad_pcb file (default: current board)"),
      freeroutingJar: z.string().optional(),
      maxPasses: z.number().optional(),
      timeout: z.number().optional(),
      seed: z.number().optional(),
      excludeNets: z.array(z.string()).optional().describe("Net names to keep out of the bulk router"),
      dsnPath: z.string().optional().describe("Optional DSN artifact path"),
      sesPath: z.string().optional().describe("Optional SES artifact path"),
      extraFreeroutingArgs: z.array(z.string()).optional().describe("Extra raw CLI args"),
    },
    async (args: any) => {
      const result = await callKicadScript("run_freerouting", args);
      return {
        content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
      };
    },
  );

  server.tool(
    "post_tune_routes",
    "Stage 6 post-processing. Rebuilds connectivity, optionally inserts conservative replacement meanders for explicit matched-length bus groups, optionally refills zones, and heals residual support-net disconnects by bridging same-layer ground/power islands before falling back to conservative stitching vias.",
    {
      boardPath: z.string().optional().describe("Path to .kicad_pcb file (default: current board)"),
      matchedLengthGroups: z.array(z.object({ nets: z.array(z.string()), maxSkewMm: z.number().optional(), type: z.string().optional() })).optional().describe("Explicit matched-length groups to tune during post-processing"),
      autoTuneMatchedLengths: z.boolean().optional().describe("Attempt deterministic post-route matched-length compensation on explicit bus groups"),
      matchedLengthMinExtraMm: z.number().optional().describe("Do not insert meanders when the required extra length is below this floor"),
      matchedLengthMaxGroupSize: z.number().int().optional().describe("Skip explicit groups larger than this size during post-route tuning"),
      refillZones: z.boolean().optional().describe("Refill zones during post-processing"),
      autoCreateReferenceZones: z.boolean().optional().describe("Create a deterministic ground reference zone when high-speed nets exist but no ground plane is present"),
      referenceZoneNet: z.string().optional().describe("Optional ground net name to use for an automatically created reference zone"),
      referenceZoneLayer: z.string().optional().describe("Optional layer override for an automatically created reference zone"),
      referenceZoneInsetMm: z.number().optional().describe("Inset from the board edge used for an automatically created reference zone"),
      referenceZoneClearanceMm: z.number().optional().describe("Clearance used for an automatically created reference zone"),
      referenceZoneMinWidthMm: z.number().optional().describe("Minimum copper width used for an automatically created reference zone"),
      autoHealSupportNets: z.boolean().optional().describe("Attempt conservative ground/power healing after routing"),
      healingPasses: z.number().int().optional().describe("Maximum support-net healing passes"),
      maxHealingViasPerNet: z.number().int().optional().describe("Upper bound for fallback stitch vias per net"),
      healingReportPath: z.string().optional().describe("Optional DRC report path used by the healing loop"),
    },
    async (args: any) => {
      const result = await callKicadScript("post_tune_routes", args);
      return {
        content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
      };
    },
  );

  server.tool(
    "verify_routing_qor",
    "Stage 7 verification. Runs DRC and produces QoR metrics including completion rate, wire length, via count, differential skew estimates, explicit matched-length group skew, uncoupled estimates, and return-path/power misuse flags.",
    {
      boardPath: z.string().optional().describe("Path to .kicad_pcb file (default: current board)"),
      reportPath: z.string().optional().describe("Optional DRC text report path"),
      qorReportPath: z.string().optional().describe("Optional JSON QoR report path"),
      profiles: z.array(z.string()).optional(),
      interfaces: z.array(z.string()).optional(),
    },
    async (args: any) => {
      const result = await callKicadScript("verify_routing_qor", args);
      return {
        content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
      };
    },
  );

  // Export DSN only
  server.tool(
    "export_dsn",
    "Export the current PCB to Specctra DSN format. Useful for manual Freerouting workflow or external autorouters.",
    {
      boardPath: z.string().optional().describe("Path to .kicad_pcb file (default: current board)"),
      outputPath: z
        .string()
        .optional()
        .describe("Output DSN file path (default: same dir as board)"),
    },
    async (args: any) => {
      const result = await callKicadScript("export_dsn", args);
      return {
        content: [
          {
            type: "text",
            text: JSON.stringify(result, null, 2),
          },
        ],
      };
    },
  );

  // Import SES
  server.tool(
    "import_ses",
    "Import a Specctra SES (session) file into the current PCB. Use after running Freerouting externally.",
    {
      sesPath: z.string().describe("Path to the .ses file to import"),
      boardPath: z.string().optional().describe("Path to .kicad_pcb file (default: current board)"),
    },
    async (args: any) => {
      const result = await callKicadScript("import_ses", args);
      return {
        content: [
          {
            type: "text",
            text: JSON.stringify(result, null, 2),
          },
        ],
      };
    },
  );

  // Check Freerouting dependencies
  server.tool(
    "check_freerouting",
    "Check if Java and Freerouting JAR are available on the system. Run this before autoroute to verify prerequisites.",
    {
      freeroutingJar: z.string().optional().describe("Path to freerouting.jar to check"),
    },
    async (args: any) => {
      const result = await callKicadScript("check_freerouting", args);
      return {
        content: [
          {
            type: "text",
            text: JSON.stringify(result, null, 2),
          },
        ],
      };
    },
  );
}
