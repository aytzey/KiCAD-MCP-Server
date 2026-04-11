"""
Schematic handler methods extracted from KiCADInterface.

All methods operate on schematic files via params["schematicPath"] and do not
touch the PCB board object.
"""

import json
import logging
import os

from commands.connection_schematic import ConnectionManager
from commands.schematic import SchematicManager

logger = logging.getLogger("kicad_interface")


class SchematicHandlers:
    """Encapsulates all schematic _handle_* logic, decoupled from the board."""

    def __init__(self, design_rule_commands=None):
        self.design_rule_commands = design_rule_commands

    # ------------------------------------------------------------------ #
    #  Schematic CRUD                                                      #
    # ------------------------------------------------------------------ #

    def create_schematic(self, params):
        """Create a new schematic"""
        logger.info("Creating schematic")
        try:
            # Support multiple parameter naming conventions for compatibility:
            # - TypeScript tools use: name, path
            # - Python schema uses: filename, title
            # - Legacy uses: projectName, path, metadata
            project_name = params.get("projectName") or params.get("name") or params.get("title")

            # Handle filename parameter - it may contain full path
            filename = params.get("filename")
            if filename:
                # If filename provided, extract name and path from it
                if filename.endswith(".kicad_sch"):
                    filename = filename[:-10]  # Remove .kicad_sch extension
                path = os.path.dirname(filename) or "."
                project_name = project_name or os.path.basename(filename)
            else:
                path = params.get("path", ".")
            metadata = params.get("metadata", {})

            if not project_name:
                return {
                    "success": False,
                    "message": "Schematic name is required. Provide 'name', 'projectName', or 'filename' parameter.",
                }

            schematic = SchematicManager.create_schematic(project_name, metadata)
            file_path = f"{path}/{project_name}.kicad_sch"
            success = SchematicManager.save_schematic(schematic, file_path)

            return {"success": success, "file_path": file_path}
        except Exception as e:
            logger.error(f"Error creating schematic: {str(e)}")
            return {"success": False, "message": str(e)}

    def load_schematic(self, params):
        """Load an existing schematic"""
        logger.info("Loading schematic")
        try:
            filename = params.get("filename")

            if not filename:
                return {"success": False, "message": "Filename is required"}

            schematic = SchematicManager.load_schematic(filename)
            success = schematic is not None

            if success:
                metadata = SchematicManager.get_schematic_metadata(schematic)
                return {"success": success, "metadata": metadata}
            else:
                return {"success": False, "message": "Failed to load schematic"}
        except Exception as e:
            logger.error(f"Error loading schematic: {str(e)}")
            return {"success": False, "message": str(e)}

    def add_schematic_component(self, params):
        """Add a component to a schematic using text-based injection (no sexpdata)"""
        logger.info("Adding component to schematic")
        try:
            from pathlib import Path

            from commands.dynamic_symbol_loader import DynamicSymbolLoader

            schematic_path = params.get("schematicPath")
            component = params.get("component", {})

            if not schematic_path:
                return {"success": False, "message": "Schematic path is required"}
            if not component:
                return {"success": False, "message": "Component definition is required"}

            comp_type = component.get("type", "R")
            library = component.get("library", "Device")
            reference = component.get("reference", "X?")
            value = component.get("value", comp_type)
            footprint = component.get("footprint", "")
            x = component.get("x", 0)
            y = component.get("y", 0)
            snap_to_grid = component.get("snapToGrid", True)
            schematic_grid = component.get("grid", 1.27)
            refresh_from_library = component.get("refreshFromLibrary", True)

            # Derive project path from schematic path for project-local library resolution
            schematic_file = Path(schematic_path)
            derived_project_path = schematic_file.parent

            loader = DynamicSymbolLoader(project_path=derived_project_path)
            loader.add_component(
                schematic_file,
                library,
                comp_type,
                reference=reference,
                value=value,
                footprint=footprint,
                x=x,
                y=y,
                project_path=derived_project_path,
                snap_to_grid=snap_to_grid,
                schematic_grid=schematic_grid,
                refresh_symbol_definition=refresh_from_library,
            )

            return {
                "success": True,
                "component_reference": reference,
                "symbol_source": f"{library}:{comp_type}",
                "position": {
                    "x": x,
                    "y": y,
                    "snapToGrid": snap_to_grid,
                    "grid": schematic_grid,
                },
            }
        except Exception as e:
            logger.error(f"Error adding component to schematic: {str(e)}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def delete_schematic_component(self, params):
        """Remove a placed symbol from a schematic using text-based manipulation (no skip writes)"""
        logger.info("Deleting schematic component")
        try:
            import re
            from pathlib import Path

            schematic_path = params.get("schematicPath")
            reference = params.get("reference")

            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}
            if not reference:
                return {"success": False, "message": "reference is required"}

            sch_file = Path(schematic_path)
            if not sch_file.exists():
                return {
                    "success": False,
                    "message": f"Schematic not found: {schematic_path}",
                }

            with open(sch_file, "r", encoding="utf-8") as f:
                content = f.read()

            def find_matching_paren(s, start):
                """Find the closing paren matching the opening paren at start."""
                depth = 0
                i = start
                while i < len(s):
                    if s[i] == "(":
                        depth += 1
                    elif s[i] == ")":
                        depth -= 1
                        if depth == 0:
                            return i
                    i += 1
                return -1

            # Skip lib_symbols section
            lib_sym_pos = content.find("(lib_symbols")
            lib_sym_end = find_matching_paren(content, lib_sym_pos) if lib_sym_pos >= 0 else -1

            # Find ALL placed symbol blocks matching the reference (handles duplicates).
            # Use content-string search so multi-line KiCAD format is handled correctly:
            # KiCAD writes (symbol\n\t\t(lib_id "...") across two lines, which a
            # line-by-line regex would never match.
            blocks_to_delete = []  # list of (char_start, char_end) into content
            search_start = 0
            pattern = re.compile(r'\(symbol\s+\(lib_id\s+"')
            while True:
                m = pattern.search(content, search_start)
                if not m:
                    break
                pos = m.start()
                # Skip blocks inside lib_symbols
                if lib_sym_pos >= 0 and lib_sym_pos <= pos <= lib_sym_end:
                    search_start = lib_sym_end + 1
                    continue
                end = find_matching_paren(content, pos)
                if end < 0:
                    search_start = pos + 1
                    continue
                block_text = content[pos : end + 1]
                if re.search(
                    r'\(property\s+"Reference"\s+"' + re.escape(reference) + r'"',
                    block_text,
                ):
                    blocks_to_delete.append((pos, end))
                search_start = end + 1

            if not blocks_to_delete:
                return {
                    "success": False,
                    "message": f"Component '{reference}' not found in schematic (note: this tool removes schematic symbols, use delete_component for PCB footprints)",
                }

            # Delete from back to front to preserve character offsets
            for b_start, b_end in sorted(blocks_to_delete, reverse=True):
                # Include any leading newline/whitespace before the block
                trim_start = b_start
                while trim_start > 0 and content[trim_start - 1] in (" ", "\t"):
                    trim_start -= 1
                if trim_start > 0 and content[trim_start - 1] == "\n":
                    trim_start -= 1
                content = content[:trim_start] + content[b_end + 1 :]

            with open(sch_file, "w", encoding="utf-8") as f:
                f.write(content)

            deleted_count = len(blocks_to_delete)
            logger.info(f"Deleted {deleted_count} instance(s) of {reference} from {sch_file.name}")
            return {
                "success": True,
                "reference": reference,
                "deleted_count": deleted_count,
                "schematic": str(sch_file),
            }

        except Exception as e:
            logger.error(f"Error deleting schematic component: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def edit_schematic_component(self, params):
        """Update properties of a placed symbol in a schematic (footprint, value, reference).
        Uses text-based in-place editing – preserves position, UUID and all other fields.
        """
        logger.info("Editing schematic component")
        try:
            import re
            from pathlib import Path

            schematic_path = params.get("schematicPath")
            reference = params.get("reference")
            new_footprint = params.get("footprint")
            new_value = params.get("value")
            new_reference = params.get("newReference")
            field_positions = params.get(
                "fieldPositions"
            )  # dict: {"Reference": {"x": 1, "y": 2, "angle": 0}}

            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}
            if not reference:
                return {"success": False, "message": "reference is required"}
            if not any(
                [
                    new_footprint is not None,
                    new_value is not None,
                    new_reference is not None,
                    field_positions is not None,
                ]
            ):
                return {
                    "success": False,
                    "message": "At least one of footprint, value, newReference, or fieldPositions must be provided",
                }

            sch_file = Path(schematic_path)
            if not sch_file.exists():
                return {
                    "success": False,
                    "message": f"Schematic not found: {schematic_path}",
                }

            with open(sch_file, "r", encoding="utf-8") as f:
                content = f.read()

            def find_matching_paren(s, start):
                """Find the position of the closing paren matching the opening paren at start."""
                depth = 0
                i = start
                while i < len(s):
                    if s[i] == "(":
                        depth += 1
                    elif s[i] == ")":
                        depth -= 1
                        if depth == 0:
                            return i
                    i += 1
                return -1

            # Skip lib_symbols section
            lib_sym_pos = content.find("(lib_symbols")
            lib_sym_end = find_matching_paren(content, lib_sym_pos) if lib_sym_pos >= 0 else -1

            # Find placed symbol blocks that match the reference
            # Search for (symbol (lib_id "...") ... (property "Reference" "<ref>" ...) ...)
            block_start = block_end = None
            search_start = 0
            pattern = re.compile(r'\(symbol\s+\(lib_id\s+"')
            while True:
                m = pattern.search(content, search_start)
                if not m:
                    break
                pos = m.start()
                # Skip if inside lib_symbols section
                if lib_sym_pos >= 0 and lib_sym_pos <= pos <= lib_sym_end:
                    search_start = lib_sym_end + 1
                    continue
                end = find_matching_paren(content, pos)
                if end < 0:
                    search_start = pos + 1
                    continue
                block_text = content[pos : end + 1]
                if re.search(
                    r'\(property\s+"Reference"\s+"' + re.escape(reference) + r'"',
                    block_text,
                ):
                    block_start, block_end = pos, end
                    break
                search_start = end + 1

            if block_start is None:
                return {
                    "success": False,
                    "message": f"Component '{reference}' not found in schematic",
                }

            # Apply property replacements within the found block
            block_text = content[block_start : block_end + 1]
            if new_footprint is not None:
                block_text = re.sub(
                    r'(\(property\s+"Footprint"\s+)"[^"]*"',
                    rf'\1"{new_footprint}"',
                    block_text,
                )
            if new_value is not None:
                block_text = re.sub(
                    r'(\(property\s+"Value"\s+)"[^"]*"', rf'\1"{new_value}"', block_text
                )
            if new_reference is not None:
                block_text = re.sub(
                    r'(\(property\s+"Reference"\s+)"[^"]*"',
                    rf'\1"{new_reference}"',
                    block_text,
                )
            if field_positions is not None:
                for field_name, pos in field_positions.items():
                    x = pos.get("x", 0)
                    y = pos.get("y", 0)
                    angle = pos.get("angle", 0)
                    block_text = re.sub(
                        r'(\(property\s+"'
                        + re.escape(field_name)
                        + r'"\s+"[^"]*"\s+)\(at\s+[\d\.\-]+\s+[\d\.\-]+\s+[\d\.\-]+\s*\)',
                        rf"\1(at {x} {y} {angle})",
                        block_text,
                    )

            content = content[:block_start] + block_text + content[block_end + 1 :]

            with open(sch_file, "w", encoding="utf-8") as f:
                f.write(content)

            changes = {
                k: v
                for k, v in {
                    "footprint": new_footprint,
                    "value": new_value,
                    "reference": new_reference,
                }.items()
                if v is not None
            }
            if field_positions is not None:
                changes["fieldPositions"] = field_positions
            logger.info(f"Edited schematic component {reference}: {changes}")
            return {"success": True, "reference": reference, "updated": changes}

        except Exception as e:
            logger.error(f"Error editing schematic component: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def get_schematic_component(self, params):
        """Return full component info: position and all field values with their (at x y angle) positions."""
        logger.info("Getting schematic component info")
        try:
            import re
            from pathlib import Path

            schematic_path = params.get("schematicPath")
            reference = params.get("reference")

            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}
            if not reference:
                return {"success": False, "message": "reference is required"}

            sch_file = Path(schematic_path)
            if not sch_file.exists():
                return {
                    "success": False,
                    "message": f"Schematic not found: {schematic_path}",
                }

            with open(sch_file, "r", encoding="utf-8") as f:
                content = f.read()

            def find_matching_paren(s, start):
                depth = 0
                i = start
                while i < len(s):
                    if s[i] == "(":
                        depth += 1
                    elif s[i] == ")":
                        depth -= 1
                        if depth == 0:
                            return i
                    i += 1
                return -1

            # Skip lib_symbols section
            lib_sym_pos = content.find("(lib_symbols")
            lib_sym_end = find_matching_paren(content, lib_sym_pos) if lib_sym_pos >= 0 else -1

            # Find the placed symbol block for this reference
            block_start = block_end = None
            search_start = 0
            pattern = re.compile(r'\(symbol\s+\(lib_id\s+"')
            while True:
                m = pattern.search(content, search_start)
                if not m:
                    break
                pos = m.start()
                if lib_sym_pos >= 0 and lib_sym_pos <= pos <= lib_sym_end:
                    search_start = lib_sym_end + 1
                    continue
                end = find_matching_paren(content, pos)
                if end < 0:
                    search_start = pos + 1
                    continue
                block_text = content[pos : end + 1]
                if re.search(
                    r'\(property\s+"Reference"\s+"' + re.escape(reference) + r'"',
                    block_text,
                ):
                    block_start, block_end = pos, end
                    break
                search_start = end + 1

            if block_start is None:
                return {
                    "success": False,
                    "message": f"Component '{reference}' not found in schematic",
                }

            block_text = content[block_start : block_end + 1]

            # Extract component position: first (at x y angle) in the symbol header line
            comp_at = re.search(
                r'\(symbol\s+\(lib_id\s+"[^"]*"\s*\)\s+\(at\s+([\d\.\-]+)\s+([\d\.\-]+)\s+([\d\.\-]+)\s*\)',
                block_text,
            )
            if comp_at:
                comp_pos = {
                    "x": float(comp_at.group(1)),
                    "y": float(comp_at.group(2)),
                    "angle": float(comp_at.group(3)),
                }
            else:
                comp_pos = None

            # Extract all properties with their at positions
            prop_pattern = re.compile(
                r'\(property\s+"([^"]*)"\s+"([^"]*)"\s+\(at\s+([\d\.\-]+)\s+([\d\.\-]+)\s+([\d\.\-]+)\s*\)'
            )
            fields = {}
            for m in prop_pattern.finditer(block_text):
                name, value, x, y, angle = (
                    m.group(1),
                    m.group(2),
                    m.group(3),
                    m.group(4),
                    m.group(5),
                )
                fields[name] = {
                    "value": value,
                    "x": float(x),
                    "y": float(y),
                    "angle": float(angle),
                }

            return {
                "success": True,
                "reference": reference,
                "position": comp_pos,
                "fields": fields,
            }

        except Exception as e:
            logger.error(f"Error getting schematic component: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    # ------------------------------------------------------------------ #
    #  Wiring                                                              #
    # ------------------------------------------------------------------ #

    def add_schematic_wire(self, params):
        """Add a wire to a schematic using WireManager, with optional pin snapping"""
        logger.info("Adding wire to schematic")
        try:
            from pathlib import Path

            from commands.wire_manager import WireManager

            schematic_path = params.get("schematicPath")
            points = params.get("waypoints")
            properties = params.get("properties", {})
            snap_to_pins = params.get("snapToPins", True)
            snap_tolerance = params.get("snapTolerance", 1.0)

            if not schematic_path:
                return {"success": False, "message": "Schematic path is required"}
            if not points or len(points) < 2:
                return {
                    "success": False,
                    "message": "At least 2 waypoints are required",
                }

            # Make a mutable copy of points
            points = [list(p) for p in points]

            # Pin snapping: adjust first and last endpoints to nearest pin
            snapped_info = []
            if snap_to_pins:
                from commands.pin_locator import PinLocator

                locator = PinLocator()
                sch_path = Path(schematic_path)

                # Load schematic to iterate all symbols
                from skip import Schematic as SkipSchematic

                sch = SkipSchematic(str(sch_path))

                # Collect all pin locations: list of (ref, pin_num, [x, y])
                all_pins = []
                for symbol in sch.symbol:
                    if not hasattr(symbol.property, "Reference"):
                        continue
                    ref = symbol.property.Reference.value
                    if ref.startswith("_TEMPLATE"):
                        continue
                    pin_locs = locator.get_all_symbol_pins(sch_path, ref)
                    for pin_num, coords in pin_locs.items():
                        all_pins.append((ref, pin_num, coords))

                def find_nearest_pin(point, tolerance):
                    """Find the nearest pin within tolerance of a point."""
                    best = None
                    best_dist = tolerance
                    for ref, pin_num, coords in all_pins:
                        dx = point[0] - coords[0]
                        dy = point[1] - coords[1]
                        dist = (dx * dx + dy * dy) ** 0.5
                        if dist <= best_dist:
                            best_dist = dist
                            best = (ref, pin_num, coords)
                    return best

                # Snap first endpoint
                match = find_nearest_pin(points[0], snap_tolerance)
                if match:
                    ref, pin_num, coords = match
                    logger.info(
                        f"Snapped start point {points[0]} -> {coords} (pin {ref}/{pin_num})"
                    )
                    snapped_info.append(
                        f"start snapped to {ref}/{pin_num} at [{coords[0]}, {coords[1]}]"
                    )
                    points[0] = list(coords)

                # Snap last endpoint
                match = find_nearest_pin(points[-1], snap_tolerance)
                if match:
                    ref, pin_num, coords = match
                    logger.info(f"Snapped end point {points[-1]} -> {coords} (pin {ref}/{pin_num})")
                    snapped_info.append(
                        f"end snapped to {ref}/{pin_num} at [{coords[0]}, {coords[1]}]"
                    )
                    points[-1] = list(coords)

            # Extract wire properties
            stroke_width = properties.get("stroke_width", 0)
            stroke_type = properties.get("stroke_type", "default")

            # Use WireManager for S-expression manipulation
            if len(points) == 2:
                success = WireManager.add_wire(
                    Path(schematic_path),
                    points[0],
                    points[1],
                    stroke_width=stroke_width,
                    stroke_type=stroke_type,
                )
            else:
                success = WireManager.add_polyline_wire(
                    Path(schematic_path),
                    points,
                    stroke_width=stroke_width,
                    stroke_type=stroke_type,
                )

            if success:
                message = "Wire added successfully"
                if snapped_info:
                    message += "; " + "; ".join(snapped_info)
                return {"success": True, "message": message}
            else:
                return {"success": False, "message": "Failed to add wire"}
        except Exception as e:
            logger.error(f"Error adding wire to schematic: {str(e)}")
            import traceback

            logger.error(traceback.format_exc())
            return {
                "success": False,
                "message": str(e),
                "errorDetails": traceback.format_exc(),
            }

    def add_schematic_junction(self, params):
        """Add a junction (connection dot) to a schematic using WireManager"""
        logger.info("Adding junction to schematic")
        try:
            from pathlib import Path

            from commands.wire_manager import WireManager

            schematic_path = params.get("schematicPath")
            position = params.get("position")

            if not schematic_path:
                return {"success": False, "message": "Schematic path is required"}
            if not position:
                return {"success": False, "message": "Position is required"}

            success = WireManager.add_junction(Path(schematic_path), position)

            if success:
                return {"success": True, "message": "Junction added successfully"}
            else:
                return {"success": False, "message": "Failed to add junction"}
        except Exception as e:
            logger.error(f"Error adding junction to schematic: {str(e)}")
            import traceback

            logger.error(traceback.format_exc())
            return {
                "success": False,
                "message": str(e),
                "errorDetails": traceback.format_exc(),
            }

    def add_schematic_net_label(self, params):
        """Add a net label to schematic using WireManager"""
        logger.info("Adding net label to schematic")
        try:
            from pathlib import Path

            from commands.wire_manager import WireManager

            schematic_path = params.get("schematicPath")
            net_name = params.get("netName")
            position = params.get("position")
            label_type = params.get(
                "labelType", "label"
            )  # 'label', 'global_label', 'hierarchical_label'
            orientation = params.get("orientation", 0)  # 0, 90, 180, 270

            if not all([schematic_path, net_name, position]):
                return {"success": False, "message": "Missing required parameters"}

            # Use WireManager for S-expression manipulation
            success = WireManager.add_label(
                Path(schematic_path),
                net_name,
                position,
                label_type=label_type,
                orientation=orientation,
            )

            if success:
                return {
                    "success": True,
                    "message": f"Added net label '{net_name}' at {position}",
                }
            else:
                return {"success": False, "message": "Failed to add net label"}
        except Exception as e:
            logger.error(f"Error adding net label: {str(e)}")
            import traceback

            logger.error(traceback.format_exc())
            return {
                "success": False,
                "message": str(e),
                "errorDetails": traceback.format_exc(),
            }

    def delete_schematic_wire(self, params):
        """Delete a wire from the schematic matching start/end points"""
        logger.info("Deleting schematic wire")
        try:
            schematic_path = params.get("schematicPath")
            start = params.get("start", {})
            end = params.get("end", {})

            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}

            from pathlib import Path

            from commands.wire_manager import WireManager

            start_point = [start.get("x", 0), start.get("y", 0)]
            end_point = [end.get("x", 0), end.get("y", 0)]

            deleted = WireManager.delete_wire(Path(schematic_path), start_point, end_point)
            if deleted:
                return {"success": True}
            else:
                return {"success": False, "message": "No matching wire found"}

        except Exception as e:
            logger.error(f"Error deleting schematic wire: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def delete_schematic_net_label(self, params):
        """Delete a net label from the schematic"""
        logger.info("Deleting schematic net label")
        try:
            schematic_path = params.get("schematicPath")
            net_name = params.get("netName")
            position = params.get("position")

            if not schematic_path or not net_name:
                return {
                    "success": False,
                    "message": "schematicPath and netName are required",
                }

            from pathlib import Path

            from commands.wire_manager import WireManager

            pos_list = None
            if position:
                pos_list = [position.get("x", 0), position.get("y", 0)]

            deleted = WireManager.delete_label(Path(schematic_path), net_name, pos_list)
            if deleted:
                return {"success": True}
            else:
                return {"success": False, "message": f"Label '{net_name}' not found"}

        except Exception as e:
            logger.error(f"Error deleting schematic net label: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    # ------------------------------------------------------------------ #
    #  Connections                                                         #
    # ------------------------------------------------------------------ #

    def connect_to_net(self, params):
        """Connect a component pin to a named net using wire stub and label"""
        logger.info("Connecting component pin to net")
        try:
            from pathlib import Path

            schematic_path = params.get("schematicPath")
            component_ref = params.get("componentRef") or params.get("reference")
            pin_name = params.get("pinName") or params.get("pinNumber")
            net_name = params.get("netName")

            if not all([schematic_path, component_ref, pin_name, net_name]):
                return {"success": False, "message": "Missing required parameters"}

            # Use ConnectionManager with new WireManager integration
            success = ConnectionManager.connect_to_net(
                Path(schematic_path), component_ref, pin_name, net_name
            )

            if success:
                return {
                    "success": True,
                    "message": f"Connected {component_ref}/{pin_name} to net '{net_name}'",
                }
            else:
                return {"success": False, "message": "Failed to connect to net"}
        except Exception as e:
            logger.error(f"Error connecting to net: {str(e)}")
            import traceback

            logger.error(traceback.format_exc())
            return {
                "success": False,
                "message": str(e),
                "errorDetails": traceback.format_exc(),
            }

    def connect_passthrough(self, params):
        """Connect all pins of source connector to matching pins of target connector"""
        logger.info("Connecting passthrough between two connectors")
        try:
            from pathlib import Path

            schematic_path = params.get("schematicPath")
            source_ref = params.get("sourceRef")
            target_ref = params.get("targetRef")
            net_prefix = params.get("netPrefix", "PIN")
            pin_offset = int(params.get("pinOffset", 0))

            if not all([schematic_path, source_ref, target_ref]):
                return {
                    "success": False,
                    "message": "Missing required parameters: schematicPath, sourceRef, targetRef",
                }

            result = ConnectionManager.connect_passthrough(
                Path(schematic_path), source_ref, target_ref, net_prefix, pin_offset
            )

            n_ok = len(result["connected"])
            n_fail = len(result["failed"])
            return {
                "success": n_fail == 0,
                "message": f"Passthrough complete: {n_ok} connected, {n_fail} failed",
                "connected": result["connected"],
                "failed": result["failed"],
            }
        except Exception as e:
            logger.error(f"Error in connect_passthrough: {str(e)}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def get_schematic_pin_locations(self, params):
        """Return exact pin endpoint coordinates for a schematic component"""
        logger.info("Getting schematic pin locations")
        try:
            from pathlib import Path

            from commands.pin_locator import PinLocator

            schematic_path = params.get("schematicPath")
            reference = params.get("reference")

            if not all([schematic_path, reference]):
                return {
                    "success": False,
                    "message": "Missing required parameters: schematicPath, reference",
                }

            locator = PinLocator()
            all_pins = locator.get_all_symbol_pins(Path(schematic_path), reference)

            if not all_pins:
                return {
                    "success": False,
                    "message": f"No pins found for {reference} — check reference and schematic path",
                }

            # Enrich with pin names and angles from the symbol definition
            pins_def = (
                locator.get_symbol_pins(
                    Path(schematic_path),
                    locator._get_lib_id(Path(schematic_path), reference),
                )
                if hasattr(locator, "_get_lib_id")
                else {}
            )

            result = {}
            for pin_num, coords in all_pins.items():
                entry = {"x": coords[0], "y": coords[1]}
                if pin_num in pins_def:
                    entry["name"] = pins_def[pin_num].get("name", pin_num)
                    entry["angle"] = (
                        locator.get_pin_angle(Path(schematic_path), reference, pin_num) or 0
                    )
                result[pin_num] = entry

            return {"success": True, "reference": reference, "pins": result}

        except Exception as e:
            logger.error(f"Error getting pin locations: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def get_net_connections(self, params):
        """Get all connections for a named net"""
        logger.info("Getting net connections")
        try:
            schematic_path = params.get("schematicPath")
            net_name = params.get("netName")

            if not all([schematic_path, net_name]):
                return {"success": False, "message": "Missing required parameters"}

            schematic = SchematicManager.load_schematic(schematic_path)
            if not schematic:
                return {"success": False, "message": "Failed to load schematic"}

            connections = ConnectionManager.get_net_connections(schematic, net_name)
            return {"success": True, "connections": connections}
        except Exception as e:
            logger.error(f"Error getting net connections: {str(e)}")
            return {"success": False, "message": str(e)}

    def get_wire_connections(self, params):
        """Find all component pins reachable from a point via connected wires"""
        logger.info("Getting wire connections")
        try:
            from commands.wire_connectivity import get_wire_connections

            schematic_path = params.get("schematicPath")
            x = params.get("x")
            y = params.get("y")

            if not (schematic_path and x is not None and y is not None):
                return {
                    "success": False,
                    "message": "Missing required parameters: schematicPath, x, y",
                }

            try:
                x, y = float(x), float(y)
            except (TypeError, ValueError):
                return {
                    "success": False,
                    "message": "Parameters x and y must be numeric",
                }

            schematic = SchematicManager.load_schematic(schematic_path)
            if not schematic:
                return {"success": False, "message": "Failed to load schematic"}

            if not hasattr(schematic, "wire"):
                return {"success": False, "message": "Schematic has no wires"}

            result = get_wire_connections(schematic, schematic_path, x, y)
            if result is None:
                return {
                    "success": False,
                    "message": f"No wire found at ({x},{y}) within tolerance",
                }

            return {"success": True, **result}

        except Exception as e:
            logger.error(f"Error getting wire connections: {str(e)}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    # ------------------------------------------------------------------ #
    #  Query                                                               #
    # ------------------------------------------------------------------ #

    def get_schematic_view(self, params):
        """Get a rasterised image of the schematic (SVG export -> optional PNG conversion)"""
        logger.info("Getting schematic view")
        import base64
        import subprocess
        import tempfile

        try:
            schematic_path = params.get("schematicPath")
            if not schematic_path or not os.path.exists(schematic_path):
                return {
                    "success": False,
                    "message": f"Schematic not found: {schematic_path}",
                }

            fmt = params.get("format", "png")
            width = params.get("width", 1200)
            height = params.get("height", 900)

            # Step 1: Export schematic to SVG via kicad-cli
            with tempfile.TemporaryDirectory() as tmpdir:
                svg_path = os.path.join(tmpdir, "schematic.svg")
                cmd = [
                    "kicad-cli",
                    "sch",
                    "export",
                    "svg",
                    "--output",
                    tmpdir,
                    "--no-background-color",
                    schematic_path,
                ]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

                if result.returncode != 0:
                    return {
                        "success": False,
                        "message": f"kicad-cli SVG export failed: {result.stderr}",
                    }

                # kicad-cli may name the file after the schematic, find it
                import glob

                svg_files = glob.glob(os.path.join(tmpdir, "*.svg"))
                if not svg_files:
                    return {
                        "success": False,
                        "message": "No SVG file produced by kicad-cli",
                    }
                svg_path = svg_files[0]

                if fmt == "svg":
                    with open(svg_path, "r", encoding="utf-8") as f:
                        svg_data = f.read()
                    return {"success": True, "imageData": svg_data, "format": "svg"}

                # Step 2: Convert SVG to PNG using cairosvg
                try:
                    from cairosvg import svg2png
                except ImportError:
                    # Fallback: return SVG data with a note
                    with open(svg_path, "r", encoding="utf-8") as f:
                        svg_data = f.read()
                    return {
                        "success": True,
                        "imageData": svg_data,
                        "format": "svg",
                        "message": "cairosvg not installed — returning SVG instead of PNG. Install with: pip install cairosvg",
                    }

                png_data = svg2png(url=svg_path, output_width=width, output_height=height)

                return {
                    "success": True,
                    "imageData": base64.b64encode(png_data).decode("utf-8"),
                    "format": "png",
                    "width": width,
                    "height": height,
                }

        except FileNotFoundError:
            return {"success": False, "message": "kicad-cli not found in PATH"}
        except Exception as e:
            logger.error(f"Error getting schematic view: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def list_schematic_components(self, params):
        """List all components in a schematic"""
        logger.info("Listing schematic components")
        try:
            from pathlib import Path

            from commands.pin_locator import PinLocator

            schematic_path = params.get("schematicPath")
            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}

            sch_file = Path(schematic_path)
            if not sch_file.exists():
                return {
                    "success": False,
                    "message": f"Schematic not found: {schematic_path}",
                }

            schematic = SchematicManager.load_schematic(schematic_path)
            if not schematic:
                return {"success": False, "message": "Failed to load schematic"}

            # Optional filters
            filter_params = params.get("filter", {})
            lib_id_filter = filter_params.get("libId", "")
            ref_prefix_filter = filter_params.get("referencePrefix", "")

            locator = PinLocator()
            components = []

            for symbol in schematic.symbol:
                if not hasattr(symbol.property, "Reference"):
                    continue
                ref = symbol.property.Reference.value
                # Skip template symbols
                if ref.startswith("_TEMPLATE"):
                    continue

                lib_id = symbol.lib_id.value if hasattr(symbol, "lib_id") else ""

                # Apply filters
                if lib_id_filter and lib_id_filter not in lib_id:
                    continue
                if ref_prefix_filter and not ref.startswith(ref_prefix_filter):
                    continue

                value = symbol.property.Value.value if hasattr(symbol.property, "Value") else ""
                footprint = (
                    symbol.property.Footprint.value if hasattr(symbol.property, "Footprint") else ""
                )
                position = symbol.at.value if hasattr(symbol, "at") else [0, 0, 0]
                uuid_val = symbol.uuid.value if hasattr(symbol, "uuid") else ""

                comp = {
                    "reference": ref,
                    "libId": lib_id,
                    "value": value,
                    "footprint": footprint,
                    "position": {"x": float(position[0]), "y": float(position[1])},
                    "rotation": float(position[2]) if len(position) > 2 else 0,
                    "uuid": str(uuid_val),
                }

                # Get pins if available
                try:
                    all_pins = locator.get_all_symbol_pins(sch_file, ref)
                    if all_pins:
                        pins_def = locator.get_symbol_pins(sch_file, lib_id) or {}
                        pin_list = []
                        for pin_num, coords in all_pins.items():
                            pin_info = {
                                "number": pin_num,
                                "position": {"x": coords[0], "y": coords[1]},
                            }
                            if pin_num in pins_def:
                                pin_info["name"] = pins_def[pin_num].get("name", pin_num)
                            pin_list.append(pin_info)
                        comp["pins"] = pin_list
                except Exception:
                    pass  # Pin lookup is best-effort

                components.append(comp)

            return {"success": True, "components": components, "count": len(components)}

        except Exception as e:
            logger.error(f"Error listing schematic components: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def list_schematic_nets(self, params):
        """List all nets in a schematic with their connections"""
        logger.info("Listing schematic nets")
        try:
            from pathlib import Path

            schematic_path = params.get("schematicPath")
            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}

            schematic = SchematicManager.load_schematic(schematic_path)
            if not schematic:
                return {"success": False, "message": "Failed to load schematic"}

            # Get all net names from labels and global labels
            net_names = set()
            if hasattr(schematic, "label"):
                for label in schematic.label:
                    if hasattr(label, "value"):
                        net_names.add(label.value)
            if hasattr(schematic, "global_label"):
                for label in schematic.global_label:
                    if hasattr(label, "value"):
                        net_names.add(label.value)

            nets = []
            for net_name in sorted(net_names):
                connections = ConnectionManager.get_net_connections(
                    schematic, net_name, Path(schematic_path)
                )
                nets.append(
                    {
                        "name": net_name,
                        "connections": connections,
                    }
                )

            return {"success": True, "nets": nets, "count": len(nets)}

        except Exception as e:
            logger.error(f"Error listing schematic nets: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def list_schematic_wires(self, params):
        """List all wires in a schematic"""
        logger.info("Listing schematic wires")
        try:
            schematic_path = params.get("schematicPath")
            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}

            schematic = SchematicManager.load_schematic(schematic_path)
            if not schematic:
                return {"success": False, "message": "Failed to load schematic"}

            wires = []
            if hasattr(schematic, "wire"):
                for wire in schematic.wire:
                    if hasattr(wire, "pts") and hasattr(wire.pts, "xy"):
                        points = []
                        for point in wire.pts.xy:
                            if hasattr(point, "value"):
                                points.append(
                                    {
                                        "x": float(point.value[0]),
                                        "y": float(point.value[1]),
                                    }
                                )

                        if len(points) >= 2:
                            wires.append(
                                {
                                    "start": points[0],
                                    "end": points[-1],
                                }
                            )

            return {"success": True, "wires": wires, "count": len(wires)}

        except Exception as e:
            logger.error(f"Error listing schematic wires: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def list_schematic_labels(self, params):
        """List all net labels and power flags in a schematic"""
        logger.info("Listing schematic labels")
        try:
            schematic_path = params.get("schematicPath")
            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}

            schematic = SchematicManager.load_schematic(schematic_path)
            if not schematic:
                return {"success": False, "message": "Failed to load schematic"}

            labels = []

            # Regular labels
            if hasattr(schematic, "label"):
                for label in schematic.label:
                    if hasattr(label, "value"):
                        pos = (
                            label.at.value
                            if hasattr(label, "at") and hasattr(label.at, "value")
                            else [0, 0]
                        )
                        labels.append(
                            {
                                "name": label.value,
                                "type": "net",
                                "position": {"x": float(pos[0]), "y": float(pos[1])},
                            }
                        )

            # Global labels
            if hasattr(schematic, "global_label"):
                for label in schematic.global_label:
                    if hasattr(label, "value"):
                        pos = (
                            label.at.value
                            if hasattr(label, "at") and hasattr(label.at, "value")
                            else [0, 0]
                        )
                        labels.append(
                            {
                                "name": label.value,
                                "type": "global",
                                "position": {"x": float(pos[0]), "y": float(pos[1])},
                            }
                        )

            # Power symbols (components with power flag)
            if hasattr(schematic, "symbol"):
                for symbol in schematic.symbol:
                    if not hasattr(symbol.property, "Reference"):
                        continue
                    ref = symbol.property.Reference.value
                    if ref.startswith("_TEMPLATE"):
                        continue
                    if not ref.startswith("#PWR"):
                        continue
                    value = (
                        symbol.property.Value.value if hasattr(symbol.property, "Value") else ref
                    )
                    pos = symbol.at.value if hasattr(symbol, "at") else [0, 0, 0]
                    labels.append(
                        {
                            "name": value,
                            "type": "power",
                            "position": {"x": float(pos[0]), "y": float(pos[1])},
                        }
                    )

            return {"success": True, "labels": labels, "count": len(labels)}

        except Exception as e:
            logger.error(f"Error listing schematic labels: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def polish_schematic_readability(self, params):
        """Apply a non-electrical readability polish pass to a schematic."""
        logger.info("Polishing schematic readability")
        try:
            from commands.schematic_polish import polish_schematic_readability

            schematic_path = params.get("schematicPath") or params.get("schematic_path")
            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}

            return polish_schematic_readability(
                schematic_path,
                hide_internal_labels=params.get("hideInternalLabels", True),
                internal_label_names=params.get("internalLabelNames"),
                keep_label_names=params.get("keepLabelNames"),
                internal_label_font_size=params.get("internalLabelFontSize", 0.2),
                visible_label_font_size=params.get("visibleLabelFontSize"),
                junction_diameter=params.get("junctionDiameter", 1.27),
                block_frames=params.get("blockFrames"),
                create_backup=params.get("createBackup", False),
                backup_suffix=params.get("backupSuffix", ".bak_pre_polish"),
            )
        except Exception as e:
            logger.error(f"Error polishing schematic readability: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def list_schematic_libraries(self, params):
        """List available symbol libraries"""
        logger.info("Listing schematic libraries")
        try:
            from commands.library_schematic import LibraryManager

            search_paths = params.get("searchPaths")

            libraries = LibraryManager.list_available_libraries(search_paths)
            return {"success": True, "libraries": libraries}
        except Exception as e:
            logger.error(f"Error listing schematic libraries: {str(e)}")
            return {"success": False, "message": str(e)}

    # ------------------------------------------------------------------ #
    #  Movement / Annotation                                               #
    # ------------------------------------------------------------------ #

    def move_schematic_component(self, params):
        """Move a schematic component to a new position, dragging connected wires."""
        logger.info("Moving schematic component")
        try:
            import sexpdata as _sexpdata
            from commands.wire_dragger import WireDragger

            schematic_path = params.get("schematicPath")
            reference = params.get("reference")
            position = params.get("position", {})
            new_x = position.get("x")
            new_y = position.get("y")
            preserve_wires = params.get("preserveWires", True)

            if not schematic_path or not reference:
                return {
                    "success": False,
                    "message": "schematicPath and reference are required",
                }
            if new_x is None or new_y is None:
                return {
                    "success": False,
                    "message": "position with x and y is required",
                }

            with open(schematic_path, "r", encoding="utf-8") as f:
                sch_data = _sexpdata.loads(f.read())

            # Find symbol and record old position
            found = WireDragger.find_symbol(sch_data, reference)
            if found is None:
                return {"success": False, "message": f"Component {reference} not found"}
            _, old_x, old_y = found[0], found[1], found[2]
            old_position = {"x": old_x, "y": old_y}

            drag_summary = {}
            if preserve_wires:
                # Compute pin world positions before and after the move
                pin_positions = WireDragger.compute_pin_positions(
                    sch_data, reference, float(new_x), float(new_y)
                )
                # Build old->new coordinate map (deduplicate coincident pins)
                old_to_new = {}
                for _pin, (old_xy, new_xy) in pin_positions.items():
                    if old_xy in old_to_new:
                        logger.warning(
                            f"move_schematic_component: pin {_pin!r} of {reference!r} "
                            f"shares old position {old_xy} with another pin; "
                            f"keeping first entry, skipping duplicate"
                        )
                        continue
                    old_to_new[old_xy] = new_xy

                drag_summary = WireDragger.drag_wires(sch_data, old_to_new)

                # Synthesize wires for touching-pin connections after dragging,
                # so drag_wires doesn't accidentally move and collapse the new wire.
                wires_synthesized = WireDragger.synthesize_touching_pin_wires(
                    sch_data, reference, pin_positions
                )
                drag_summary["wires_synthesized"] = wires_synthesized

            # Update symbol position
            WireDragger.update_symbol_position(sch_data, reference, float(new_x), float(new_y))

            with open(schematic_path, "w", encoding="utf-8") as f:
                f.write(_sexpdata.dumps(sch_data))

            return {
                "success": True,
                "oldPosition": old_position,
                "newPosition": {"x": new_x, "y": new_y},
                "wiresMoved": drag_summary.get("endpoints_moved", 0),
                "wiresRemoved": drag_summary.get("wires_removed", 0),
                "wiresSynthesized": drag_summary.get("wires_synthesized", 0),
            }

        except Exception as e:
            logger.error(f"Error moving schematic component: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def rotate_schematic_component(self, params):
        """Rotate a schematic component"""
        logger.info("Rotating schematic component")
        try:
            schematic_path = params.get("schematicPath")
            reference = params.get("reference")
            angle = params.get("angle", 0)
            mirror = params.get("mirror")

            if not schematic_path or not reference:
                return {
                    "success": False,
                    "message": "schematicPath and reference are required",
                }

            schematic = SchematicManager.load_schematic(schematic_path)
            if not schematic:
                return {"success": False, "message": "Failed to load schematic"}

            for symbol in schematic.symbol:
                if not hasattr(symbol.property, "Reference"):
                    continue
                if symbol.property.Reference.value == reference:
                    pos = list(symbol.at.value)
                    while len(pos) < 3:
                        pos.append(0)
                    pos[2] = angle
                    symbol.at.value = pos

                    if mirror:
                        if hasattr(symbol, "mirror"):
                            symbol.mirror.value = mirror
                        else:
                            logger.warning(
                                f"Mirror '{mirror}' requested for {reference}, "
                                f"but symbol has no mirror attribute; skipped"
                            )

                    SchematicManager.save_schematic(schematic, schematic_path)
                    return {"success": True, "reference": reference, "angle": angle}

            return {"success": False, "message": f"Component {reference} not found"}

        except Exception as e:
            logger.error(f"Error rotating schematic component: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def annotate_schematic(self, params):
        """Annotate unannotated components in schematic (R? -> R1, R2, ...)"""
        logger.info("Annotating schematic")
        try:
            import re

            schematic_path = params.get("schematicPath")
            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}

            schematic = SchematicManager.load_schematic(schematic_path)
            if not schematic:
                return {"success": False, "message": "Failed to load schematic"}

            # Collect existing references by prefix
            existing_refs = {}  # prefix -> set of numbers
            unannotated = []  # (symbol, prefix)

            for symbol in schematic.symbol:
                if not hasattr(symbol.property, "Reference"):
                    continue
                ref = symbol.property.Reference.value
                if ref.startswith("_TEMPLATE"):
                    continue

                # Split reference into prefix and number
                match = re.match(r"^([A-Za-z_]+)(\d+)$", ref)
                if match:
                    prefix = match.group(1)
                    num = int(match.group(2))
                    if prefix not in existing_refs:
                        existing_refs[prefix] = set()
                    existing_refs[prefix].add(num)
                elif ref.endswith("?"):
                    prefix = ref[:-1]
                    unannotated.append((symbol, prefix))

            if not unannotated:
                return {
                    "success": True,
                    "annotated": [],
                    "message": "All components already annotated",
                }

            annotated = []
            for symbol, prefix in unannotated:
                if prefix not in existing_refs:
                    existing_refs[prefix] = set()

                # Find next available number
                next_num = 1
                while next_num in existing_refs[prefix]:
                    next_num += 1

                old_ref = symbol.property.Reference.value
                new_ref = f"{prefix}{next_num}"
                symbol.setAllReferences(new_ref)
                existing_refs[prefix].add(next_num)

                uuid_val = str(symbol.uuid.value) if hasattr(symbol, "uuid") else ""
                annotated.append(
                    {
                        "uuid": uuid_val,
                        "oldReference": old_ref,
                        "newReference": new_ref,
                    }
                )

            SchematicManager.save_schematic(schematic, schematic_path)
            return {"success": True, "annotated": annotated}

        except Exception as e:
            logger.error(f"Error annotating schematic: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    # ------------------------------------------------------------------ #
    #  Export                                                              #
    # ------------------------------------------------------------------ #

    def export_schematic_pdf(self, params):
        """Export schematic to PDF"""
        logger.info("Exporting schematic to PDF")
        try:
            schematic_path = params.get("schematicPath")
            output_path = params.get("outputPath")

            if not schematic_path:
                return {"success": False, "message": "Schematic path is required"}
            if not output_path:
                return {"success": False, "message": "Output path is required"}

            if not os.path.exists(schematic_path):
                return {
                    "success": False,
                    "message": f"Schematic not found: {schematic_path}",
                }

            import subprocess

            cmd = [
                "kicad-cli",
                "sch",
                "export",
                "pdf",
                "--output",
                output_path,
                schematic_path,
            ]

            if params.get("blackAndWhite"):
                cmd.insert(-1, "--black-and-white")

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

            if result.returncode == 0:
                return {"success": True, "file": {"path": output_path}}
            else:
                return {
                    "success": False,
                    "message": f"kicad-cli failed: {result.stderr}",
                }

        except FileNotFoundError:
            return {"success": False, "message": "kicad-cli not found in PATH"}
        except Exception as e:
            logger.error(f"Error exporting schematic to PDF: {str(e)}")
            return {"success": False, "message": str(e)}

    def export_schematic_svg(self, params):
        """Export schematic to SVG using kicad-cli"""
        logger.info("Exporting schematic SVG")
        import glob
        import shutil
        import subprocess

        try:
            schematic_path = params.get("schematicPath")
            output_path = params.get("outputPath")

            if not schematic_path or not output_path:
                return {
                    "success": False,
                    "message": "schematicPath and outputPath are required",
                }

            if not os.path.exists(schematic_path):
                return {
                    "success": False,
                    "message": f"Schematic not found: {schematic_path}",
                }

            # kicad-cli's --output flag for SVG export expects a directory, not a file path.
            # The output file is auto-named based on the schematic name.
            output_dir = os.path.dirname(output_path)
            if not output_dir:
                output_dir = "."

            os.makedirs(output_dir, exist_ok=True)

            cmd = [
                "kicad-cli",
                "sch",
                "export",
                "svg",
                schematic_path,
                "-o",
                output_dir,
            ]

            if params.get("blackAndWhite"):
                cmd.append("--black-and-white")

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

            if result.returncode != 0:
                return {
                    "success": False,
                    "message": f"kicad-cli failed: {result.stderr}",
                }

            # kicad-cli names the file after the schematic, so find the generated SVG
            svg_files = glob.glob(os.path.join(output_dir, "*.svg"))
            if not svg_files:
                return {
                    "success": False,
                    "message": "No SVG file produced by kicad-cli",
                }

            generated_svg = svg_files[0]

            # Move/rename to the user-specified output path if it differs
            if os.path.abspath(generated_svg) != os.path.abspath(output_path):
                shutil.move(generated_svg, output_path)

            return {"success": True, "file": {"path": output_path}}

        except FileNotFoundError:
            return {"success": False, "message": "kicad-cli not found in PATH"}
        except Exception as e:
            logger.error(f"Error exporting schematic SVG: {e}")
            return {"success": False, "message": str(e)}

    # ------------------------------------------------------------------ #
    #  ERC / Netlist                                                       #
    # ------------------------------------------------------------------ #

    def run_erc(self, params):
        """Run Electrical Rules Check on a schematic via kicad-cli"""
        logger.info("Running ERC on schematic")
        import os
        import subprocess
        import tempfile

        try:
            schematic_path = params.get("schematicPath")
            if not schematic_path or not os.path.exists(schematic_path):
                return {
                    "success": False,
                    "message": "Schematic file not found",
                    "errorDetails": f"Path does not exist: {schematic_path}",
                }

            kicad_cli = self.design_rule_commands._find_kicad_cli()
            if not kicad_cli:
                return {
                    "success": False,
                    "message": "kicad-cli not found",
                    "errorDetails": "Install KiCAD 8.0+ or add kicad-cli to PATH.",
                }

            cli_supports_erc = False
            if self.design_rule_commands is not None:
                cli_supports_erc = self.design_rule_commands._cli_supports_subcommand(
                    kicad_cli, "sch", "erc"
                )
            if not cli_supports_erc:
                logger.info(
                    "Installed kicad-cli does not expose 'sch erc'; falling back to schematic analysis"
                )
                from commands.schematic_analysis import check_wire_collisions, find_unconnected_pins

                unconnected = find_unconnected_pins(schematic_path)
                collisions = check_wire_collisions(schematic_path)
                violations = []
                severity_counts = {"error": 0, "warning": 0, "info": 0}

                for pin in unconnected.get("unconnectedPins", []):
                    violations.append(
                        {
                            "type": "unconnected_pin",
                            "severity": "error",
                            "message": (
                                f"Pin {pin['reference']}/{pin['pin']}"
                                + (f" ({pin['pinName']})" if pin.get("pinName") else "")
                                + " is not connected"
                            ),
                            "location": pin.get("position", {}),
                        }
                    )
                    severity_counts["error"] += 1

                for collision in collisions.get("collisions", []):
                    component = collision.get("component", {})
                    location = component.get("position", {})
                    violations.append(
                        {
                            "type": "wire_collision",
                            "severity": "error",
                            "message": (
                                f"Wire passes through component body {component.get('reference', '?')}"
                            ),
                            "location": location,
                        }
                    )
                    severity_counts["error"] += 1

                return {
                    "success": True,
                    "message": f"ERC fallback complete: {len(violations)} violation(s)",
                    "summary": {
                        "total": len(violations),
                        "by_severity": severity_counts,
                    },
                    "violations": violations,
                    "backend": "static_analysis",
                }

            with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tmp:
                json_output = tmp.name

            try:
                cmd = [
                    kicad_cli,
                    "sch",
                    "erc",
                    "--format",
                    "json",
                    "--output",
                    json_output,
                    schematic_path,
                ]
                logger.info(f"Running ERC command: {' '.join(cmd)}")

                result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

                if result.returncode != 0:
                    logger.error(f"ERC command failed: {result.stderr}")
                    return {
                        "success": False,
                        "message": "ERC command failed",
                        "errorDetails": result.stderr,
                    }

                with open(json_output, "r", encoding="utf-8") as f:
                    erc_data = json.load(f)

                violations = []
                severity_counts = {"error": 0, "warning": 0, "info": 0}

                for v in erc_data.get("violations", []):
                    vseverity = v.get("severity", "error")
                    items = v.get("items", [])
                    loc = {}
                    if items and "pos" in items[0]:
                        loc = {
                            "x": items[0]["pos"].get("x", 0),
                            "y": items[0]["pos"].get("y", 0),
                        }
                    violations.append(
                        {
                            "type": v.get("type", "unknown"),
                            "severity": vseverity,
                            "message": v.get("description", ""),
                            "location": loc,
                        }
                    )
                    if vseverity in severity_counts:
                        severity_counts[vseverity] += 1

                return {
                    "success": True,
                    "message": f"ERC complete: {len(violations)} violation(s)",
                    "summary": {
                        "total": len(violations),
                        "by_severity": severity_counts,
                    },
                    "violations": violations,
                }

            finally:
                if os.path.exists(json_output):
                    os.unlink(json_output)

        except subprocess.TimeoutExpired:
            return {"success": False, "message": "ERC timed out after 120 seconds"}
        except Exception as e:
            logger.error(f"Error running ERC: {str(e)}")
            return {"success": False, "message": str(e)}

    def generate_netlist(self, params):
        """Generate netlist from schematic"""
        logger.info("Generating netlist from schematic")
        try:
            schematic_path = params.get("schematicPath")

            if not schematic_path:
                return {"success": False, "message": "Schematic path is required"}

            schematic = SchematicManager.load_schematic(schematic_path)
            if not schematic:
                return {"success": False, "message": "Failed to load schematic"}

            netlist = ConnectionManager.generate_netlist(schematic, schematic_path=schematic_path)
            if not netlist.get("nets"):
                fallback = self.list_schematic_nets({"schematicPath": schematic_path})
                if fallback.get("success"):
                    netlist["nets"] = fallback.get("nets", [])
            return {"success": True, "netlist": netlist}
        except Exception as e:
            logger.error(f"Error generating netlist: {str(e)}")
            return {"success": False, "message": str(e)}

    # ------------------------------------------------------------------ #
    #  Analysis                                                            #
    # ------------------------------------------------------------------ #

    def get_schematic_view_region(self, params):
        """Export a cropped region of the schematic as an image"""
        logger.info("Exporting schematic view region")
        import base64
        import os
        import subprocess
        import tempfile

        try:
            schematic_path = params.get("schematicPath")
            if not schematic_path or not os.path.exists(schematic_path):
                return {"success": False, "message": "Schematic file not found"}

            x1 = float(params.get("x1", 0))
            y1 = float(params.get("y1", 0))
            x2 = float(params.get("x2", 297))
            y2 = float(params.get("y2", 210))
            x1, x2 = min(x1, x2), max(x1, x2)
            y1, y2 = min(y1, y2), max(y1, y2)
            out_format = params.get("format", "png")
            width = int(params.get("width", 800))
            height = int(params.get("height", 600))

            kicad_cli = self.design_rule_commands._find_kicad_cli()
            if not kicad_cli:
                return {"success": False, "message": "kicad-cli not found"}

            tmp_dir = tempfile.mkdtemp()
            svg_output = None

            try:
                cmd = [
                    kicad_cli,
                    "sch",
                    "export",
                    "svg",
                    "--output",
                    tmp_dir,
                    schematic_path,
                ]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

                if result.returncode != 0:
                    return {
                        "success": False,
                        "message": f"SVG export failed: {result.stderr}",
                    }

                # kicad-cli names the file after the schematic
                svg_files = [f for f in os.listdir(tmp_dir) if f.endswith(".svg")]
                if not svg_files:
                    return {
                        "success": False,
                        "message": "kicad-cli produced no SVG output",
                    }
                svg_output = os.path.join(tmp_dir, svg_files[0])

                import xml.etree.ElementTree as ET

                tree = ET.parse(svg_output)
                root = tree.getroot()

                # KiCad schematic SVGs use mm as viewBox units directly
                vb = root.get("viewBox", "")
                if vb:
                    parts = vb.split()
                    if len(parts) == 4:
                        orig_vb_x = float(parts[0])
                        orig_vb_y = float(parts[1])

                        new_x = orig_vb_x + x1
                        new_y = orig_vb_y + y1
                        new_w = x2 - x1
                        new_h = y2 - y1

                        root.set("viewBox", f"{new_x} {new_y} {new_w} {new_h}")
                        root.set("width", str(width))
                        root.set("height", str(height))

                # Write modified SVG
                cropped_svg_path = os.path.join(tmp_dir, "cropped.svg")
                tree.write(cropped_svg_path, xml_declaration=True, encoding="utf-8")

                if out_format == "svg":
                    with open(cropped_svg_path, "r", encoding="utf-8") as f:
                        svg_data = f.read()
                    return {"success": True, "imageData": svg_data, "format": "svg"}
                else:
                    try:
                        from cairosvg import svg2png
                    except ImportError:
                        return {
                            "success": False,
                            "message": "PNG export requires the 'cairosvg' package. Install it with: pip install cairosvg",
                        }
                    png_data = svg2png(
                        url=cropped_svg_path, output_width=width, output_height=height
                    )
                    return {
                        "success": True,
                        "imageData": base64.b64encode(png_data).decode("utf-8"),
                        "format": "png",
                    }
            finally:
                import shutil

                shutil.rmtree(tmp_dir, ignore_errors=True)

        except Exception as e:
            logger.error(f"Error in get_schematic_view_region: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def find_overlapping_elements(self, params):
        """Detect spatially overlapping symbols, wires, and labels"""
        logger.info("Finding overlapping elements in schematic")
        try:
            from pathlib import Path

            from commands.schematic_analysis import find_overlapping_elements

            schematic_path = params.get("schematicPath")
            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}

            tolerance = float(params.get("tolerance", 0.5))
            result = find_overlapping_elements(Path(schematic_path), tolerance)
            return {
                "success": True,
                **result,
                "message": f"Found {result['totalOverlaps']} overlap(s)",
            }
        except Exception as e:
            logger.error(f"Error finding overlapping elements: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def get_elements_in_region(self, params):
        """List all wires, labels, and symbols within a rectangular region"""
        logger.info("Getting elements in schematic region")
        try:
            from pathlib import Path

            from commands.schematic_analysis import get_elements_in_region

            schematic_path = params.get("schematicPath")
            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}

            x1 = float(params.get("x1", 0))
            y1 = float(params.get("y1", 0))
            x2 = float(params.get("x2", 0))
            y2 = float(params.get("y2", 0))

            result = get_elements_in_region(Path(schematic_path), x1, y1, x2, y2)
            return {
                "success": True,
                **result,
                "message": f"Found {result['counts']['symbols']} symbols, {result['counts']['wires']} wires, {result['counts']['labels']} labels in region",
            }
        except Exception as e:
            logger.error(f"Error getting elements in region: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def find_wires_crossing_symbols(self, params):
        """Find wires that cross over component symbol bodies"""
        logger.info("Finding wires crossing symbols in schematic")
        try:
            from pathlib import Path

            from commands.schematic_analysis import find_wires_crossing_symbols

            schematic_path = params.get("schematicPath")
            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}

            result = find_wires_crossing_symbols(Path(schematic_path))
            return {
                "success": True,
                "collisions": result,
                "count": len(result),
                "message": f"Found {len(result)} wire(s) crossing symbols",
            }
        except Exception as e:
            logger.error(f"Error checking wire collisions: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    # ------------------------------------------------------------------ #
    #  Helper analysis methods                                             #
    # ------------------------------------------------------------------ #

    def find_unconnected_pins(self, params):
        """List component pins with no wire/label/power symbol touching them"""
        logger.info("Finding unconnected pins")
        try:
            from commands.schematic_analysis import find_unconnected_pins

            schematic_path = params.get("schematicPath")
            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}
            result = find_unconnected_pins(schematic_path)
            return {"success": True, **result}
        except ImportError:
            return {
                "success": False,
                "message": "schematic_analysis module not available",
            }
        except Exception as e:
            logger.error(f"Error finding unconnected pins: {e}")
            return {"success": False, "message": str(e)}

    def check_wire_collisions(self, params):
        """Detect wires passing through component bodies without connecting to pins"""
        logger.info("Checking wire collisions")
        try:
            from commands.schematic_analysis import check_wire_collisions

            schematic_path = params.get("schematicPath")
            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}
            result = check_wire_collisions(schematic_path)
            return {"success": True, **result}
        except ImportError:
            return {
                "success": False,
                "message": "schematic_analysis module not available",
            }
        except Exception as e:
            logger.error(f"Error checking wire collisions: {e}")
            return {"success": False, "message": str(e)}
