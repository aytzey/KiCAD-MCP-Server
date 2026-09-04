import { describe, expect, it, vi } from "vitest";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";
import { registerComponentTools } from "../src/tools/component.js";

function suggestPlacementSchema(): z.ZodRawShape {
  let schema: z.ZodRawShape | undefined;
  const server = {
    tool: vi.fn((...registration: unknown[]) => {
      if (registration[0] === "suggest_placement") {
        schema = registration[2] as z.ZodRawShape;
      }
    }),
  } as unknown as McpServer;

  registerComponentTools(server, vi.fn());
  expect(schema).toBeDefined();
  return schema!;
}

describe("suggest_placement MCP work budget", () => {
  it("accepts the documented upper bounds", () => {
    const result = z.object(suggestPlacementSchema()).safeParse({
      iterations: 1000,
      rotation_passes: 8,
      spread_iters: 500,
      legalize_iters: 500,
      rotation_steps: [-90, 0, 90, 180],
    });

    expect(result.success).toBe(true);
  });

  it.each([
    { iterations: 1001 },
    { rotation_passes: 9 },
    { spread_iters: 501 },
    { legalize_iters: 501 },
    { rotation_steps: [0, 45, 90] },
  ])("rejects an unsafe or geometrically unsupported control: %j", (payload) => {
    const result = z.object(suggestPlacementSchema()).safeParse(payload);
    expect(result.success).toBe(false);
  });
});
