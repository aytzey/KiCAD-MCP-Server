"""
Miscellaneous command handlers extracted from kicad_interface.py.

Covers: SVG logo import, project snapshots, KiCAD UI management, and zone refill.
"""

import logging
import os

import pcbnew

from utils.kicad_process import KiCADProcessManager, check_and_launch_kicad

AUTO_LAUNCH_KICAD = os.environ.get("KICAD_AUTO_LAUNCH", "false").lower() == "true"

logger = logging.getLogger("kicad_interface")


class MiscHandlers:
    def __init__(self):
        pass

    def import_svg_logo(self, params, board=None):
        """Import an SVG file as PCB graphic polygons on the silkscreen"""
        logger.info("Importing SVG logo into PCB")
        try:
            from commands.svg_import import import_svg_to_pcb

            pcb_path = params.get("pcbPath")
            svg_path = params.get("svgPath")
            x = float(params.get("x", 0))
            y = float(params.get("y", 0))
            width = float(params.get("width", 10))
            layer = params.get("layer", "F.SilkS")
            stroke_width = float(params.get("strokeWidth", 0))
            filled = bool(params.get("filled", True))

            if not pcb_path or not svg_path:
                return {
                    "success": False,
                    "message": "Missing required parameters: pcbPath, svgPath",
                }

            result = import_svg_to_pcb(pcb_path, svg_path, x, y, width, layer, stroke_width, filled)

            # import_svg_to_pcb writes gr_poly entries directly to the .kicad_pcb file,
            # bypassing the pcbnew in-memory board object.  Any subsequent board.Save()
            # call would overwrite the file with the stale in-memory state, erasing the
            # logo.  Reload the board from disk so pcbnew's memory matches the file.
            if result.get("success") and board:
                try:
                    board = pcbnew.LoadBoard(pcb_path)
                    logger.info("Reloaded board into pcbnew after SVG logo import")
                except Exception as reload_err:
                    logger.warning(
                        f"Board reload after SVG import failed (non-fatal): {reload_err}"
                    )

            return result

        except Exception as e:
            logger.error(f"Error importing SVG logo: {str(e)}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def snapshot_project(self, params, board=None):
        """Copy the entire project folder to a snapshot directory for checkpoint/resume."""
        import shutil
        from datetime import datetime
        from pathlib import Path

        try:
            step = params.get("step", "")
            label = params.get("label", "")
            prompt_text = params.get("prompt", "")
            # Determine project directory from loaded board or explicit path
            project_dir = None
            if board:
                board_file = board.GetFileName()
                if board_file:
                    project_dir = str(Path(board_file).parent)
            if not project_dir:
                project_dir = params.get("projectPath")
            if not project_dir or not os.path.isdir(project_dir):
                return {
                    "success": False,
                    "message": "Could not determine project directory for snapshot",
                }

            ts = datetime.now().strftime("%Y%m%d_%H%M%S")

            # Save prompt + log into logs/ subdirectory before snapshotting
            logs_dir = Path(project_dir) / "logs"
            logs_dir.mkdir(exist_ok=True)

            prompt_file = None
            if prompt_text:
                prompt_filename = f"PROMPT_step{step}_{ts}.md" if step else f"PROMPT_{ts}.md"
                prompt_file = logs_dir / prompt_filename
                prompt_file.write_text(prompt_text, encoding="utf-8")
                logger.info(f"Prompt saved: {prompt_file}")

            # Copy current MCP session log into logs/ before snapshotting
            import platform

            system = platform.system()
            if system == "Windows":
                mcp_log_dir = os.path.join(os.environ.get("APPDATA", ""), "Claude", "logs")
            elif system == "Darwin":
                mcp_log_dir = os.path.expanduser("~/Library/Logs/Claude")
            else:
                mcp_log_dir = os.path.expanduser("~/.config/Claude/logs")
            mcp_log_src = os.path.join(mcp_log_dir, "mcp-server-kicad.log")
            mcp_log_dest = None
            if os.path.exists(mcp_log_src):
                with open(mcp_log_src, "r", encoding="utf-8", errors="replace") as f:
                    all_lines = f.readlines()
                session_start = 0
                for i, line in enumerate(all_lines):
                    if "Initializing server" in line:
                        session_start = i
                session_lines = all_lines[session_start:]
                log_filename = f"mcp_log_step{step}_{ts}.txt" if step else f"mcp_log_{ts}.txt"
                mcp_log_dest = logs_dir / log_filename
                with open(mcp_log_dest, "w", encoding="utf-8") as f:
                    f.writelines(session_lines)
                logger.info(f"MCP session log saved: {mcp_log_dest} ({len(session_lines)} lines)")

            base_name = Path(project_dir).name
            suffix_parts = [p for p in [f"step{step}" if step else "", label, ts] if p]
            snapshot_name = base_name + "_snapshot_" + "_".join(suffix_parts)
            snapshots_base = Path(project_dir) / "snapshots"
            snapshots_base.mkdir(exist_ok=True)
            snapshot_dir = str(snapshots_base / snapshot_name)

            shutil.copytree(project_dir, snapshot_dir, ignore=shutil.ignore_patterns("snapshots"))
            logger.info(f"Project snapshot saved: {snapshot_dir}")
            return {
                "success": True,
                "message": f"Snapshot saved: {snapshot_name}",
                "snapshotPath": snapshot_dir,
                "sourceDir": project_dir,
                "promptSaved": str(prompt_file) if prompt_file else None,
                "mcpLogSaved": str(mcp_log_dest) if mcp_log_dest else None,
            }
        except Exception as e:
            logger.error(f"snapshot_project error: {e}")
            return {"success": False, "message": str(e)}

    def check_kicad_ui(self, params):
        """Check if KiCAD UI is running"""
        logger.info("Checking if KiCAD UI is running")
        try:
            manager = KiCADProcessManager()
            is_running = manager.is_running()
            processes = manager.get_process_info() if is_running else []

            return {
                "success": True,
                "running": is_running,
                "processes": processes,
                "message": "KiCAD is running" if is_running else "KiCAD is not running",
            }
        except Exception as e:
            logger.error(f"Error checking KiCAD UI status: {str(e)}")
            return {"success": False, "message": str(e)}

    def launch_kicad_ui(self, params):
        """Launch KiCAD UI"""
        logger.info("Launching KiCAD UI")
        try:
            project_path = params.get("projectPath")
            auto_launch = params.get("autoLaunch", AUTO_LAUNCH_KICAD)

            # Convert project path to Path object if provided
            from pathlib import Path

            path_obj = Path(project_path) if project_path else None

            result = check_and_launch_kicad(path_obj, auto_launch)

            return {"success": True, **result}
        except Exception as e:
            logger.error(f"Error launching KiCAD UI: {str(e)}")
            return {"success": False, "message": str(e)}

    def refill_zones(self, params, board=None):
        """Refill all copper pour zones on the board.

        pcbnew.ZONE_FILLER.Fill() can cause a C++ access violation (0xC0000005)
        that crashes the entire Python process when called from SWIG outside KiCAD UI.
        To avoid killing the main process we run the fill in an isolated subprocess.
        If the subprocess crashes or times out, we return a non-fatal warning so the
        caller can continue — KiCAD Pcbnew will refill zones automatically when the
        board is opened (press B).
        """
        logger.info("Refilling zones (subprocess isolation)")
        try:
            if not board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first",
                }

            # First save the board so the subprocess can load it fresh
            board_path = board.GetFileName()
            if not board_path:
                return {
                    "success": False,
                    "message": "Board has no file path — save first",
                }
            board.Save(board_path)

            zone_count = board.GetAreaCount() if hasattr(board, "GetAreaCount") else 0

            # Run pcbnew zone fill in an isolated subprocess to prevent crashes
            import subprocess
            import sys
            import textwrap

            script = textwrap.dedent(f"""
import pcbnew, sys
board = pcbnew.LoadBoard({repr(board_path)})
filler = pcbnew.ZONE_FILLER(board)
filler.Fill(board.Zones())
board.Save({repr(board_path)})
print("ok")
""")
            try:
                result = subprocess.run(
                    [sys.executable, "-c", script],
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                if result.returncode == 0 and "ok" in result.stdout:
                    logger.info("Zone fill subprocess succeeded")
                    return {
                        "success": True,
                        "message": f"Zones refilled successfully ({zone_count} zones)",
                        "zoneCount": zone_count,
                    }
                else:
                    logger.warning(
                        f"Zone fill subprocess failed: rc={result.returncode} stderr={result.stderr[:200]}"
                    )
                    return {
                        "success": False,
                        "message": "Zone fill failed in subprocess — zones are defined and will fill when opened in KiCAD (press B). Continuing is safe.",
                        "zoneCount": zone_count,
                        "details": (result.stderr[:300] if result.stderr else result.stdout[:300]),
                    }
            except subprocess.TimeoutExpired:
                logger.warning("Zone fill subprocess timed out after 60s")
                return {
                    "success": False,
                    "message": "Zone fill timed out — zones are defined and will fill when opened in KiCAD (press B). Continuing is safe.",
                    "zoneCount": zone_count,
                }

        except Exception as e:
            logger.error(f"Error refilling zones: {str(e)}")
            return {"success": False, "message": str(e)}
