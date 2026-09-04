import { describe, expect, it, vi } from "vitest";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";
import { registerSchematicTools } from "../src/tools/schematic.js";

describe("sync_schematic_to_board MCP contract", () => {
  it("validates and forwards routing-aware placement controls", async () => {
    let schema: z.ZodRawShape | undefined;
    let handler: ((args: Record<string, unknown>) => Promise<unknown>) | undefined;
    const server = {
      tool: vi.fn((...registration: unknown[]) => {
        if (registration[0] === "sync_schematic_to_board") {
          schema = registration[2] as z.ZodRawShape;
          handler = registration[3] as (args: Record<string, unknown>) => Promise<unknown>;
        }
      }),
    } as unknown as McpServer;
    const callKicadScript = vi.fn().mockResolvedValue({ success: true });

    registerSchematicTools(server, callKicadScript);

    expect(schema).toBeDefined();
    expect(handler).toBeDefined();
    const payload = {
      schematicPath: "C:/boards/demo.kicad_sch",
      boardPath: "C:/boards/demo.kicad_pcb",
      autoPlaceMissingFootprints: true,
      placementStrategy: "routing_aware" as const,
      placementStartXmm: 12.5,
      placementStartYmm: 8,
      placementPitchXmm: 10,
      placementPitchYmm: 8,
      placementColumns: 5,
      placementEdgeMarginMm: 3,
      placementClusterGapMm: 7,
    };
    const parsed = z.object(schema!).parse(payload);

    await handler!(parsed);

    expect(callKicadScript).toHaveBeenCalledWith("sync_schematic_to_board", payload);
  });

  it("rejects invalid placement controls before they reach Python", () => {
    let schema: z.ZodRawShape | undefined;
    const server = {
      tool: vi.fn((...registration: unknown[]) => {
        if (registration[0] === "sync_schematic_to_board") {
          schema = registration[2] as z.ZodRawShape;
        }
      }),
    } as unknown as McpServer;

    registerSchematicTools(server, vi.fn());

    const result = z.object(schema!).safeParse({
      schematicPath: "C:/boards/demo.kicad_sch",
      boardPath: "C:/boards/demo.kicad_pcb",
      placementStrategy: "random",
      placementPitchXmm: 0,
      placementColumns: 0,
    });
    expect(result.success).toBe(false);
  });
});
