"""
Design rules command implementations for KiCAD interface
"""

import json
import logging
import os
import platform
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pcbnew

logger = logging.getLogger("kicad_interface")


class DesignRuleCommands:
    """Handles design rule checking and configuration"""

    def __init__(self, board: Optional[pcbnew.BOARD] = None):
        """Initialize with optional board instance"""
        self.board = board

    @staticmethod
    def _parse_drc_report_text(report_text: str) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """Parse KiCad text DRC reports into the same summary shape as CLI JSON."""
        violations: List[Dict[str, Any]] = []
        severity_counts = {"error": 0, "warning": 0, "info": 0}
        violation_counts: Dict[str, int] = {}

        current: Optional[Dict[str, Any]] = None
        line_re = re.compile(r"^\[(?P<type>[^\]]+)\]:\s*(?P<message>.+)$")
        severity_re = re.compile(r"Severity:\s*(?P<severity>\w+)", re.IGNORECASE)
        location_re = re.compile(
            r"@\((?P<x>-?\d+(?:\.\d+)?)\s*mm,\s*(?P<y>-?\d+(?:\.\d+)?)\s*mm\)"
        )

        def _flush() -> None:
            nonlocal current
            if not current:
                return
            violations.append(current)
            vtype = current.get("type", "unknown")
            violation_counts[vtype] = violation_counts.get(vtype, 0) + 1
            severity = str(current.get("severity", "error")).lower()
            if severity not in severity_counts:
                severity_counts[severity] = 0
            severity_counts[severity] += 1
            current = None

        for raw_line in report_text.splitlines():
            line = raw_line.rstrip()
            match = line_re.match(line)
            if match:
                _flush()
                current = {
                    "type": match.group("type"),
                    "severity": "error",
                    "message": match.group("message").strip(),
                    "location": {},
                }
                continue

            if current is None:
                continue

            severity_match = severity_re.search(line)
            if severity_match:
                current["severity"] = severity_match.group("severity").lower()

            location_match = location_re.search(line)
            if location_match and not current.get("location"):
                current["location"] = {
                    "x": float(location_match.group("x")),
                    "y": float(location_match.group("y")),
                    "unit": "mm",
                }

        _flush()
        return violations, {"by_severity": severity_counts, "by_type": violation_counts}

    def _cli_supports_subcommand(
        self, kicad_cli: str, parent: str, subcommand: str
    ) -> bool:
        """Detect whether the installed kicad-cli exposes a given subcommand."""
        try:
            probe = subprocess.run(
                [kicad_cli, parent],
                capture_output=True,
                text=True,
                timeout=10,
            )
        except Exception:
            return False

        output = f"{probe.stdout or ''}\n{probe.stderr or ''}".lower()
        return subcommand.lower() in output

    def _write_violations_file(
        self,
        board_file: str,
        violations: List[Dict[str, Any]],
        summary: Dict[str, Any],
        *,
        timestamp: str = "unknown",
    ) -> str:
        board_dir = os.path.dirname(board_file)
        board_name = os.path.splitext(os.path.basename(board_file))[0]
        violations_file = os.path.join(board_dir, f"{board_name}_drc_violations.json")
        with open(violations_file, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "board": board_file,
                    "timestamp": timestamp,
                    "total_violations": len(violations),
                    "violation_counts": summary.get("by_type", {}),
                    "severity_counts": summary.get("by_severity", {}),
                    "violations": violations,
                },
                f,
                indent=2,
            )
        return violations_file

    def set_design_rules(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Set design rules for the PCB"""
        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first",
                }

            design_settings = self.board.GetDesignSettings()

            # Convert mm to nanometers for KiCAD internal units
            scale = 1000000  # mm to nm

            # Set clearance
            if "clearance" in params:
                design_settings.m_MinClearance = int(params["clearance"] * scale)

            # KiCAD 9.0: Use SetCustom* methods instead of SetCurrent* (which were removed)
            # Track if we set any custom track/via values
            custom_values_set = False

            if "trackWidth" in params:
                design_settings.SetCustomTrackWidth(int(params["trackWidth"] * scale))
                custom_values_set = True

            # Via settings
            if "viaDiameter" in params:
                design_settings.SetCustomViaSize(int(params["viaDiameter"] * scale))
                custom_values_set = True
            if "viaDrill" in params:
                design_settings.SetCustomViaDrill(int(params["viaDrill"] * scale))
                custom_values_set = True

            # KiCAD 9.0: Activate custom track/via values so they become the current values
            if custom_values_set:
                design_settings.UseCustomTrackViaSize(True)

            # Set micro via settings (use properties - methods removed in KiCAD 9.0)
            if "microViaDiameter" in params:
                design_settings.m_MicroViasMinSize = int(params["microViaDiameter"] * scale)
            if "microViaDrill" in params:
                design_settings.m_MicroViasMinDrill = int(params["microViaDrill"] * scale)

            # Set minimum values
            if "minTrackWidth" in params:
                design_settings.m_TrackMinWidth = int(params["minTrackWidth"] * scale)
            if "minViaDiameter" in params:
                design_settings.m_ViasMinSize = int(params["minViaDiameter"] * scale)

            # KiCAD 9.0: m_ViasMinDrill removed - use m_MinThroughDrill instead
            if "minViaDrill" in params:
                design_settings.m_MinThroughDrill = int(params["minViaDrill"] * scale)

            if "minMicroViaDiameter" in params:
                design_settings.m_MicroViasMinSize = int(params["minMicroViaDiameter"] * scale)
            if "minMicroViaDrill" in params:
                design_settings.m_MicroViasMinDrill = int(params["minMicroViaDrill"] * scale)

            # KiCAD 9.0: m_MinHoleDiameter removed - use m_MinThroughDrill
            if "minHoleDiameter" in params:
                design_settings.m_MinThroughDrill = int(params["minHoleDiameter"] * scale)

            # KiCAD 9.0: Added hole clearance settings
            if "holeClearance" in params:
                design_settings.m_HoleClearance = int(params["holeClearance"] * scale)
            if "holeToHoleMin" in params:
                design_settings.m_HoleToHoleMin = int(params["holeToHoleMin"] * scale)

            # Build response with KiCAD 9.0 compatible properties
            # After UseCustomTrackViaSize(True), GetCurrent* returns the custom values
            response_rules = {
                "clearance": design_settings.m_MinClearance / scale,
                "trackWidth": design_settings.GetCurrentTrackWidth() / scale,
                "viaDiameter": design_settings.GetCurrentViaSize() / scale,
                "viaDrill": design_settings.GetCurrentViaDrill() / scale,
                "microViaDiameter": design_settings.m_MicroViasMinSize / scale,
                "microViaDrill": design_settings.m_MicroViasMinDrill / scale,
                "minTrackWidth": design_settings.m_TrackMinWidth / scale,
                "minViaDiameter": design_settings.m_ViasMinSize / scale,
                "minThroughDrill": design_settings.m_MinThroughDrill / scale,
                "minMicroViaDiameter": design_settings.m_MicroViasMinSize / scale,
                "minMicroViaDrill": design_settings.m_MicroViasMinDrill / scale,
                "holeClearance": design_settings.m_HoleClearance / scale,
                "holeToHoleMin": design_settings.m_HoleToHoleMin / scale,
                "viasMinAnnularWidth": design_settings.m_ViasMinAnnularWidth / scale,
            }

            return {
                "success": True,
                "message": "Updated design rules",
                "rules": response_rules,
            }

        except Exception as e:
            logger.error(f"Error setting design rules: {str(e)}")
            return {
                "success": False,
                "message": "Failed to set design rules",
                "errorDetails": str(e),
            }

    def get_design_rules(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get current design rules - KiCAD 9.0 compatible"""
        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first",
                }

            design_settings = self.board.GetDesignSettings()
            scale = 1000000  # nm to mm

            # Build rules dict with KiCAD 9.0 compatible properties
            rules = {
                # Core clearance and track settings
                "clearance": design_settings.m_MinClearance / scale,
                "trackWidth": design_settings.GetCurrentTrackWidth() / scale,
                "minTrackWidth": design_settings.m_TrackMinWidth / scale,
                # Via settings (current values from methods)
                "viaDiameter": design_settings.GetCurrentViaSize() / scale,
                "viaDrill": design_settings.GetCurrentViaDrill() / scale,
                # Via minimum values
                "minViaDiameter": design_settings.m_ViasMinSize / scale,
                "viasMinAnnularWidth": design_settings.m_ViasMinAnnularWidth / scale,
                # Micro via settings
                "microViaDiameter": design_settings.m_MicroViasMinSize / scale,
                "microViaDrill": design_settings.m_MicroViasMinDrill / scale,
                "minMicroViaDiameter": design_settings.m_MicroViasMinSize / scale,
                "minMicroViaDrill": design_settings.m_MicroViasMinDrill / scale,
                # KiCAD 9.0: Hole and drill settings (replaces removed m_ViasMinDrill and m_MinHoleDiameter)
                "minThroughDrill": design_settings.m_MinThroughDrill / scale,
                "holeClearance": design_settings.m_HoleClearance / scale,
                "holeToHoleMin": design_settings.m_HoleToHoleMin / scale,
                # Other constraints
                "copperEdgeClearance": design_settings.m_CopperEdgeClearance / scale,
                "silkClearance": design_settings.m_SilkClearance / scale,
            }

            return {"success": True, "rules": rules}

        except Exception as e:
            logger.error(f"Error getting design rules: {str(e)}")
            return {
                "success": False,
                "message": "Failed to get design rules",
                "errorDetails": str(e),
            }

    def run_drc(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Run Design Rule Check using kicad-cli"""
        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first",
                }

            report_path = params.get("reportPath")

            # Get the board file path
            board_file = self.board.GetFileName()
            if not board_file or not os.path.exists(board_file):
                return {
                    "success": False,
                    "message": "Board file not found",
                    "errorDetails": "Cannot run DRC without a saved board file",
                }

            # Find kicad-cli executable
            kicad_cli = self._find_kicad_cli()
            if not kicad_cli:
                return {
                    "success": False,
                    "message": "kicad-cli not found",
                    "errorDetails": "KiCAD CLI tool not found in system. Install KiCAD 8.0+ or set PATH.",
                }

            if self._cli_supports_subcommand(kicad_cli, "pcb", "drc"):
                with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tmp:
                    json_output = tmp.name

                try:
                    cmd = [
                        kicad_cli,
                        "pcb",
                        "drc",
                        "--format",
                        "json",
                        "--output",
                        json_output,
                        "--units",
                        "mm",
                        board_file,
                    ]

                    logger.info(f"Running DRC command: {' '.join(cmd)}")

                    result = subprocess.run(
                        cmd,
                        capture_output=True,
                        text=True,
                        timeout=600,
                    )

                    if result.returncode != 0:
                        logger.error(f"DRC command failed: {result.stderr}")
                        return {
                            "success": False,
                            "message": "DRC command failed",
                            "errorDetails": result.stderr,
                        }

                    with open(json_output, "r", encoding="utf-8") as f:
                        drc_data = json.load(f)

                    violations = []
                    violation_counts: dict[str, int] = {}
                    severity_counts = {"error": 0, "warning": 0, "info": 0}

                    for violation in drc_data.get("violations", []):
                        vtype = violation.get("type", "unknown")
                        vseverity = str(violation.get("severity", "error")).lower()
                        items = violation.get("items", [])
                        loc_x, loc_y = 0, 0
                        if items and "pos" in items[0]:
                            loc_x = items[0]["pos"].get("x", 0)
                            loc_y = items[0]["pos"].get("y", 0)

                        violations.append(
                            {
                                "type": vtype,
                                "severity": vseverity,
                                "message": violation.get("description", ""),
                                "location": {
                                    "x": loc_x,
                                    "y": loc_y,
                                    "unit": "mm",
                                },
                            }
                        )
                        violation_counts[vtype] = violation_counts.get(vtype, 0) + 1
                        if vseverity not in severity_counts:
                            severity_counts[vseverity] = 0
                        severity_counts[vseverity] += 1

                    summary = {
                        "total": len(violations),
                        "by_severity": severity_counts,
                        "by_type": violation_counts,
                    }
                    violations_file = self._write_violations_file(
                        board_file,
                        violations,
                        summary,
                        timestamp=drc_data.get("date", "unknown"),
                    )

                    if report_path:
                        report_path = os.path.abspath(os.path.expanduser(report_path))
                        cmd_report = [
                            kicad_cli,
                            "pcb",
                            "drc",
                            "--format",
                            "report",
                            "--output",
                            report_path,
                            "--units",
                            "mm",
                            board_file,
                        ]
                        subprocess.run(cmd_report, capture_output=True, timeout=600)

                    return {
                        "success": True,
                        "message": f"Found {len(violations)} DRC violations",
                        "summary": summary,
                        "violationsFile": violations_file,
                        "reportPath": report_path if report_path else None,
                    }

                finally:
                    if os.path.exists(json_output):
                        os.unlink(json_output)

            logger.info(
                "Installed kicad-cli does not expose 'pcb drc'; falling back to pcbnew.WriteDRCReport"
            )
            report_tmp = None
            if report_path:
                report_path = os.path.abspath(os.path.expanduser(report_path))
                report_output = report_path
            else:
                report_tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".rpt", delete=False)
                report_output = report_tmp.name
                report_tmp.close()

            try:
                ok = pcbnew.WriteDRCReport(
                    self.board,
                    report_output,
                    pcbnew.EDA_UNITS_MILLIMETRES,
                    True,
                )
                if not ok or not os.path.exists(report_output):
                    return {
                        "success": False,
                        "message": "DRC fallback failed",
                        "errorDetails": "pcbnew.WriteDRCReport did not produce a report",
                    }

                report_text = Path(report_output).read_text(encoding="utf-8", errors="replace")
                violations, parsed_summary = self._parse_drc_report_text(report_text)
                summary = {
                    "total": len(violations),
                    "by_severity": parsed_summary.get("by_severity", {}),
                    "by_type": parsed_summary.get("by_type", {}),
                }
                violations_file = self._write_violations_file(
                    board_file,
                    violations,
                    summary,
                )
                return {
                    "success": True,
                    "message": f"Found {len(violations)} DRC violations",
                    "summary": summary,
                    "violationsFile": violations_file,
                    "reportPath": report_path if report_path else None,
                    "backend": "pcbnew-report",
                }
            finally:
                if report_tmp is not None and os.path.exists(report_output):
                    os.unlink(report_output)

        except subprocess.TimeoutExpired:
            logger.error("DRC command timed out")
            return {
                "success": False,
                "message": "DRC command timed out",
                "errorDetails": "Command took longer than 600 seconds (10 minutes)",
            }
        except Exception as e:
            logger.error(f"Error running DRC: {str(e)}")
            return {
                "success": False,
                "message": "Failed to run DRC",
                "errorDetails": str(e),
            }

    def _find_kicad_cli(self) -> Optional[str]:
        """Find kicad-cli executable"""
        import platform
        import shutil

        # Try system PATH first
        cli_name = "kicad-cli.exe" if platform.system() == "Windows" else "kicad-cli"
        cli_path = shutil.which(cli_name)
        if cli_path:
            return cli_path

        # Try common installation paths (version-specific)
        if platform.system() == "Windows":
            common_paths = [
                r"C:\Program Files\KiCad\10.0\bin\kicad-cli.exe",
                r"C:\Program Files\KiCad\9.0\bin\kicad-cli.exe",
                r"C:\Program Files\KiCad\8.0\bin\kicad-cli.exe",
                r"C:\Program Files (x86)\KiCad\10.0\bin\kicad-cli.exe",
                r"C:\Program Files (x86)\KiCad\9.0\bin\kicad-cli.exe",
                r"C:\Program Files (x86)\KiCad\8.0\bin\kicad-cli.exe",
                r"C:\Program Files\KiCad\bin\kicad-cli.exe",
            ]
            for path in common_paths:
                if os.path.exists(path):
                    return path
        elif platform.system() == "Darwin":  # macOS
            common_paths = [
                "/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli",
                "/usr/local/bin/kicad-cli",
            ]
            for path in common_paths:
                if os.path.exists(path):
                    return path
        else:  # Linux
            common_paths = [
                "/usr/bin/kicad-cli",
                "/usr/local/bin/kicad-cli",
            ]
            for path in common_paths:
                if os.path.exists(path):
                    return path

        return None

    def get_drc_violations(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Get list of DRC violations

        Note: This command internally uses run_drc() which calls kicad-cli.
        The old BOARD.GetDRCMarkers() API was removed in KiCAD 9.0.
        This implementation provides backward compatibility by parsing kicad-cli output.
        """
        import json

        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first",
                }

            severity = params.get("severity", "all")

            # Run DRC using kicad-cli (this saves violations to JSON file)
            drc_result = self.run_drc({})

            if not drc_result.get("success"):
                return drc_result  # Return the error from run_drc

            # Read violations from the saved JSON file
            violations_file = drc_result.get("violationsFile")
            if not violations_file or not os.path.exists(violations_file):
                return {
                    "success": False,
                    "message": "Violations file not found",
                    "errorDetails": "run_drc did not create violations file",
                }

            # Load violations from file
            with open(violations_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            all_violations = data.get("violations", [])

            # Filter by severity if specified
            if severity != "all":
                filtered_violations = [v for v in all_violations if v.get("severity") == severity]
            else:
                filtered_violations = all_violations

            return {
                "success": True,
                "violations": filtered_violations,
                "violationsFile": violations_file,  # Include file path for reference
            }

        except Exception as e:
            logger.error(f"Error getting DRC violations: {str(e)}")
            return {
                "success": False,
                "message": "Failed to get DRC violations",
                "errorDetails": str(e),
            }
