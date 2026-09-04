import { afterEach, describe, expect, it } from "vitest";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { findPythonExecutable } from "../src/server.js";

describe("KiCad Python selection", () => {
  const originalOverride = process.env.KICAD_PYTHON;
  const temporaryRoots: string[] = [];

  afterEach(() => {
    if (originalOverride === undefined) {
      delete process.env.KICAD_PYTHON;
    } else {
      process.env.KICAD_PYTHON = originalOverride;
    }
    for (const root of temporaryRoots.splice(0)) {
      rmSync(root, { recursive: true, force: true });
    }
  });

  it("honors explicit KICAD_PYTHON when a project .venv also exists", () => {
    const root = mkdtempSync(join(tmpdir(), "kicad-python-selection-"));
    temporaryRoots.push(root);
    const scriptPath = join(root, "python", "kicad_interface.py");
    const venvPython = join(root, ".venv", "Scripts", "python.exe");
    const configuredPython = join(root, "KiCad", "bin", "python.exe");
    for (const path of [scriptPath, venvPython, configuredPython]) {
      mkdirSync(join(path, ".."), { recursive: true });
      writeFileSync(path, "");
    }
    process.env.KICAD_PYTHON = configuredPython;

    expect(findPythonExecutable(scriptPath)).toBe(configuredPython);
  });
});
