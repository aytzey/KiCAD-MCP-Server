#!/usr/bin/env node

/** Verify the built server over a real MCP stdio connection. */

import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";
import { resolve } from "node:path";

const expectedTools = [
  "suggest_placement",
  "autoroute_cfha",
  "analyze_manufacturing_readiness",
  "prepare_manufacturing_package",
];

const transport = new StdioClientTransport({
  command: process.execPath,
  args: [resolve("dist/index.js")],
  cwd: process.cwd(),
  env: {
    ...process.env,
    KICAD_AUTO_LAUNCH: "false",
    KICAD_SKIP_SYMBOL_WARMUP: "1",
    LOG_LEVEL: process.env.LOG_LEVEL || "error",
  },
});
const client = new Client({ name: "kicad-production-smoke", version: "1.0.0" });

try {
  await client.connect(transport);
  const listed = await client.listTools();
  const names = new Set(listed.tools.map((tool) => tool.name));
  const missing = expectedTools.filter((name) => !names.has(name));
  if (missing.length) {
    throw new Error(`Expected MCP tools are missing: ${missing.join(", ")}`);
  }

  const freerouting = await client.callTool({
    name: "check_freerouting",
    arguments: {},
  });
  if (freerouting.isError) {
    throw new Error(`Freerouting readiness failed: ${JSON.stringify(freerouting.content)}`);
  }

  console.log(
    JSON.stringify(
      {
        success: true,
        toolCount: listed.tools.length,
        expectedTools,
        freerouting: freerouting.content,
      },
      null,
      2,
    ),
  );
} finally {
  await client.close();
}
