import logging
import os
from pathlib import Path
from typing import List, Optional, Tuple

from skip import Schematic

logger = logging.getLogger(__name__)

# Import new wire and pin managers
try:
    from commands.pin_locator import PinLocator
    from commands.orthogonal_router import (
        compress_path,
        manhattan_path_length,
        plan_orthogonal_path,
        segment_direction,
        segment_intersects_rect,
        segments_conflict,
    )
    from commands.wire_manager import WireManager

    WIRE_MANAGER_AVAILABLE = True
except ImportError:
    logger.warning("WireManager/PinLocator not available")
    WIRE_MANAGER_AVAILABLE = False


class ConnectionManager:
    """Manage connections between components in schematics"""

    # Initialize pin locator (class variable, shared across instances)
    _pin_locator = None

    @classmethod
    def get_pin_locator(cls):
        """Get or create pin locator instance"""
        if cls._pin_locator is None and WIRE_MANAGER_AVAILABLE:
            cls._pin_locator = PinLocator()
        return cls._pin_locator

    @staticmethod
    def add_net_label(schematic: Schematic, net_name: str, position: list):
        """
        Add a net label to the schematic

        Args:
            schematic: Schematic object
            net_name: Name of the net (e.g., "VCC", "GND", "SIGNAL_1")
            position: [x, y] coordinates for the label

        Returns:
            Label object or None on error
        """
        try:
            if not hasattr(schematic, "label"):
                logger.error("Schematic does not have label collection")
                return None

            label = schematic.label.append(text=net_name, at={"x": position[0], "y": position[1]})
            logger.info(f"Added net label '{net_name}' at {position}")
            return label
        except Exception as e:
            logger.error(f"Error adding net label: {e}")
            return None

    @staticmethod
    def _direction_from_angle(angle_degrees: float) -> Tuple[int, int]:
        """Convert a schematic outward angle to a screen-axis unit vector."""
        angle = int(round(angle_degrees / 90.0)) % 4
        mapping = {
            0: (1, 0),
            1: (0, -1),
            2: (-1, 0),
            3: (0, 1),
        }
        return mapping[angle]

    @staticmethod
    def _perpendicular(direction: Tuple[int, int]) -> Tuple[int, int]:
        """Return a right-handed perpendicular for an axis-aligned direction."""
        dx, dy = direction
        return (-dy, dx)

    @staticmethod
    def _exit_point_from_bbox(
        pin_loc: List[float],
        direction: Tuple[int, int],
        bbox: Optional[Tuple[float, float, float, float]],
        margin: float,
    ) -> Tuple[float, float]:
        """Return a point just outside the symbol bbox in the pin's outward direction."""
        if not bbox:
            return (
                round(pin_loc[0] + direction[0] * margin, 4),
                round(pin_loc[1] + direction[1] * margin, 4),
            )

        min_x, min_y, max_x, max_y = bbox
        if direction == (1, 0):
            return (round(max_x + margin, 4), round(pin_loc[1], 4))
        if direction == (-1, 0):
            return (round(min_x - margin, 4), round(pin_loc[1], 4))
        if direction == (0, -1):
            return (round(pin_loc[0], 4), round(min_y - margin, 4))
        return (round(pin_loc[0], 4), round(max_y + margin, 4))

    @staticmethod
    def _point_near_labels(
        point: Tuple[float, float],
        labels: List[dict],
        minimum_spacing: float = 1.5,
    ) -> bool:
        """Return True if the candidate label point is too close to an existing label."""
        for label in labels:
            dx = point[0] - label["x"]
            dy = point[1] - label["y"]
            if (dx * dx + dy * dy) ** 0.5 < minimum_spacing:
                return True
        return False

    @staticmethod
    def _path_crosses_wires(path_points: List[Tuple[float, float]], wires: List[dict]) -> bool:
        """Reject paths that would create wire-wire crossings or overlaps."""
        for index in range(len(path_points) - 1):
            seg_start = path_points[index]
            seg_end = path_points[index + 1]
            for wire in wires:
                if segments_conflict(seg_start, seg_end, wire["start"], wire["end"]):
                    return True
        return False

    @staticmethod
    def _path_hits_symbol_bboxes(
        path_points: List[Tuple[float, float]],
        bboxes: List[Tuple[float, float, float, float]],
    ) -> bool:
        """Return True if any segment passes through another symbol body."""
        for index in range(len(path_points) - 1):
            seg_start = path_points[index]
            seg_end = path_points[index + 1]
            for bbox in bboxes:
                if segment_intersects_rect(seg_start, seg_end, bbox, strict=True):
                    return True
        return False

    @staticmethod
    def connect_to_net(schematic_path: Path, component_ref: str, pin_name: str, net_name: str):
        """
        Connect a component pin to a named net using a wire stub and label

        Args:
            schematic_path: Path to .kicad_sch file
            component_ref: Reference designator (e.g., "U1", "U1_")
            pin_name: Pin name/number
            net_name: Name of the net to connect to (e.g., "VCC", "GND", "SIGNAL_1")

        Returns:
            True if successful, False otherwise
        """
        try:
            if not WIRE_MANAGER_AVAILABLE:
                logger.error("WireManager/PinLocator not available")
                return False

            locator = ConnectionManager.get_pin_locator()
            if not locator:
                logger.error("Pin locator unavailable")
                return False

            # Get pin location using PinLocator
            pin_loc = locator.get_pin_location(schematic_path, component_ref, pin_name)
            if not pin_loc:
                logger.error(f"Could not locate pin {component_ref}/{pin_name}")
                return False

            pin_angle_deg = getattr(locator, "_last_pin_angle", 0)
            try:
                pin_angle_deg = locator.get_pin_angle(schematic_path, component_ref, pin_name) or 0
            except Exception:
                pin_angle_deg = 0

            from commands.schematic_analysis import (
                _compute_symbol_bbox_direct,
                _extract_lib_symbols,
                _load_sexp,
                _parse_labels,
                _parse_symbols,
                _parse_wires,
            )

            sexp_data = _load_sexp(schematic_path)
            labels = _parse_labels(sexp_data)
            wires = _parse_wires(sexp_data)
            symbols = _parse_symbols(sexp_data)
            lib_defs = _extract_lib_symbols(sexp_data)

            symbol_bboxes = {}
            for symbol in symbols:
                reference = symbol.get("reference", "")
                if not reference or reference.startswith("_TEMPLATE"):
                    continue
                lib_data = lib_defs.get(symbol.get("lib_id", ""), {})
                pin_defs = lib_data.get("pins", {})
                graphics_points = lib_data.get("graphics_points", [])
                if not pin_defs:
                    continue
                bbox = _compute_symbol_bbox_direct(
                    symbol,
                    pin_defs,
                    graphics_points=graphics_points,
                )
                if bbox is not None:
                    symbol_bboxes[reference] = bbox

            direction = ConnectionManager._direction_from_angle(pin_angle_deg)
            perpendicular = ConnectionManager._perpendicular(direction)
            other_bboxes = [
                bbox for reference, bbox in symbol_bboxes.items() if reference != component_ref
            ]
            grid = 2.54
            anchor_point = (
                round(pin_loc[0] + direction[0] * grid, 4),
                round(pin_loc[1] + direction[1] * grid, 4),
            )

            candidates = []
            for distance_steps in (0, 1, 2):
                forward_point = (
                    round(anchor_point[0] + direction[0] * grid * distance_steps, 4),
                    round(anchor_point[1] + direction[1] * grid * distance_steps, 4),
                )
                for offset_steps in (0, 1, -1, 2, -2):
                    label_point = (
                        round(forward_point[0] + perpendicular[0] * grid * offset_steps, 4),
                        round(forward_point[1] + perpendicular[1] * grid * offset_steps, 4),
                    )
                    if ConnectionManager._point_near_labels(label_point, labels):
                        continue

                    tail_path = plan_orthogonal_path(
                        anchor_point,
                        label_point,
                        other_bboxes,
                        bend_penalty=1.0,
                    )
                    if not tail_path:
                        continue

                    full_path = compress_path([tuple(pin_loc), anchor_point] + tail_path[1:])
                    if ConnectionManager._path_hits_symbol_bboxes(full_path, other_bboxes):
                        continue
                    if ConnectionManager._path_crosses_wires(full_path, wires):
                        continue

                    candidates.append(
                        (
                            manhattan_path_length(full_path)
                            + max(len(full_path) - 2, 0)
                            + abs(offset_steps) * 0.5,
                            full_path,
                            label_point,
                        )
                    )

            if candidates:
                _, chosen_path, label_point = min(candidates, key=lambda item: item[0])
            else:
                # Conservative fallback: preserve the old simple outward stub.
                label_point = anchor_point
                chosen_path = [tuple(pin_loc), anchor_point]

            wire_success = (
                WireManager.add_polyline_wire(schematic_path, [[p[0], p[1]] for p in chosen_path])
                if len(chosen_path) > 2
                else WireManager.add_wire(
                    schematic_path,
                    [chosen_path[0][0], chosen_path[0][1]],
                    [chosen_path[-1][0], chosen_path[-1][1]],
                )
            )
            if not wire_success:
                logger.error("Failed to create wire stub for net connection")
                return False

            last_direction = (
                segment_direction(chosen_path[-2], chosen_path[-1]) if len(chosen_path) >= 2 else "H"
            )
            label_orientation = 90 if last_direction == "V" else 0
            label_success = WireManager.add_label(
                schematic_path,
                net_name,
                [label_point[0], label_point[1]],
                label_type="label",
                orientation=label_orientation,
            )
            if not label_success:
                logger.error(f"Failed to add net label '{net_name}'")
                return False

            logger.info(f"Connected {component_ref}/{pin_name} to net '{net_name}'")
            return True

        except Exception as e:
            logger.error(f"Error connecting to net: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return False

    @staticmethod
    def connect_passthrough(
        schematic_path: Path,
        source_ref: str,
        target_ref: str,
        net_prefix: str = "PIN",
        pin_offset: int = 0,
    ):
        """
        Connect all pins of source_ref to matching pins of target_ref via shared net labels.
        Useful for passthrough adapters: J1 pin N <-> J2 pin N on net {net_prefix}_{N}.

        Args:
            schematic_path: Path to .kicad_sch file
            source_ref: Reference of the first connector (e.g., "J1")
            target_ref: Reference of the second connector (e.g., "J2")
            net_prefix: Prefix for generated net names (default: "PIN" -> PIN_1, PIN_2, ...)
            pin_offset: Add this value to the pin number when building the net name (default 0)

        Returns:
            dict with 'connected' list and 'failed' list
        """
        if not WIRE_MANAGER_AVAILABLE:
            logger.error("WireManager/PinLocator not available")
            return {"connected": [], "failed": ["WireManager unavailable"]}

        locator = ConnectionManager.get_pin_locator()
        if not locator:
            return {"connected": [], "failed": ["PinLocator unavailable"]}

        # Get all pins of source and target
        src_pins = locator.get_all_symbol_pins(schematic_path, source_ref) or {}
        tgt_pins = locator.get_all_symbol_pins(schematic_path, target_ref) or {}

        if not src_pins:
            return {"connected": [], "failed": [f"No pins found on {source_ref}"]}
        if not tgt_pins:
            return {"connected": [], "failed": [f"No pins found on {target_ref}"]}

        connected = []
        failed = []

        for pin_num in sorted(src_pins.keys(), key=lambda x: int(x) if x.isdigit() else 0):
            try:
                net_name = (
                    f"{net_prefix}_{int(pin_num) + pin_offset}"
                    if pin_num.isdigit()
                    else f"{net_prefix}_{pin_num}"
                )

                ok_src = ConnectionManager.connect_to_net(
                    schematic_path, source_ref, pin_num, net_name
                )
                if not ok_src:
                    failed.append(f"{source_ref}/{pin_num}")
                    continue

                if pin_num in tgt_pins:
                    ok_tgt = ConnectionManager.connect_to_net(
                        schematic_path, target_ref, pin_num, net_name
                    )
                    if not ok_tgt:
                        failed.append(f"{target_ref}/{pin_num}")
                        continue
                else:
                    failed.append(f"{target_ref}/{pin_num} (pin not found)")
                    continue

                connected.append(f"{source_ref}/{pin_num} <-> {target_ref}/{pin_num} [{net_name}]")
            except Exception as e:
                failed.append(f"{source_ref}/{pin_num}: {e}")

        logger.info(f"connect_passthrough: {len(connected)} connected, {len(failed)} failed")
        return {"connected": connected, "failed": failed}

    @staticmethod
    def get_net_connections(
        schematic: Schematic, net_name: str, schematic_path: Optional[Path] = None
    ):
        """
        Get all connections for a named net using wire graph analysis

        Args:
            schematic: Schematic object
            net_name: Name of the net to query
            schematic_path: Optional path to schematic file (enables accurate pin matching)

        Returns:
            List of connections: [{"component": ref, "pin": pin_name}, ...]
        """
        try:
            from commands.pin_locator import PinLocator

            connections = []
            tolerance = 0.5  # 0.5mm tolerance for point coincidence (grid spacing consideration)

            def points_coincide(p1, p2):
                """Check if two points are the same (within tolerance)"""
                if not p1 or not p2:
                    return False
                dx = abs(p1[0] - p2[0])
                dy = abs(p1[1] - p2[1])
                return dx < tolerance and dy < tolerance

            # 1. Find all labels with this net name
            if not hasattr(schematic, "label"):
                logger.warning("Schematic has no labels")
                return connections

            net_label_positions = []
            for label in schematic.label:
                if hasattr(label, "value") and label.value == net_name:
                    if hasattr(label, "at") and hasattr(label.at, "value"):
                        pos = label.at.value
                        net_label_positions.append([float(pos[0]), float(pos[1])])

            if not net_label_positions:
                logger.info(f"No labels found for net '{net_name}'")
                return connections

            logger.debug(f"Found {len(net_label_positions)} labels for net '{net_name}'")

            # 2. Find all wires connected to these label positions
            if not hasattr(schematic, "wire"):
                logger.warning("Schematic has no wires")
                return connections

            connected_wire_points = set()
            for wire in schematic.wire:
                if hasattr(wire, "pts") and hasattr(wire.pts, "xy"):
                    # Get all points in this wire (polyline)
                    wire_points = []
                    for point in wire.pts.xy:
                        if hasattr(point, "value"):
                            wire_points.append([float(point.value[0]), float(point.value[1])])

                    # Check if any wire point touches a label
                    wire_connected = False
                    for wire_pt in wire_points:
                        for label_pt in net_label_positions:
                            if points_coincide(wire_pt, label_pt):
                                wire_connected = True
                                break
                        if wire_connected:
                            break

                    # If this wire is connected to the net, add all its points
                    if wire_connected:
                        for pt in wire_points:
                            connected_wire_points.add((pt[0], pt[1]))

            if not connected_wire_points:
                logger.debug(f"No wires connected to net '{net_name}' labels")
                return connections

            logger.debug(
                f"Found {len(connected_wire_points)} wire connection points for net '{net_name}'"
            )

            # 3. Find component pins at wire endpoints
            if not hasattr(schematic, "symbol"):
                logger.warning("Schematic has no symbols")
                return connections

            # Create pin locator for accurate pin matching (if schematic_path available)
            locator = None
            if schematic_path and WIRE_MANAGER_AVAILABLE:
                locator = PinLocator()

            for symbol in schematic.symbol:
                # Skip template symbols
                if not hasattr(symbol.property, "Reference"):
                    continue

                ref = symbol.property.Reference.value
                if ref.startswith("_TEMPLATE"):
                    continue

                # Get lib_id for pin location lookup
                lib_id = symbol.lib_id.value if hasattr(symbol, "lib_id") else None
                if not lib_id:
                    continue

                # If we have PinLocator and schematic_path, do accurate pin matching
                if locator and schematic_path:
                    try:
                        # Get all pins for this symbol
                        pins = locator.get_symbol_pins(schematic_path, lib_id)
                        if not pins:
                            continue

                        # Check each pin
                        for pin_num, pin_data in pins.items():
                            # Get pin location
                            pin_loc = locator.get_pin_location(schematic_path, ref, pin_num)
                            if not pin_loc:
                                continue

                            # Check if pin coincides with any wire point
                            for wire_pt in connected_wire_points:
                                if points_coincide(pin_loc, list(wire_pt)):
                                    connections.append({"component": ref, "pin": pin_num})
                                    break  # Pin found, no need to check more wire points

                    except Exception as e:
                        logger.warning(f"Error matching pins for {ref}: {e}")
                        # Fall back to proximity matching
                        pass

                # Fallback: proximity-based matching if no PinLocator
                if not locator or not schematic_path:
                    symbol_pos = symbol.at.value if hasattr(symbol, "at") else None
                    if not symbol_pos:
                        continue

                    symbol_x = float(symbol_pos[0])
                    symbol_y = float(symbol_pos[1])

                    # Check if symbol is near any wire point (within 10mm)
                    for wire_pt in connected_wire_points:
                        dist = ((symbol_x - wire_pt[0]) ** 2 + (symbol_y - wire_pt[1]) ** 2) ** 0.5
                        if dist < 10.0:  # 10mm proximity threshold
                            connections.append({"component": ref, "pin": "unknown"})
                            break  # Only add once per component

            logger.info(f"Found {len(connections)} connections for net '{net_name}'")
            return connections

        except Exception as e:
            logger.error(f"Error getting net connections: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return []

    @staticmethod
    def generate_netlist(schematic: Schematic, schematic_path: Optional[Path] = None):
        """
        Generate a netlist from the schematic

        Args:
            schematic: Schematic object
            schematic_path: Optional path to schematic file (enables accurate pin matching
                via PinLocator; without it, only one connection per component is found)

        Returns:
            Dictionary with net information:
            {
                "nets": [
                    {
                        "name": "VCC",
                        "connections": [
                            {"component": "R1", "pin": "1"},
                            {"component": "C1", "pin": "1"}
                        ]
                    },
                    ...
                ],
                "components": [
                    {"reference": "R1", "value": "10k", "footprint": "..."},
                    ...
                ]
            }
        """
        try:
            netlist = {"nets": [], "components": []}

            # Gather all components
            if hasattr(schematic, "symbol"):
                for symbol in schematic.symbol:
                    component_info = {
                        "reference": symbol.property.Reference.value,
                        "value": (
                            symbol.property.Value.value if hasattr(symbol.property, "Value") else ""
                        ),
                        "footprint": (
                            symbol.property.Footprint.value
                            if hasattr(symbol.property, "Footprint")
                            else ""
                        ),
                    }
                    netlist["components"].append(component_info)

            # Gather all nets from labels
            if hasattr(schematic, "label"):
                net_names = set()
                for label in schematic.label:
                    if hasattr(label, "value"):
                        net_names.add(label.value)

                # For each net, get connections
                for net_name in net_names:
                    connections = ConnectionManager.get_net_connections(
                        schematic, net_name, schematic_path
                    )
                    if connections:
                        netlist["nets"].append({"name": net_name, "connections": connections})

            logger.info(
                f"Generated netlist with {len(netlist['nets'])} nets and {len(netlist['components'])} components"
            )
            return netlist

        except Exception as e:
            logger.error(f"Error generating netlist: {e}")
            return {"nets": [], "components": []}
