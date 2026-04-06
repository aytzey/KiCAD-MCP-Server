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
    orthorouteExecutable: z
      .string()
      .optional()
      .describe("Optional external OrthoRoute executable path"),
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
    "Run the full constraint-first hybrid autorouting orchestrator explicitly.",
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
    "Stage 2 constraint synthesis. Builds the canonical JSON routing schema that becomes the single source of truth for runtime intents, KiCad custom rules, and backend orchestration defaults.",
    {
      boardPath: z.string().optional().describe("Path to .kicad_pcb file (default: current board)"),
      profiles: z.array(z.string()).optional(),
      interfaces: z.array(z.string()).optional(),
      criticalClasses: z.array(z.string()).optional(),
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
    "Stage 4 critical routing. Uses the embedded orthoroute-compatible critical router with IPC-first application when available, falling back to SWIG only when live IPC control is not available.",
    {
      boardPath: z.string().optional().describe("Path to .kicad_pcb file (default: current board)"),
      criticalClasses: z.array(z.string()).optional().describe("Critical classes to route in this stage"),
      criticalLayer: z.string().optional().describe("Preferred layer for critical routing (default: F.Cu)"),
      criticalWidthMm: z.number().optional().describe("Preferred width override for critical routing"),
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
    "Stage 6 post-processing. Rebuilds connectivity, optionally refills zones, and reserves a stable hook for future skew cleanup, meander relaxation, RF smoothing, and stitching-via insertion.",
    {
      boardPath: z.string().optional().describe("Path to .kicad_pcb file (default: current board)"),
      refillZones: z.boolean().optional().describe("Refill zones during post-processing"),
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
    "Stage 7 verification. Runs DRC and produces QoR metrics including completion rate, wire length, via count, differential skew estimates, uncoupled estimates, and return-path/power misuse flags.",
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
