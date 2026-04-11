/**
 * Static workflow resources for KiCAD MCP server.
 */

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { logger } from "../logger.js";
import { CIRCUIT_DESIGN_EXCELLENCE_WORKFLOW } from "../workflows/circuit-design-excellence.js";

export function registerWorkflowResources(server: McpServer): void {
  logger.info("Registering workflow resources");

  server.resource(
    "circuit_design_excellence_workflow",
    "kicad://workflow/circuit-design-excellence",
    async (uri) => ({
      contents: [
        {
          uri: uri.href,
          text: CIRCUIT_DESIGN_EXCELLENCE_WORKFLOW,
          mimeType: "text/plain",
        },
      ],
    }),
  );

  logger.info("Workflow resources registered");
}
