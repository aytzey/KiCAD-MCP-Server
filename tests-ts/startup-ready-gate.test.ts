import { afterEach, describe, expect, it, vi } from "vitest";
import { fileURLToPath } from "node:url";
import { KiCADMcpServer } from "../src/server.js";

const pythonBridge = fileURLToPath(new URL("../python/kicad_interface.py", import.meta.url));

afterEach(() => {
  vi.useRealTimers();
});

describe("startup ready gate (#377)", () => {
  it("queues a tool call received after transport connect but before Python spawn", async () => {
    const server = new KiCADMcpServer(pythonBridge, "error") as any;
    server.lifecycleState = "starting";
    let rejection: Error | undefined;

    const pending = server.callKicadScript("check_freerouting", {}).catch((error: Error) => {
      rejection = error;
    });
    await Promise.resolve();

    expect(rejection).toBeUndefined();
    expect(server.requestQueue).toHaveLength(1);
    const queued = server.requestQueue.shift();
    queued?.resolve({ success: true });
    await pending;
  });

  it("holds queued tool calls until the backend reports READY", () => {
    vi.useFakeTimers();
    const server = new KiCADMcpServer(pythonBridge, "error") as any;
    const stdin = { write: vi.fn() };
    server.pythonProcess = { stdin };
    server.readyDetected = false;

    server.requestQueue.push({
      request: { command: "get_board_info", params: {}, timeout: 30_000 },
      resolve: vi.fn(),
      reject: vi.fn(),
    });

    server.processNextRequest();

    // Held: nothing written, no timeout started against Python's own startup.
    expect(stdin.write).not.toHaveBeenCalled();
    expect(server.processingRequest).toBe(false);
    expect(server.requestQueue.length).toBe(1);

    // READY fires: the queue drains and the request dispatches.
    server.readyDetected = true;
    server.processNextRequest();
    expect(stdin.write).toHaveBeenCalledOnce();
    expect(server.requestQueue.length).toBe(0);
  });
});
