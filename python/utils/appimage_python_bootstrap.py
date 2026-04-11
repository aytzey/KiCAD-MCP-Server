#!/usr/bin/env python3
"""
Bootstrap KiCad AppImage's Python so it can also import MCP dependencies.
"""

from __future__ import annotations

import runpy
import sys
from pathlib import Path


def _iter_extra_site_packages(project_root: Path) -> list[str]:
    extra_paths: list[str] = []
    lib_roots = [
        Path.home() / ".local" / "opt" / "kicad-10.0.0" / "python-packages",
        project_root / "venv" / "lib",
        project_root / ".venv" / "lib",
        Path.home() / ".local" / "lib",
        Path("/usr/local/lib"),
        Path("/usr/lib"),
    ]

    for lib_root in lib_roots:
        if not lib_root.exists():
            continue
        if lib_root.name == "python-packages":
            extra_paths.append(str(lib_root))
            continue
        for site_packages in sorted(lib_root.glob("python*/site-packages")):
            if site_packages.is_dir():
                extra_paths.append(str(site_packages))
        for dist_packages in sorted(lib_root.glob("python*/dist-packages")):
            if dist_packages.is_dir():
                extra_paths.append(str(dist_packages))
    return extra_paths


def _append_paths(paths: list[str]) -> None:
    new_paths = [path for path in paths if path and path not in sys.path]
    if new_paths:
        sys.path.extend(new_paths)


def _run_code(code: str, argv: list[str]) -> None:
    sys.argv = ["-c", *argv]
    globals_dict = {"__name__": "__main__", "__file__": "<string>"}
    exec(compile(code, "<string>", "exec"), globals_dict)


def _run_module(module_name: str, argv: list[str]) -> None:
    sys.argv = [module_name, *argv]
    runpy.run_module(module_name, run_name="__main__", alter_sys=True)


def _run_script(script: str, argv: list[str]) -> None:
    script_path = Path(script).resolve()
    sys.argv = [str(script_path), *argv]
    script_dir = str(script_path.parent)
    if script_dir not in sys.path:
        sys.path.insert(0, script_dir)
    runpy.run_path(str(script_path), run_name="__main__")


def main() -> int:
    project_root = Path(__file__).resolve().parents[2]
    _append_paths(_iter_extra_site_packages(project_root))

    args = sys.argv[1:]
    if not args:
        return 0

    if args[0] in ("-V", "--version"):
        print(sys.version)
        return 0

    if args[0] == "-c":
        if len(args) < 2:
            raise SystemExit("Argument expected for -c")
        _run_code(args[1], args[2:])
        return 0

    if args[0] == "-m":
        if len(args) < 2:
            raise SystemExit("Argument expected for -m")
        _run_module(args[1], args[2:])
        return 0

    _run_script(args[0], args[1:])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
