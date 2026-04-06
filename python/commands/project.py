"""
Project-related command implementations for KiCAD interface
"""

import logging
import os
import shutil
from typing import Any, Dict, Optional

import pcbnew  # type: ignore

logger = logging.getLogger("kicad_interface")

DEFAULT_BOARD_WIDTH_MM = 100.0
DEFAULT_BOARD_HEIGHT_MM = 100.0
DEFAULT_COPPER_LAYERS = 2


class ProjectCommands:
    """Handles project-related KiCAD operations"""

    def __init__(self, board: Optional[pcbnew.BOARD] = None):
        """Initialize with optional board instance"""
        self.board = board

    def create_project(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new KiCAD project"""
        try:
            # Accept both 'name' (from MCP tool) and 'projectName' (legacy)
            project_name = params.get("name") or params.get("projectName", "New_Project")
            path = params.get("path", os.getcwd())
            template = params.get("template")
            board_width_mm = float(params.get("boardWidthMm", DEFAULT_BOARD_WIDTH_MM))
            board_height_mm = float(params.get("boardHeightMm", DEFAULT_BOARD_HEIGHT_MM))
            board_unit = params.get("boardUnit", "mm")
            requested_copper_layers = params.get("copperLayers")

            if board_width_mm <= 0 or board_height_mm <= 0:
                return {
                    "success": False,
                    "message": "Invalid board dimensions",
                    "errorDetails": "boardWidthMm and boardHeightMm must be positive numbers",
                }
            if board_unit not in {"mm", "inch"}:
                return {
                    "success": False,
                    "message": "Invalid board unit",
                    "errorDetails": "boardUnit must be 'mm' or 'inch'",
                }

            if requested_copper_layers is None:
                copper_layers = DEFAULT_COPPER_LAYERS
            else:
                copper_layers = int(requested_copper_layers)

            if copper_layers < 2 or copper_layers % 2 != 0:
                return {
                    "success": False,
                    "message": "Invalid copper layer count",
                    "errorDetails": "copperLayers must be an even number greater than or equal to 2",
                }

            # Generate the full project path
            project_path = os.path.join(path, project_name)
            if not project_path.endswith(".kicad_pro"):
                project_path += ".kicad_pro"

            # Create project directory if it doesn't exist
            os.makedirs(os.path.dirname(project_path), exist_ok=True)

            # Create a new board
            board = pcbnew.BOARD()

            # Set project properties
            board.GetTitleBlock().SetTitle(project_name)

            # Set current date with proper parameter
            from datetime import datetime

            current_date = datetime.now().strftime("%Y-%m-%d")
            board.GetTitleBlock().SetDate(current_date)

            # If template is specified, try to load it
            if template:
                template_path = os.path.expanduser(template)
                if os.path.exists(template_path):
                    template_board = pcbnew.LoadBoard(template_path)
                    # Copy settings from template
                    board.SetDesignSettings(template_board.GetDesignSettings())
                    board.SetLayerStack(template_board.GetLayerStack())

            # For blank projects, give LLM sessions a routable default workspace.
            if not template or requested_copper_layers is not None:
                board.SetCopperLayerCount(copper_layers)

            if not template:
                from commands.board.outline import BoardOutlineCommands

                outline_commands = BoardOutlineCommands(board)
                outline_result = outline_commands.add_board_outline(
                    {
                        "shape": "rectangle",
                        "params": {
                            "x": 0,
                            "y": 0,
                            "width": board_width_mm,
                            "height": board_height_mm,
                            "unit": board_unit,
                        },
                    }
                )
                if not outline_result.get("success"):
                    return outline_result

            # Save the board
            board_path = project_path.replace(".kicad_pro", ".kicad_pcb")
            board.SetFileName(board_path)
            pcbnew.SaveBoard(board_path, board)

            # Create schematic from template (use expanded template with symbol definitions)
            schematic_path = project_path.replace(".kicad_pro", ".kicad_sch")
            template_sch_path = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                "..",
                "templates",
                "template_with_symbols_expanded.kicad_sch",
            )

            if os.path.exists(template_sch_path):
                # Copy template schematic
                shutil.copy(template_sch_path, schematic_path)

                # Regenerate UUID to ensure uniqueness for each created project
                import re
                import uuid as uuid_module

                with open(schematic_path, "r", encoding="utf-8") as f:
                    content = f.read()
                new_uuid = str(uuid_module.uuid4())
                content = re.sub(
                    r"\(uuid [0-9a-fA-F-]+\)",
                    f"(uuid {new_uuid})",
                    content,
                    count=1,  # Only replace first (schematic) UUID
                )
                with open(schematic_path, "w", encoding="utf-8", newline="\n") as f:
                    f.write(content)

                logger.info(f"Created schematic from template: {schematic_path}")
            else:
                # Fallback: create minimal schematic
                logger.warning(
                    f"Template not found at {template_sch_path}, creating minimal schematic"
                )
                import uuid as uuid_module

                schematic_uuid = str(uuid_module.uuid4())
                with open(schematic_path, "w", encoding="utf-8", newline="\n") as f:
                    f.write('(kicad_sch (version 20250114) (generator "KiCAD-MCP-Server")\n\n')
                    f.write(f"  (uuid {schematic_uuid})\n\n")
                    f.write('  (paper "A4")\n\n')
                    f.write("  (lib_symbols\n  )\n\n")
                    f.write('  (sheet_instances\n    (path "/" (page "1"))\n  )\n')
                    f.write(")\n")

            # Create project file with schematic reference
            with open(project_path, "w") as f:
                f.write("{\n")
                f.write('  "board": {\n')
                f.write(f'    "filename": "{os.path.basename(board_path)}"\n')
                f.write("  },\n")
                f.write('  "sheets": [\n')
                f.write(f'    ["root", "{os.path.basename(schematic_path)}"]\n')
                f.write("  ]\n")
                f.write("}\n")

            self.board = board

            return {
                "success": True,
                "message": f"Created project: {project_name}",
                "project": {
                    "name": project_name,
                    "path": project_path,
                    "boardPath": board_path,
                    "schematicPath": schematic_path,
                    "defaults": {
                        "boardWidthMm": board_width_mm,
                        "boardHeightMm": board_height_mm,
                        "boardUnit": board_unit,
                        "copperLayers": copper_layers if not template or requested_copper_layers is not None else None,
                    },
                },
            }

        except Exception as e:
            logger.error(f"Error creating project: {str(e)}")
            return {
                "success": False,
                "message": "Failed to create project",
                "errorDetails": str(e),
            }

    def open_project(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Open an existing KiCAD project"""
        try:
            filename = params.get("filename")
            if not filename:
                return {
                    "success": False,
                    "message": "No filename provided",
                    "errorDetails": "The filename parameter is required",
                }

            # Expand user path and make absolute
            filename = os.path.abspath(os.path.expanduser(filename))

            # If it's a project file, get the board file
            if filename.endswith(".kicad_pro"):
                board_path = filename.replace(".kicad_pro", ".kicad_pcb")
            else:
                board_path = filename

            # Load the board
            board = pcbnew.LoadBoard(board_path)
            self.board = board

            return {
                "success": True,
                "message": f"Opened project: {os.path.basename(board_path)}",
                "project": {
                    "name": os.path.splitext(os.path.basename(board_path))[0],
                    "path": filename,
                    "boardPath": board_path,
                },
            }

        except Exception as e:
            logger.error(f"Error opening project: {str(e)}")
            return {
                "success": False,
                "message": "Failed to open project",
                "errorDetails": str(e),
            }

    def save_project(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Save the current KiCAD project"""
        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first",
                }

            filename = params.get("filename")
            if filename:
                # Save to new location
                filename = os.path.abspath(os.path.expanduser(filename))
                self.board.SetFileName(filename)

            # Save the board
            pcbnew.SaveBoard(self.board.GetFileName(), self.board)

            return {
                "success": True,
                "message": f"Saved project to: {self.board.GetFileName()}",
                "project": {
                    "name": os.path.splitext(os.path.basename(self.board.GetFileName()))[0],
                    "path": self.board.GetFileName(),
                },
            }

        except Exception as e:
            logger.error(f"Error saving project: {str(e)}")
            return {
                "success": False,
                "message": "Failed to save project",
                "errorDetails": str(e),
            }

    def get_project_info(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get information about the current project"""
        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first",
                }

            title_block = self.board.GetTitleBlock()
            filename = self.board.GetFileName()

            return {
                "success": True,
                "project": {
                    "name": os.path.splitext(os.path.basename(filename))[0],
                    "path": filename,
                    "title": title_block.GetTitle(),
                    "date": title_block.GetDate(),
                    "revision": title_block.GetRevision(),
                    "company": title_block.GetCompany(),
                    "comment1": title_block.GetComment(0),
                    "comment2": title_block.GetComment(1),
                    "comment3": title_block.GetComment(2),
                    "comment4": title_block.GetComment(3),
                },
            }

        except Exception as e:
            logger.error(f"Error getting project info: {str(e)}")
            return {
                "success": False,
                "message": "Failed to get project information",
                "errorDetails": str(e),
            }
