#!/usr/bin/env python3
"""
Run the CFHA autorouter repeatedly against one or more board files.

This is intentionally subprocess-based so it exercises the same Python MCP
interface entrypoint that the server uses in production.
"""

from __future__ import annotations

import argparse
import json
import os
import site
import subprocess
import sys
import sysconfig
from pathlib import Path
from typing import Any, Dict


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _python_env() -> Dict[str, str]:
    env = dict(os.environ)
    paths = ["/usr/lib/python3/dist-packages"]
    for candidate in {site.getusersitepackages(), sysconfig.get_paths().get("purelib")}:
        if candidate:
            paths.append(candidate)
    existing = env.get("PYTHONPATH")
    if existing:
        paths.append(existing)
    env["PYTHONPATH"] = ":".join(dict.fromkeys(path for path in paths if path))
    return env


def _interface_python() -> str:
    return "/usr/bin/python3" if Path("/usr/bin/python3").exists() else sys.executable


def _call_interface(command: str, params: Dict[str, Any]) -> Dict[str, Any]:
    script = _repo_root() / "python" / "kicad_interface.py"
    proc = subprocess.run(
        [_interface_python(), str(script)],
        input=json.dumps({"command": command, "params": params}) + "\n",
        text=True,
        capture_output=True,
        env=_python_env(),
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or "unknown interface failure")

    lines = [line for line in proc.stdout.splitlines() if line.strip()]
    if not lines:
        raise RuntimeError("No response from kicad_interface.py")
    return json.loads(lines[-1])


def main() -> int:
    parser = argparse.ArgumentParser(description="Run CFHA autorouting regression on board files")
    parser.add_argument("boards", nargs="+", help="Paths to .kicad_pcb files")
    parser.add_argument("--strategy", default="hybrid", choices=["hybrid", "critical_only", "analysis_only"])
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--time-budget-sec", type=int, default=300)
    parser.add_argument("--report-dir", default=str(_repo_root() / "benchmarks" / "autoroute_cfha"))
    args = parser.parse_args()

    report_dir = Path(args.report_dir).resolve()
    report_dir.mkdir(parents=True, exist_ok=True)

    overall_ok = True
    for board_arg in args.boards:
        board_path = Path(board_arg).expanduser().resolve()
        result = _call_interface(
            "autoroute_cfha",
            {
                "boardPath": str(board_path),
                "strategy": args.strategy,
                "seed": args.seed,
                "timeBudgetSec": args.time_budget_sec,
                "qorReportPath": str(report_dir / f"{board_path.stem}.qor.json"),
            },
        )

        out_path = report_dir / f"{board_path.stem}.result.json"
        out_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(f"{board_path}: success={result.get('success')} report={out_path}")
        if not result.get("success"):
            overall_ok = False

    return 0 if overall_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
