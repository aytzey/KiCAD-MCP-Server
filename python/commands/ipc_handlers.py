"""
IPC handler methods extracted from KiCAD interface.

These handlers wrap the kipy IPC board API, providing real-time UI sync
for board editing operations without needing a KiCAD reload.
"""

import logging

logger = logging.getLogger("kicad_interface")


class IPCHandlers:
    """Handles IPC-based board operations with real-time KiCAD UI updates."""

    def __init__(self, ipc_board_api=None, ipc_backend=None, use_ipc=False):
        self.ipc_board_api = ipc_board_api
        self.ipc_backend = ipc_backend
        self.use_ipc = use_ipc

    def set_ipc_board_api(self, ipc_board_api):
        self.ipc_board_api = ipc_board_api

    # =========================================================================
    # IPC operation handlers (_ipc_* methods, renamed without leading _)
    # =========================================================================

    def ipc_route_trace(self, params):
        """IPC handler for route_trace - adds track with real-time UI update"""
        try:
            # Extract parameters matching the existing route_trace interface
            start = params.get("start", {})
            end = params.get("end", {})
            layer = params.get("layer", "F.Cu")
            width = params.get("width", 0.25)
            net = params.get("net")

            # Handle both dict format and direct x/y
            start_x = start.get("x", 0) if isinstance(start, dict) else params.get("startX", 0)
            start_y = start.get("y", 0) if isinstance(start, dict) else params.get("startY", 0)
            end_x = end.get("x", 0) if isinstance(end, dict) else params.get("endX", 0)
            end_y = end.get("y", 0) if isinstance(end, dict) else params.get("endY", 0)

            success = self.ipc_board_api.add_track(
                start_x=start_x,
                start_y=start_y,
                end_x=end_x,
                end_y=end_y,
                width=width,
                layer=layer,
                net_name=net,
            )

            return {
                "success": success,
                "message": (
                    "Added trace (visible in KiCAD UI)" if success else "Failed to add trace"
                ),
                "trace": {
                    "start": {"x": start_x, "y": start_y, "unit": "mm"},
                    "end": {"x": end_x, "y": end_y, "unit": "mm"},
                    "layer": layer,
                    "width": width,
                    "net": net,
                },
            }
        except Exception as e:
            logger.error(f"IPC route_trace error: {e}")
            return {"success": False, "message": str(e)}

    def ipc_add_via(self, params):
        """IPC handler for add_via - adds via with real-time UI update"""
        try:
            position = params.get("position", {})
            x = position.get("x", 0) if isinstance(position, dict) else params.get("x", 0)
            y = position.get("y", 0) if isinstance(position, dict) else params.get("y", 0)

            size = params.get("size", 0.8)
            drill = params.get("drill", 0.4)
            net = params.get("net")
            from_layer = params.get("from_layer", "F.Cu")
            to_layer = params.get("to_layer", "B.Cu")

            success = self.ipc_board_api.add_via(
                x=x, y=y, diameter=size, drill=drill, net_name=net, via_type="through"
            )

            return {
                "success": success,
                "message": ("Added via (visible in KiCAD UI)" if success else "Failed to add via"),
                "via": {
                    "position": {"x": x, "y": y, "unit": "mm"},
                    "size": size,
                    "drill": drill,
                    "from_layer": from_layer,
                    "to_layer": to_layer,
                    "net": net,
                },
            }
        except Exception as e:
            logger.error(f"IPC add_via error: {e}")
            return {"success": False, "message": str(e)}

    def ipc_add_net(self, params):
        """IPC handler for add_net"""
        # Note: Net creation via IPC is limited - nets are typically created
        # when components are placed. Return success for compatibility.
        name = params.get("name")
        logger.info(f"IPC add_net: {name} (nets auto-created with components)")
        return {
            "success": True,
            "message": f"Net '{name}' will be created when components are connected",
            "net": {"name": name},
        }

    def ipc_add_copper_pour(self, params):
        """IPC handler for add_copper_pour - adds zone with real-time UI update"""
        try:
            layer = params.get("layer", "F.Cu")
            net = params.get("net")
            clearance = params.get("clearance", 0.5)
            min_width = params.get("minWidth", 0.25)
            points = params.get("points", [])
            priority = params.get("priority", 0)
            fill_type = params.get("fillType", "solid")
            name = params.get("name", "")

            if not points or len(points) < 3:
                return {
                    "success": False,
                    "message": "At least 3 points are required for copper pour outline",
                }

            # Convert points format if needed (handle both {x, y} and {x, y, unit})
            formatted_points = []
            for point in points:
                formatted_points.append({"x": point.get("x", 0), "y": point.get("y", 0)})

            success = self.ipc_board_api.add_zone(
                points=formatted_points,
                layer=layer,
                net_name=net,
                clearance=clearance,
                min_thickness=min_width,
                priority=priority,
                fill_mode=fill_type,
                name=name,
            )

            return {
                "success": success,
                "message": (
                    "Added copper pour (visible in KiCAD UI)"
                    if success
                    else "Failed to add copper pour"
                ),
                "pour": {
                    "layer": layer,
                    "net": net,
                    "clearance": clearance,
                    "minWidth": min_width,
                    "priority": priority,
                    "fillType": fill_type,
                    "pointCount": len(points),
                },
            }
        except Exception as e:
            logger.error(f"IPC add_copper_pour error: {e}")
            return {"success": False, "message": str(e)}

    def ipc_refill_zones(self, params):
        """IPC handler for refill_zones - refills all zones with real-time UI update"""
        try:
            success = self.ipc_board_api.refill_zones()

            return {
                "success": success,
                "message": (
                    "Zones refilled (visible in KiCAD UI)" if success else "Failed to refill zones"
                ),
            }
        except Exception as e:
            logger.error(f"IPC refill_zones error: {e}")
            return {"success": False, "message": str(e)}

    def ipc_add_text(self, params):
        """IPC handler for add_text/add_board_text - adds text with real-time UI update"""
        try:
            text = params.get("text", "")
            position = params.get("position", {})
            x = position.get("x", 0) if isinstance(position, dict) else params.get("x", 0)
            y = position.get("y", 0) if isinstance(position, dict) else params.get("y", 0)
            layer = params.get("layer", "F.SilkS")
            size = params.get("size", 1.0)
            rotation = params.get("rotation", 0)

            success = self.ipc_board_api.add_text(
                text=text, x=x, y=y, layer=layer, size=size, rotation=rotation
            )

            return {
                "success": success,
                "message": (
                    f"Added text '{text}' (visible in KiCAD UI)"
                    if success
                    else "Failed to add text"
                ),
            }
        except Exception as e:
            logger.error(f"IPC add_text error: {e}")
            return {"success": False, "message": str(e)}

    def ipc_set_board_size(self, params):
        """IPC handler for set_board_size"""
        try:
            width = params.get("width", 100)
            height = params.get("height", 100)
            unit = params.get("unit", "mm")

            success = self.ipc_board_api.set_size(width, height, unit)

            return {
                "success": success,
                "message": (
                    f"Board size set to {width}x{height} {unit} (visible in KiCAD UI)"
                    if success
                    else "Failed to set board size"
                ),
                "boardSize": {"width": width, "height": height, "unit": unit},
            }
        except Exception as e:
            logger.error(f"IPC set_board_size error: {e}")
            return {"success": False, "message": str(e)}

    def ipc_get_board_info(self, params):
        """IPC handler for get_board_info"""
        try:
            size = self.ipc_board_api.get_size()
            components = self.ipc_board_api.list_components()
            tracks = self.ipc_board_api.get_tracks()
            vias = self.ipc_board_api.get_vias()
            nets = self.ipc_board_api.get_nets()

            return {
                "success": True,
                "boardInfo": {
                    "size": size,
                    "componentCount": len(components),
                    "trackCount": len(tracks),
                    "viaCount": len(vias),
                    "netCount": len(nets),
                    "backend": "ipc",
                    "realtime": True,
                },
            }
        except Exception as e:
            logger.error(f"IPC get_board_info error: {e}")
            return {"success": False, "message": str(e)}

    def ipc_place_component(self, params):
        """IPC handler for place_component - places component with real-time UI update"""
        try:
            reference = params.get("reference", params.get("componentId", ""))
            footprint = params.get("footprint", "")
            position = params.get("position", {})
            x = position.get("x", 0) if isinstance(position, dict) else params.get("x", 0)
            y = position.get("y", 0) if isinstance(position, dict) else params.get("y", 0)
            rotation = params.get("rotation", 0)
            layer = params.get("layer", "F.Cu")
            value = params.get("value", "")

            success = self.ipc_board_api.place_component(
                reference=reference,
                footprint=footprint,
                x=x,
                y=y,
                rotation=rotation,
                layer=layer,
                value=value,
            )

            return {
                "success": success,
                "message": (
                    f"Placed component {reference} (visible in KiCAD UI)"
                    if success
                    else "Failed to place component"
                ),
                "component": {
                    "reference": reference,
                    "footprint": footprint,
                    "position": {"x": x, "y": y, "unit": "mm"},
                    "rotation": rotation,
                    "layer": layer,
                },
            }
        except Exception as e:
            logger.error(f"IPC place_component error: {e}")
            return {"success": False, "message": str(e)}

    def ipc_move_component(self, params):
        """IPC handler for move_component - moves component with real-time UI update"""
        try:
            reference = params.get("reference", params.get("componentId", ""))
            position = params.get("position", {})
            x = position.get("x", 0) if isinstance(position, dict) else params.get("x", 0)
            y = position.get("y", 0) if isinstance(position, dict) else params.get("y", 0)
            rotation = params.get("rotation")

            success = self.ipc_board_api.move_component(
                reference=reference, x=x, y=y, rotation=rotation
            )

            return {
                "success": success,
                "message": (
                    f"Moved component {reference} (visible in KiCAD UI)"
                    if success
                    else "Failed to move component"
                ),
            }
        except Exception as e:
            logger.error(f"IPC move_component error: {e}")
            return {"success": False, "message": str(e)}

    def ipc_delete_component(self, params):
        """IPC handler for delete_component - deletes component with real-time UI update"""
        try:
            reference = params.get("reference", params.get("componentId", ""))

            success = self.ipc_board_api.delete_component(reference=reference)

            return {
                "success": success,
                "message": (
                    f"Deleted component {reference} (visible in KiCAD UI)"
                    if success
                    else "Failed to delete component"
                ),
            }
        except Exception as e:
            logger.error(f"IPC delete_component error: {e}")
            return {"success": False, "message": str(e)}

    def ipc_get_component_list(self, params):
        """IPC handler for get_component_list"""
        try:
            components = self.ipc_board_api.list_components()

            return {"success": True, "components": components, "count": len(components)}
        except Exception as e:
            logger.error(f"IPC get_component_list error: {e}")
            return {"success": False, "message": str(e)}

    def ipc_save_project(self, params):
        """IPC handler for save_project"""
        try:
            success = self.ipc_board_api.save()

            return {
                "success": success,
                "message": "Project saved" if success else "Failed to save project",
            }
        except Exception as e:
            logger.error(f"IPC save_project error: {e}")
            return {"success": False, "message": str(e)}

    def ipc_delete_trace(self, params, routing_commands=None):
        """IPC handler for delete_trace - Note: IPC doesn't support direct trace deletion yet"""
        # IPC API doesn't have a direct delete track method
        # Fall back to SWIG for this operation
        logger.info("delete_trace: Falling back to SWIG (IPC doesn't support trace deletion)")
        return routing_commands.delete_trace(params)

    def ipc_get_nets_list(self, params):
        """IPC handler for get_nets_list - gets nets with real-time data"""
        try:
            nets = self.ipc_board_api.get_nets()

            return {"success": True, "nets": nets, "count": len(nets)}
        except Exception as e:
            logger.error(f"IPC get_nets_list error: {e}")
            return {"success": False, "message": str(e)}

    def ipc_add_board_outline(self, params, board_commands=None):
        """IPC handler for add_board_outline - adds board edge with real-time UI update.
        Rounded rectangles are delegated to the SWIG path because the IPC BoardSegment
        type cannot represent arcs; the SWIG path writes directly to the .kicad_pcb file
        and correctly generates PCB_SHAPE arcs for rounded corners.
        """
        shape = params.get("shape", "rectangle")
        if shape in ("rounded_rectangle", "rectangle"):
            # IPC path only supports straight segments from a points list,
            # but Claude sends rectangle/rounded_rectangle as shape+width+height.
            # Fall back to the SWIG path which correctly handles both shapes.
            logger.info(f"ipc_add_board_outline: delegating {shape} to SWIG path")
            return board_commands.add_board_outline(params)

        try:
            from kipy.board_types import BoardSegment
            from kipy.geometry import Vector2
            from kipy.proto.board.board_types_pb2 import BoardLayer
            from kipy.util.units import from_mm

            board = self.ipc_board_api._get_board()

            # Unwrap nested params (Claude sends {"shape":..., "params":{...}})
            inner = params.get("params", params)
            points = inner.get("points", params.get("points", []))
            width = inner.get("width", params.get("width", 0.1))

            if len(points) < 2:
                return {
                    "success": False,
                    "message": "At least 2 points required for board outline",
                }

            commit = board.begin_commit()
            lines_created = 0

            # Create line segments connecting the points
            for i in range(len(points)):
                start = points[i]
                end = points[(i + 1) % len(points)]  # Wrap around to close the outline

                segment = BoardSegment()
                segment.start = Vector2.from_xy(
                    from_mm(start.get("x", 0)), from_mm(start.get("y", 0))
                )
                segment.end = Vector2.from_xy(from_mm(end.get("x", 0)), from_mm(end.get("y", 0)))
                segment.layer = BoardLayer.BL_Edge_Cuts
                segment.attributes.stroke.width = from_mm(width)

                board.create_items(segment)
                lines_created += 1

            board.push_commit(commit, "Added board outline")

            return {
                "success": True,
                "message": f"Added board outline with {lines_created} segments (visible in KiCAD UI)",
                "segments": lines_created,
            }
        except Exception as e:
            logger.error(f"IPC add_board_outline error: {e}")
            return {"success": False, "message": str(e)}

    def ipc_add_mounting_hole(self, params):
        """IPC handler for add_mounting_hole - adds mounting hole with real-time UI update"""
        try:
            from kipy.board_types import BoardCircle
            from kipy.geometry import Vector2
            from kipy.proto.board.board_types_pb2 import BoardLayer
            from kipy.util.units import from_mm

            board = self.ipc_board_api._get_board()

            x = params.get("x", 0)
            y = params.get("y", 0)
            diameter = params.get("diameter", 3.2)  # M3 hole default

            commit = board.begin_commit()

            # Create circle on Edge.Cuts layer for the hole
            circle = BoardCircle()
            circle.center = Vector2.from_xy(from_mm(x), from_mm(y))
            circle.radius = from_mm(diameter / 2)
            circle.layer = BoardLayer.BL_Edge_Cuts
            circle.attributes.stroke.width = from_mm(0.1)

            board.create_items(circle)
            board.push_commit(commit, f"Added mounting hole at ({x}, {y})")

            return {
                "success": True,
                "message": f"Added mounting hole at ({x}, {y}) mm (visible in KiCAD UI)",
                "hole": {"position": {"x": x, "y": y}, "diameter": diameter},
            }
        except Exception as e:
            logger.error(f"IPC add_mounting_hole error: {e}")
            return {"success": False, "message": str(e)}

    def ipc_get_layer_list(self, params):
        """IPC handler for get_layer_list - gets enabled layers"""
        try:
            layers = self.ipc_board_api.get_enabled_layers()

            return {"success": True, "layers": layers, "count": len(layers)}
        except Exception as e:
            logger.error(f"IPC get_layer_list error: {e}")
            return {"success": False, "message": str(e)}

    def ipc_rotate_component(self, params):
        """IPC handler for rotate_component - rotates component with real-time UI update"""
        try:
            reference = params.get("reference", params.get("componentId", ""))
            angle = params.get("angle", params.get("rotation", 90))

            # Get current component to find its position
            components = self.ipc_board_api.list_components()
            target = None
            for comp in components:
                if comp.get("reference") == reference:
                    target = comp
                    break

            if not target:
                return {"success": False, "message": f"Component {reference} not found"}

            # Calculate new rotation
            current_rotation = target.get("rotation", 0)
            new_rotation = (current_rotation + angle) % 360

            # Use move_component with new rotation (position stays the same)
            success = self.ipc_board_api.move_component(
                reference=reference,
                x=target.get("position", {}).get("x", 0),
                y=target.get("position", {}).get("y", 0),
                rotation=new_rotation,
            )

            return {
                "success": success,
                "message": (
                    f"Rotated component {reference} by {angle}° (visible in KiCAD UI)"
                    if success
                    else "Failed to rotate component"
                ),
                "newRotation": new_rotation,
            }
        except Exception as e:
            logger.error(f"IPC rotate_component error: {e}")
            return {"success": False, "message": str(e)}

    def ipc_get_component_properties(self, params):
        """IPC handler for get_component_properties - gets detailed component info"""
        try:
            reference = params.get("reference", params.get("componentId", ""))

            components = self.ipc_board_api.list_components()
            target = None
            for comp in components:
                if comp.get("reference") == reference:
                    target = comp
                    break

            if not target:
                return {"success": False, "message": f"Component {reference} not found"}

            return {"success": True, "component": target}
        except Exception as e:
            logger.error(f"IPC get_component_properties error: {e}")
            return {"success": False, "message": str(e)}

    # =========================================================================
    # Legacy IPC command handlers (_handle_* methods, renamed without _handle_ prefix)
    # =========================================================================

    def get_backend_info(self, params):
        """Get information about the current backend"""
        return {
            "success": True,
            "backend": "ipc" if self.use_ipc else "swig",
            "realtime_sync": self.use_ipc,
            "ipc_connected": (self.ipc_backend.is_connected() if self.ipc_backend else False),
            "version": self.ipc_backend.get_version() if self.ipc_backend else "N/A",
            "message": (
                "Using IPC backend with real-time UI sync"
                if self.use_ipc
                else "Using SWIG backend (requires manual reload)"
            ),
        }

    def handle_ipc_add_track(self, params):
        """Add a track using IPC backend (real-time)"""
        if not self.use_ipc or not self.ipc_board_api:
            return {"success": False, "message": "IPC backend not available"}

        try:
            success = self.ipc_board_api.add_track(
                start_x=params.get("startX", 0),
                start_y=params.get("startY", 0),
                end_x=params.get("endX", 0),
                end_y=params.get("endY", 0),
                width=params.get("width", 0.25),
                layer=params.get("layer", "F.Cu"),
                net_name=params.get("net"),
            )
            return {
                "success": success,
                "message": (
                    "Track added (visible in KiCAD UI)" if success else "Failed to add track"
                ),
                "realtime": True,
            }
        except Exception as e:
            logger.error(f"Error adding track via IPC: {e}")
            return {"success": False, "message": str(e)}

    def handle_ipc_add_via(self, params):
        """Add a via using IPC backend (real-time)"""
        if not self.use_ipc or not self.ipc_board_api:
            return {"success": False, "message": "IPC backend not available"}

        try:
            success = self.ipc_board_api.add_via(
                x=params.get("x", 0),
                y=params.get("y", 0),
                diameter=params.get("diameter", 0.8),
                drill=params.get("drill", 0.4),
                net_name=params.get("net"),
                via_type=params.get("type", "through"),
            )
            return {
                "success": success,
                "message": ("Via added (visible in KiCAD UI)" if success else "Failed to add via"),
                "realtime": True,
            }
        except Exception as e:
            logger.error(f"Error adding via via IPC: {e}")
            return {"success": False, "message": str(e)}

    def handle_ipc_add_text(self, params):
        """Add text using IPC backend (real-time)"""
        if not self.use_ipc or not self.ipc_board_api:
            return {"success": False, "message": "IPC backend not available"}

        try:
            success = self.ipc_board_api.add_text(
                text=params.get("text", ""),
                x=params.get("x", 0),
                y=params.get("y", 0),
                layer=params.get("layer", "F.SilkS"),
                size=params.get("size", 1.0),
                rotation=params.get("rotation", 0),
            )
            return {
                "success": success,
                "message": (
                    "Text added (visible in KiCAD UI)" if success else "Failed to add text"
                ),
                "realtime": True,
            }
        except Exception as e:
            logger.error(f"Error adding text via IPC: {e}")
            return {"success": False, "message": str(e)}

    def handle_ipc_list_components(self, params):
        """List components using IPC backend"""
        if not self.use_ipc or not self.ipc_board_api:
            return {"success": False, "message": "IPC backend not available"}

        try:
            components = self.ipc_board_api.list_components()
            return {"success": True, "components": components, "count": len(components)}
        except Exception as e:
            logger.error(f"Error listing components via IPC: {e}")
            return {"success": False, "message": str(e)}

    def handle_ipc_get_tracks(self, params):
        """Get tracks using IPC backend"""
        if not self.use_ipc or not self.ipc_board_api:
            return {"success": False, "message": "IPC backend not available"}

        try:
            tracks = self.ipc_board_api.get_tracks()
            return {"success": True, "tracks": tracks, "count": len(tracks)}
        except Exception as e:
            logger.error(f"Error getting tracks via IPC: {e}")
            return {"success": False, "message": str(e)}

    def handle_ipc_get_vias(self, params):
        """Get vias using IPC backend"""
        if not self.use_ipc or not self.ipc_board_api:
            return {"success": False, "message": "IPC backend not available"}

        try:
            vias = self.ipc_board_api.get_vias()
            return {"success": True, "vias": vias, "count": len(vias)}
        except Exception as e:
            logger.error(f"Error getting vias via IPC: {e}")
            return {"success": False, "message": str(e)}

    def handle_ipc_save_board(self, params):
        """Save board using IPC backend"""
        if not self.use_ipc or not self.ipc_board_api:
            return {"success": False, "message": "IPC backend not available"}

        try:
            success = self.ipc_board_api.save()
            return {
                "success": success,
                "message": "Board saved" if success else "Failed to save board",
            }
        except Exception as e:
            logger.error(f"Error saving board via IPC: {e}")
            return {"success": False, "message": str(e)}
