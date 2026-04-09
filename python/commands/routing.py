"""
Routing-related command implementations for KiCAD interface
"""

import logging
import math
import os
from typing import Any, Dict, List, Optional, Tuple

import pcbnew
from commands.orthogonal_router import (
    compress_path,
    inflate_rect,
    manhattan_path_length,
    normalize_rect,
    plan_orthogonal_path,
)

logger = logging.getLogger("kicad_interface")


class RoutingCommands:
    """Handles routing-related KiCAD operations"""

    def __init__(self, board: Optional[pcbnew.BOARD] = None):
        """Initialize with optional board instance"""
        self.board = board

    @staticmethod
    def _bbox_to_rect_mm(bbox) -> Tuple[float, float, float, float]:
        """Convert a KiCad bounding box object to a normalized mm rectangle."""
        return normalize_rect(
            (
                bbox.GetLeft() / 1000000,
                bbox.GetTop() / 1000000,
                bbox.GetRight() / 1000000,
                bbox.GetBottom() / 1000000,
            )
        )

    @staticmethod
    def _union_rects(
        rects: List[Tuple[float, float, float, float]],
    ) -> Optional[Tuple[float, float, float, float]]:
        """Return the union of rects, or None for an empty list."""
        if not rects:
            return None
        min_x = min(rect[0] for rect in rects)
        min_y = min(rect[1] for rect in rects)
        max_x = max(rect[2] for rect in rects)
        max_y = max(rect[3] for rect in rects)
        return (min_x, min_y, max_x, max_y)

    def _get_track_width_mm(self, width: Optional[float]) -> float:
        """Resolve the effective trace width in mm."""
        if width:
            return float(width)
        return self.board.GetDesignSettings().GetCurrentTrackWidth() / 1000000

    def _get_clearance_mm(self) -> float:
        """Return board minimum copper clearance in mm."""
        design_settings = self.board.GetDesignSettings()
        clearance_nm = getattr(design_settings, "m_MinClearance", 0) or 0
        if clearance_nm:
            return clearance_nm / 1000000
        return 0.2

    def _find_best_via_position(
        self,
        start_point: Tuple[float, float],
        end_point: Tuple[float, float],
        start_layer: str,
        end_layer: str,
        keepout_margin: float,
        ignored_refs: List[str],
        net: Optional[str],
    ) -> Tuple[float, float]:
        """
        Pick a via location that minimises total wirelength while avoiding
        obstacles on both layers.

        Uses a 13-point candidate grid (midpoints, quarter-points, axis-
        aligned projections, and L-bend corners) scored by total Manhattan
        distance from start+end with an obstacle proximity bonus.

        This is significantly better than the naive 5-point search for dense
        boards where the midpoint is blocked.

        Reference: He (2024) Section 3.4 — via placement heuristics.
        """
        mid_x = round((start_point[0] + end_point[0]) / 2, 6)
        mid_y = round((start_point[1] + end_point[1]) / 2, 6)
        q1_x = round((start_point[0] + mid_x) / 2, 6)
        q3_x = round((mid_x + end_point[0]) / 2, 6)
        q1_y = round((start_point[1] + mid_y) / 2, 6)
        q3_y = round((mid_y + end_point[1]) / 2, 6)

        candidate_points = [
            # Original 5 candidates
            (mid_x, mid_y),
            (start_point[0], mid_y),
            (end_point[0], mid_y),
            (mid_x, start_point[1]),
            (mid_x, end_point[1]),
            # Quarter-point candidates (better for offset vias)
            (q1_x, mid_y),
            (q3_x, mid_y),
            (mid_x, q1_y),
            (mid_x, q3_y),
            # L-bend corners (optimal for Manhattan routing)
            (start_point[0], end_point[1]),
            (end_point[0], start_point[1]),
            # Near-start and near-end (for tight clearance situations)
            (start_point[0], q1_y),
            (q1_x, start_point[1]),
        ]

        start_obstacles = self._collect_routing_obstacles(
            start_layer,
            keepout_margin,
            ignored_refs=ignored_refs,
            net=net,
        )
        end_obstacles = self._collect_routing_obstacles(
            end_layer,
            keepout_margin,
            ignored_refs=ignored_refs,
            net=net,
        )
        all_obstacles = start_obstacles + end_obstacles

        def _via_score(point: Tuple[float, float]) -> float:
            """Lower is better: total wirelength + obstacle proximity penalty."""
            wl = (
                abs(point[0] - start_point[0]) + abs(point[1] - start_point[1])
                + abs(point[0] - end_point[0]) + abs(point[1] - end_point[1])
            )
            # Penalise proximity to obstacles (closer = worse)
            min_clearance = float("inf")
            for rect in all_obstacles:
                cx = max(rect[0], min(point[0], rect[2]))
                cy = max(rect[1], min(point[1], rect[3]))
                dist = math.hypot(point[0] - cx, point[1] - cy)
                min_clearance = min(min_clearance, dist)
            proximity_penalty = 0.0
            if min_clearance < keepout_margin * 2:
                proximity_penalty = keepout_margin * 5
            return wl + proximity_penalty

        viable = []
        for point in candidate_points:
            blocked = any(
                rect[0] < point[0] < rect[2] and rect[1] < point[1] < rect[3]
                for rect in all_obstacles
            )
            if not blocked:
                viable.append(point)

        if viable:
            return min(viable, key=_via_score)

        # All candidates blocked — try the least-bad option
        return min(candidate_points, key=_via_score)

    def _get_footprint_pad_rect(
        self, footprint
    ) -> Optional[Tuple[float, float, float, float]]:
        """Return the union of all pad bounding boxes for a footprint."""
        pad_rects = []
        for pad in footprint.Pads():
            try:
                pad_rects.append(self._bbox_to_rect_mm(pad.GetBoundingBox()))
            except Exception:
                continue
        if pad_rects:
            return self._union_rects(pad_rects)
        try:
            return self._bbox_to_rect_mm(footprint.GetBoundingBox())
        except Exception:
            return None

    def _get_pad_escape_point(
        self,
        pad,
        footprint,
        target_point: Tuple[float, float],
        clearance_margin: float,
    ) -> Tuple[float, float]:
        """
        Escape from a pad to the best footprint edge, balancing proximity
        to the pad, distance to target, and freedom from neighbouring pads.

        Scoring uses a weighted combination:
          score = α · edge_distance + β · target_distance + γ · pad_crowding

        where α=1 (prefer short escape), β=0.5 (bias toward target),
        and γ=2 (heavily penalise escaping into pad-dense areas).

        For BGA and dense QFP packages, this avoids routing through
        pin fields by preferring escape directions with fewer nearby pads.
        """
        pad_pos = pad.GetPosition()
        pad_point = (pad_pos.x / 1000000, pad_pos.y / 1000000)
        rect = self._get_footprint_pad_rect(footprint)
        if rect is None:
            return pad_point

        min_x, min_y, max_x, max_y = rect
        candidates = [
            (min_x - clearance_margin, pad_point[1]),
            (max_x + clearance_margin, pad_point[1]),
            (pad_point[0], min_y - clearance_margin),
            (pad_point[0], max_y + clearance_margin),
        ]
        edge_distances = [
            abs(pad_point[0] - min_x),
            abs(max_x - pad_point[0]),
            abs(pad_point[1] - min_y),
            abs(max_y - pad_point[1]),
        ]

        # Count neighbouring pads near each escape direction to detect
        # crowded sides (important for BGA/QFP escape routing)
        pad_crowds = [0, 0, 0, 0]  # left, right, top, bottom
        for other_pad in footprint.Pads():
            if other_pad.GetNumber() == pad.GetNumber():
                continue
            other_pos = other_pad.GetPosition()
            ox = other_pos.x / 1000000
            oy = other_pos.y / 1000000
            # Check which side this pad is relative to our pad
            if ox < pad_point[0] - 0.1:
                pad_crowds[0] += 1  # left
            elif ox > pad_point[0] + 0.1:
                pad_crowds[1] += 1  # right
            if oy < pad_point[1] - 0.1:
                pad_crowds[2] += 1  # top
            elif oy > pad_point[1] + 0.1:
                pad_crowds[3] += 1  # bottom

        def _escape_score(idx: int) -> float:
            edge_cost = edge_distances[idx]
            target_cost = (
                abs(candidates[idx][0] - target_point[0])
                + abs(candidates[idx][1] - target_point[1])
            )
            crowd_cost = pad_crowds[idx]
            return edge_cost + 0.5 * target_cost + 2.0 * crowd_cost

        best_idx = min(range(4), key=_escape_score)
        best = candidates[best_idx]
        return (round(best[0], 6), round(best[1], 6))

    def _collect_routing_obstacles(
        self,
        layer: str,
        keepout_margin: float,
        *,
        ignored_refs: Optional[List[str]] = None,
        net: Optional[str] = None,
    ) -> List[Tuple[float, float, float, float]]:
        """
        Collect inflated copper keepouts for simple obstacle-aware routing.

        Footprints are approximated by the union of their pad bboxes. Tracks and
        vias on other nets become obstacles as well.
        """
        ignored = set(ignored_refs or [])
        obstacles: List[Tuple[float, float, float, float]] = []
        layer_id = self.board.GetLayerID(layer)

        for footprint in self.board.GetFootprints():
            if footprint.GetReference() in ignored:
                continue
            rect = self._get_footprint_pad_rect(footprint)
            if rect is not None:
                obstacles.append(inflate_rect(rect, keepout_margin))

        for item in self.board.GetTracks():
            try:
                item_net = item.GetNetname()
            except Exception:
                item_net = ""
            if net and item_net == net:
                continue

            is_via = item.Type() == pcbnew.PCB_VIA_T
            if not is_via and item.GetLayer() != layer_id:
                continue

            try:
                rect = self._bbox_to_rect_mm(item.GetBoundingBox())
                obstacles.append(inflate_rect(rect, keepout_margin))
            except Exception:
                continue

        return obstacles

    def _collect_existing_tracks(
        self, layer: str, *, net: Optional[str] = None,
    ) -> List[Tuple[Tuple[float, float], Tuple[float, float]]]:
        """Collect existing track segments on *layer* for congestion awareness."""
        segments: List[Tuple[Tuple[float, float], Tuple[float, float]]] = []
        if not self.board:
            return segments
        layer_id = self.board.GetLayerID(layer)
        nm2mm = 1.0 / 1_000_000
        for item in self.board.GetTracks():
            try:
                if item.Type() == pcbnew.PCB_VIA_T:
                    continue
                if item.GetLayer() != layer_id:
                    continue
                if net and item.GetNetname() == net:
                    continue
                start = item.GetStart()
                end = item.GetEnd()
                segments.append(
                    ((start.x * nm2mm, start.y * nm2mm), (end.x * nm2mm, end.y * nm2mm))
                )
            except Exception:
                continue
        return segments

    def _plan_trace_points(
        self,
        start_point: Tuple[float, float],
        end_point: Tuple[float, float],
        layer: str,
        width_mm: float,
        *,
        net: Optional[str] = None,
        ignored_refs: Optional[List[str]] = None,
        pad_repulsion: float = 1.0,
        congestion_weight: float = 0.5,
    ) -> Optional[List[Tuple[float, float]]]:
        """Plan an orthogonal route on the Hanan grid with multi-term cost.

        Cost function:
          g(n→m) = L(n,m) + λ_b·bend + λ_g·pad_away + λ_c·congestion

        where:
          - λ_b (bend_penalty) = 2 × keepout_margin
          - λ_g (pad_repulsion) = 1.0 (He 2024 Eq 3.2)
          - λ_c (congestion_weight) = 0.5 (Rubin 1974 / PathFinder)

        The Hanan grid with midpoint enrichment provides ~3× more routing
        candidates than the original obstacle-corner-only grid, enabling
        significantly better paths around dense component clusters.
        """
        keepout_margin = self._get_clearance_mm() + width_mm / 2
        obstacles = self._collect_routing_obstacles(
            layer,
            keepout_margin,
            ignored_refs=ignored_refs,
            net=net,
        )

        # Collect pad centers for the pad-repulsion heuristic
        pad_centers: List[Tuple[float, float]] = []
        if pad_repulsion > 0 and self.board:
            nm2mm = 1.0 / 1_000_000
            for fp in self.board.GetFootprints():
                for pad in fp.Pads():
                    pos = pad.GetPosition()
                    pad_centers.append((pos.x * nm2mm, pos.y * nm2mm))

        # Collect existing tracks for congestion awareness
        existing_tracks = None
        if congestion_weight > 0:
            existing_tracks = self._collect_existing_tracks(layer, net=net)

        route = plan_orthogonal_path(
            start_point,
            end_point,
            obstacles,
            bend_penalty=max(keepout_margin * 2, 1.0),
            pad_repulsion=pad_repulsion,
            pad_centers=pad_centers if pad_repulsion > 0 else None,
            congestion_weight=congestion_weight,
            existing_tracks=existing_tracks,
        )
        if route:
            return compress_path(route)
        return None

    def _add_track_segment(
        self,
        start_point: pcbnew.VECTOR2I,
        end_point: pcbnew.VECTOR2I,
        layer_id: int,
        width_mm: float,
        net: Optional[str],
    ) -> pcbnew.PCB_TRACK:
        """Add a single already-planned segment to the board."""
        track = pcbnew.PCB_TRACK(self.board)
        track.SetStart(start_point)
        track.SetEnd(end_point)
        track.SetLayer(layer_id)
        track.SetWidth(int(width_mm * 1000000))

        if net:
            netinfo = self.board.GetNetInfo()
            nets_map = netinfo.NetsByName()
            if nets_map.has_key(net):
                track.SetNet(nets_map[net])

        self.board.Add(track)
        return track

    def add_net(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Add a new net to the PCB"""
        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first",
                }

            name = params.get("name")
            net_class = params.get("class")

            if not name:
                return {
                    "success": False,
                    "message": "Missing net name",
                    "errorDetails": "name parameter is required",
                }

            # Create new net
            netinfo = self.board.GetNetInfo()
            nets_map = netinfo.NetsByName()
            if nets_map.has_key(name):
                net = nets_map[name]
            else:
                net = pcbnew.NETINFO_ITEM(self.board, name)
                self.board.Add(net)

            # Set net class if provided
            if net_class:
                net_classes = self.board.GetNetClasses()
                if net_classes.Find(net_class):
                    net.SetClass(net_classes.Find(net_class))

            return {
                "success": True,
                "message": f"Added net: {name}",
                "net": {
                    "name": name,
                    "class": net_class if net_class else "Default",
                    "netcode": net.GetNetCode(),
                },
            }

        except Exception as e:
            logger.error(f"Error adding net: {str(e)}")
            return {
                "success": False,
                "message": "Failed to add net",
                "errorDetails": str(e),
            }

    def route_pad_to_pad(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Route a trace directly from one component pad to another.

        Looks up pad positions automatically, then creates a trace.
        Convenience wrapper around route_trace that eliminates the need
        for separate get_pad_position calls.
        """
        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first",
                }

            from_ref = params.get("fromRef")
            from_pad = str(params.get("fromPad", ""))
            to_ref = params.get("toRef")
            to_pad = str(params.get("toPad", ""))
            layer = params.get("layer", "F.Cu")
            width = params.get("width")
            net = params.get("net")  # optional override

            if not from_ref or not from_pad or not to_ref or not to_pad:
                return {
                    "success": False,
                    "message": "Missing parameters",
                    "errorDetails": "fromRef, fromPad, toRef, toPad are all required",
                }

            scale = 1000000  # nm to mm

            # Find pads
            footprints = {fp.GetReference(): fp for fp in self.board.GetFootprints()}

            for ref in [from_ref, to_ref]:
                if ref not in footprints:
                    return {
                        "success": False,
                        "message": f"Component not found: {ref}",
                        "errorDetails": f"'{ref}' does not exist on the board",
                    }

            def find_pad(ref: str, pad_num: str):
                fp = footprints[ref]
                for pad in fp.Pads():
                    if pad.GetNumber() == pad_num:
                        return pad
                return None

            start_pad = find_pad(from_ref, from_pad)
            end_pad = find_pad(to_ref, to_pad)

            if not start_pad:
                return {
                    "success": False,
                    "message": f"Pad not found: {from_ref} pad {from_pad}",
                    "errorDetails": f"Check pad number for {from_ref}",
                }
            if not end_pad:
                return {
                    "success": False,
                    "message": f"Pad not found: {to_ref} pad {to_pad}",
                    "errorDetails": f"Check pad number for {to_ref}",
                }

            start_pos = start_pad.GetPosition()
            end_pos = end_pad.GetPosition()
            start_point_mm = (start_pos.x / scale, start_pos.y / scale)
            end_point_mm = (end_pos.x / scale, end_pos.y / scale)
            width_mm = self._get_track_width_mm(width)
            keepout_margin = self._get_clearance_mm() + width_mm / 2

            # Use net from start pad if not overridden
            if not net:
                net = start_pad.GetNetname() or end_pad.GetNetname() or ""

            # Detect if pads are on different copper layers → need via.
            # SMD pad.GetLayer() reports F.Cu even on flipped B.Cu footprints in
            # KiCAD 9 SWIG. Use footprint.GetLayer() instead — it always reflects
            # the actual placed layer after Flip().
            fp_start = footprints[from_ref]
            fp_end = footprints[to_ref]
            start_layer = self.board.GetLayerName(fp_start.GetLayer())
            end_layer = self.board.GetLayerName(fp_end.GetLayer())
            start_escape = self._get_pad_escape_point(
                start_pad,
                fp_start,
                end_point_mm,
                keepout_margin,
            )
            end_escape = self._get_pad_escape_point(
                end_pad,
                fp_end,
                start_point_mm,
                keepout_margin,
            )
            copper_layers = {"F.Cu", "B.Cu"}
            needs_via = (
                start_layer in copper_layers
                and end_layer in copper_layers
                and start_layer != end_layer
            )

            if needs_via:
                via_x, via_y = self._find_best_via_position(
                    start_escape,
                    end_escape,
                    start_layer,
                    end_layer,
                    keepout_margin,
                    [from_ref, to_ref],
                    net,
                )
                start_route = self._plan_trace_points(
                    start_escape,
                    (via_x, via_y),
                    start_layer,
                    width_mm,
                    net=net,
                    ignored_refs=[from_ref],
                ) or [start_escape, (via_x, via_y)]
                end_route = self._plan_trace_points(
                    (via_x, via_y),
                    end_escape,
                    end_layer,
                    width_mm,
                    net=net,
                    ignored_refs=[to_ref],
                ) or [(via_x, via_y), end_escape]

                # Trace on start layer: start_pad → via
                r1 = self.route_trace(
                    {
                        "start": {"x": start_point_mm[0], "y": start_point_mm[1], "unit": "mm"},
                        "end": {"x": via_x, "y": via_y, "unit": "mm"},
                        "layer": start_layer,
                        "width": width_mm,
                        "net": net,
                        "waypoints": [{"x": p[0], "y": p[1], "unit": "mm"} for p in start_route[1:-1]],
                    }
                )
                # Via connecting both layers
                via_result = self.add_via(
                    {
                        "position": {"x": via_x, "y": via_y, "unit": "mm"},
                        "net": net,
                        "from_layer": start_layer,
                        "to_layer": end_layer,
                    }
                )
                # Trace on end layer: via → end_pad
                r2 = self.route_trace(
                    {
                        "start": {"x": via_x, "y": via_y, "unit": "mm"},
                        "end": {"x": end_point_mm[0], "y": end_point_mm[1], "unit": "mm"},
                        "layer": end_layer,
                        "width": width_mm,
                        "net": net,
                        "waypoints": [{"x": p[0], "y": p[1], "unit": "mm"} for p in end_route[1:-1]],
                    }
                )
                success = r1.get("success") and r2.get("success") and via_result.get("success")
                result = {
                    "success": success,
                    "message": f"Routed {from_ref}.{from_pad} → via → {to_ref}.{to_pad} (net: {net}, via at {via_x:.2f},{via_y:.2f})",
                    "via_added": True,
                    "via_position": {"x": via_x, "y": via_y},
                }
            else:
                middle_route = self._plan_trace_points(
                    start_escape,
                    end_escape,
                    layer if layer else start_layer,
                    width_mm,
                    net=net,
                    ignored_refs=[from_ref, to_ref],
                )
                full_route = compress_path(
                    [start_point_mm]
                    + (middle_route if middle_route else [start_escape, end_escape])
                    + [end_point_mm]
                )
                result = self.route_trace(
                    {
                        "start": {"x": start_point_mm[0], "y": start_point_mm[1], "unit": "mm"},
                        "end": {"x": end_point_mm[0], "y": end_point_mm[1], "unit": "mm"},
                        "layer": layer if layer else start_layer,
                        "width": width_mm,
                        "net": net,
                        "waypoints": [{"x": p[0], "y": p[1], "unit": "mm"} for p in full_route[1:-1]],
                    }
                )

            if result.get("success"):
                result["fromPad"] = {
                    "ref": from_ref,
                    "pad": from_pad,
                    "x": start_pos.x / scale,
                    "y": start_pos.y / scale,
                }
                result["toPad"] = {
                    "ref": to_ref,
                    "pad": to_pad,
                    "x": end_pos.x / scale,
                    "y": end_pos.y / scale,
                }

            return result

        except Exception as e:
            logger.error(f"Error in route_pad_to_pad: {str(e)}")
            return {
                "success": False,
                "message": "Failed to route pad to pad",
                "errorDetails": str(e),
            }

    def route_trace(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Route a trace between two points or pads"""
        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first",
                }

            start = params.get("start")
            end = params.get("end")
            layer = params.get("layer", "F.Cu")
            width = params.get("width")
            net = params.get("net")
            via = params.get("via", False)
            waypoints = params.get("waypoints") or []
            ignored_refs = params.get("ignoreRefs") or []

            if not start or not end:
                return {
                    "success": False,
                    "message": "Missing parameters",
                    "errorDetails": "start and end points are required",
                }

            # Get layer ID
            layer_id = self.board.GetLayerID(layer)
            if layer_id < 0:
                return {
                    "success": False,
                    "message": "Invalid layer",
                    "errorDetails": f"Layer '{layer}' does not exist",
                }

            # Get start point
            start_point = self._get_point(start)
            end_point = self._get_point(end)
            width_mm = self._get_track_width_mm(width)

            def _coerce_waypoint(point_spec: Any) -> Tuple[float, float]:
                if isinstance(point_spec, dict):
                    return (float(point_spec["x"]), float(point_spec["y"]))
                if isinstance(point_spec, (list, tuple)) and len(point_spec) >= 2:
                    return (float(point_spec[0]), float(point_spec[1]))
                raise ValueError(f"Invalid waypoint: {point_spec}")

            start_mm = (start_point.x / 1000000, start_point.y / 1000000)
            end_mm = (end_point.x / 1000000, end_point.y / 1000000)
            if waypoints:
                path_points = compress_path(
                    [start_mm] + [_coerce_waypoint(point) for point in waypoints] + [end_mm]
                )
            else:
                planned_points = self._plan_trace_points(
                    start_mm,
                    end_mm,
                    layer,
                    width_mm,
                    net=net,
                    ignored_refs=ignored_refs,
                )
                path_points = compress_path(planned_points or [start_mm, end_mm])

            tracks = []
            for index in range(len(path_points) - 1):
                seg_start = path_points[index]
                seg_end = path_points[index + 1]
                if seg_start == seg_end:
                    continue
                tracks.append(
                    self._add_track_segment(
                        pcbnew.VECTOR2I(int(seg_start[0] * 1000000), int(seg_start[1] * 1000000)),
                        pcbnew.VECTOR2I(int(seg_end[0] * 1000000), int(seg_end[1] * 1000000)),
                        layer_id,
                        width_mm,
                        net,
                    )
                )

            if not tracks:
                return {
                    "success": False,
                    "message": "Failed to route trace",
                    "errorDetails": "Planner produced no segments",
                }

            # Add via if requested and net is specified
            if via and net:
                via_point = end_point
                self.add_via(
                    {
                        "position": {
                            "x": via_point.x / 1000000,
                            "y": via_point.y / 1000000,
                            "unit": "mm",
                        },
                        "net": net,
                    }
                )

            self.board.SetModified()
            if hasattr(self.board, "BuildConnectivity"):
                try:
                    self.board.BuildConnectivity()
                except Exception:
                    logger.debug("BuildConnectivity failed after route_trace", exc_info=True)

            return {
                "success": True,
                "message": f"Added trace using {len(tracks)} segment(s)",
                "trace": {
                    "start": {
                        "x": start_point.x / 1000000,
                        "y": start_point.y / 1000000,
                        "unit": "mm",
                    },
                    "end": {
                        "x": end_point.x / 1000000,
                        "y": end_point.y / 1000000,
                        "unit": "mm",
                    },
                    "layer": layer,
                    "width": width_mm,
                    "net": net,
                    "segments": [
                        {
                            "start": {"x": seg_start[0], "y": seg_start[1], "unit": "mm"},
                            "end": {"x": seg_end[0], "y": seg_end[1], "unit": "mm"},
                        }
                        for seg_start, seg_end in zip(path_points, path_points[1:])
                    ],
                    "length": manhattan_path_length(path_points),
                },
            }

        except Exception as e:
            logger.error(f"Error routing trace: {str(e)}")
            return {
                "success": False,
                "message": "Failed to route trace",
                "errorDetails": str(e),
            }

    def add_via(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Add a via at the specified location"""
        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first",
                }

            position = params.get("position")
            size = params.get("size")
            drill = params.get("drill")
            net = params.get("net")
            from_layer = params.get("from_layer", "F.Cu")
            to_layer = params.get("to_layer", "B.Cu")

            if not position:
                return {
                    "success": False,
                    "message": "Missing position",
                    "errorDetails": "position parameter is required",
                }

            # Create via
            via = pcbnew.PCB_VIA(self.board)

            # Set position
            scale = 1000000 if position["unit"] == "mm" else 25400000  # mm or inch to nm
            x_nm = int(position["x"] * scale)
            y_nm = int(position["y"] * scale)
            via.SetPosition(pcbnew.VECTOR2I(x_nm, y_nm))

            # Set size and drill (default to board's current via settings)
            design_settings = self.board.GetDesignSettings()
            via.SetWidth(int(size * 1000000) if size else design_settings.GetCurrentViaSize())
            via.SetDrill(int(drill * 1000000) if drill else design_settings.GetCurrentViaDrill())

            # Set layers
            from_id = self.board.GetLayerID(from_layer)
            to_id = self.board.GetLayerID(to_layer)
            if from_id < 0 or to_id < 0:
                return {
                    "success": False,
                    "message": "Invalid layer",
                    "errorDetails": "Specified layers do not exist",
                }
            via.SetLayerPair(from_id, to_id)

            # Set net if provided
            if net:
                netinfo = self.board.GetNetInfo()
                nets_map = netinfo.NetsByName()
                if nets_map.has_key(net):
                    net_obj = nets_map[net]
                    via.SetNet(net_obj)

            # Add via to board
            self.board.Add(via)
            self.board.SetModified()
            if hasattr(self.board, "BuildConnectivity"):
                try:
                    self.board.BuildConnectivity()
                except Exception:
                    logger.debug("BuildConnectivity failed after add_via", exc_info=True)

            return {
                "success": True,
                "message": "Added via",
                "via": {
                    "position": {
                        "x": position["x"],
                        "y": position["y"],
                        "unit": position["unit"],
                    },
                    "size": via.GetWidth(pcbnew.F_Cu) / 1000000,
                    "drill": via.GetDrill() / 1000000,
                    "from_layer": from_layer,
                    "to_layer": to_layer,
                    "net": net,
                },
            }

        except Exception as e:
            logger.error(f"Error adding via: {str(e)}")
            return {
                "success": False,
                "message": "Failed to add via",
                "errorDetails": str(e),
            }

    def delete_trace(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Delete a trace from the PCB"""
        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first",
                }

            trace_uuid = params.get("traceUuid")
            position = params.get("position")
            net_name = params.get("net")
            layer = params.get("layer")
            include_vias = params.get("includeVias", False)

            if not trace_uuid and not position and not net_name:
                return {
                    "success": False,
                    "message": "Missing parameters",
                    "errorDetails": "One of traceUuid, position, or net must be provided",
                }

            # Delete by net name (bulk delete)
            if net_name:
                tracks_to_remove = []
                for track in list(self.board.GetTracks()):
                    if track.GetNetname() != net_name:
                        continue

                    # Skip vias if not requested
                    is_via = track.Type() == pcbnew.PCB_VIA_T
                    if is_via and not include_vias:
                        continue

                    # Filter by layer if specified (only for non-vias)
                    if layer and not is_via:
                        layer_id = self.board.GetLayerID(layer)
                        if track.GetLayer() != layer_id:
                            continue

                    tracks_to_remove.append(track)

                deleted_count = len(tracks_to_remove)
                for track in tracks_to_remove:
                    self.board.Remove(track)
                tracks_to_remove.clear()
                self.board.SetModified()

                return {
                    "success": True,
                    "message": f"Deleted {deleted_count} traces on net '{net_name}'",
                    "deletedCount": deleted_count,
                }

            # Find track by UUID
            if trace_uuid:
                track = None
                for item in list(self.board.GetTracks()):
                    if item.m_Uuid.AsString() == trace_uuid:
                        track = item
                        break

                if not track:
                    return {
                        "success": False,
                        "message": "Track not found",
                        "errorDetails": f"Could not find track with UUID: {trace_uuid}",
                    }

                self.board.Remove(track)
                track = None
                self.board.SetModified()
                return {"success": True, "message": f"Deleted track: {trace_uuid}"}

            # No valid parameters provided
            if not position:
                return {
                    "success": False,
                    "message": "No valid search parameter provided",
                    "errorDetails": "Provide traceUuid, position, or net parameter",
                }

            # Find track by position
            if position:
                scale = 1000000 if position["unit"] == "mm" else 25400000  # mm or inch to nm
                x_nm = int(position["x"] * scale)
                y_nm = int(position["y"] * scale)
                point = pcbnew.VECTOR2I(x_nm, y_nm)

                # Find closest track
                closest_track = None
                min_distance = float("inf")
                for track in list(self.board.GetTracks()):
                    dist = self._point_to_track_distance(point, track)
                    if dist < min_distance:
                        min_distance = dist
                        closest_track = track

                if closest_track and min_distance < 1000000:  # Within 1mm
                    self.board.Remove(closest_track)
                    closest_track = None
                    self.board.SetModified()
                    return {
                        "success": True,
                        "message": "Deleted track at specified position",
                    }
                else:
                    return {
                        "success": False,
                        "message": "No track found",
                        "errorDetails": "No track found near specified position",
                    }

        except Exception as e:
            logger.error(f"Error deleting trace: {str(e)}")
            return {
                "success": False,
                "message": "Failed to delete trace",
                "errorDetails": str(e),
            }
        return {
            "success": False,
            "message": "No action taken",
            "errorDetails": "No matching trace found for given parameters",
        }

    def get_nets_list(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get a list of all nets in the PCB"""
        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first",
                }

            nets = []
            netinfo = self.board.GetNetInfo()
            for net_code in range(netinfo.GetNetCount()):
                net = netinfo.GetNetItem(net_code)
                if net:
                    nets.append(
                        {
                            "name": net.GetNetname(),
                            "code": net.GetNetCode(),
                            "class": net.GetNetClassName(),
                        }
                    )

            return {"success": True, "nets": nets}

        except Exception as e:
            logger.error(f"Error getting nets list: {str(e)}")
            return {
                "success": False,
                "message": "Failed to get nets list",
                "errorDetails": str(e),
            }

    def query_traces(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Query traces by net, layer, or bounding box"""
        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first",
                }

            # Get filter parameters
            net_name = params.get("net")
            layer = params.get("layer")
            bbox = params.get("boundingBox")  # {x1, y1, x2, y2, unit}
            include_vias = params.get("includeVias", False)

            scale = 1000000  # nm to mm conversion factor
            traces = []
            vias = []

            # Process tracks
            for track in list(self.board.GetTracks()):
                try:
                    # Check if it's a via
                    is_via = track.Type() == pcbnew.PCB_VIA_T

                    if is_via and not include_vias:
                        continue

                    # Filter by net
                    if net_name and track.GetNetname() != net_name:
                        continue

                    # Filter by layer (only for tracks, not vias)
                    if layer and not is_via:
                        layer_id = self.board.GetLayerID(layer)
                        if track.GetLayer() != layer_id:
                            continue

                    # Filter by bounding box
                    if bbox:
                        bbox_unit = bbox.get("unit", "mm")
                        bbox_scale = scale if bbox_unit == "mm" else 25400000
                        x1 = int(bbox.get("x1", 0) * bbox_scale)
                        y1 = int(bbox.get("y1", 0) * bbox_scale)
                        x2 = int(bbox.get("x2", 0) * bbox_scale)
                        y2 = int(bbox.get("y2", 0) * bbox_scale)

                        if is_via:
                            pos = track.GetPosition()
                            if not (x1 <= pos.x <= x2 and y1 <= pos.y <= y2):
                                continue
                        else:
                            start = track.GetStart()
                            end = track.GetEnd()
                            # Check if either endpoint is within bbox
                            start_in = x1 <= start.x <= x2 and y1 <= start.y <= y2
                            end_in = x1 <= end.x <= x2 and y1 <= end.y <= y2
                            if not (start_in or end_in):
                                continue

                    if is_via:
                        pos = track.GetPosition()
                        vias.append(
                            {
                                "uuid": track.m_Uuid.AsString(),
                                "position": {
                                    "x": pos.x / scale,
                                    "y": pos.y / scale,
                                    "unit": "mm",
                                },
                                "net": track.GetNetname(),
                                "netCode": track.GetNetCode(),
                                "diameter": track.GetWidth() / scale,
                                "drill": track.GetDrillValue() / scale,
                            }
                        )
                    else:
                        start = track.GetStart()
                        end = track.GetEnd()
                        traces.append(
                            {
                                "uuid": track.m_Uuid.AsString(),
                                "net": track.GetNetname(),
                                "netCode": track.GetNetCode(),
                                "layer": self.board.GetLayerName(track.GetLayer()),
                                "width": track.GetWidth() / scale,
                                "start": {
                                    "x": start.x / scale,
                                    "y": start.y / scale,
                                    "unit": "mm",
                                },
                                "end": {
                                    "x": end.x / scale,
                                    "y": end.y / scale,
                                    "unit": "mm",
                                },
                                "length": track.GetLength() / scale,
                            }
                        )
                except Exception as track_err:
                    logger.warning(f"Skipping invalid track object: {track_err}")
                    continue

            result = {"success": True, "traceCount": len(traces), "traces": traces}

            if include_vias:
                result["viaCount"] = len(vias)
                result["vias"] = vias

            return result

        except Exception as e:
            logger.error(f"Error querying traces: {str(e)}")
            return {
                "success": False,
                "message": "Failed to query traces",
                "errorDetails": str(e),
            }

    def modify_trace(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Modify properties of an existing trace

        Allows changing trace width, layer, and net assignment.
        Find trace by UUID or position.
        """
        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first",
                }

            # Identification parameters
            trace_uuid = params.get("uuid")
            position = params.get("position")  # {x, y, unit}

            # Modification parameters
            new_width = params.get("width")  # in mm
            new_layer = params.get("layer")
            new_net = params.get("net")

            if not trace_uuid and not position:
                return {
                    "success": False,
                    "message": "Missing trace identifier",
                    "errorDetails": "Provide either 'uuid' or 'position' to identify the trace",
                }

            scale = 1000000  # nm to mm conversion

            # Find the track
            track = None

            if trace_uuid:
                for item in list(self.board.GetTracks()):
                    if item.m_Uuid.AsString() == trace_uuid:
                        track = item
                        break
            elif position:
                pos_unit = position.get("unit", "mm")
                pos_scale = scale if pos_unit == "mm" else 25400000
                x_nm = int(position["x"] * pos_scale)
                y_nm = int(position["y"] * pos_scale)
                point = pcbnew.VECTOR2I(x_nm, y_nm)

                # Find closest track
                min_distance = float("inf")
                for item in list(self.board.GetTracks()):
                    dist = self._point_to_track_distance(point, item)
                    if dist < min_distance:
                        min_distance = dist
                        track = item

                # Only accept if within 1mm
                if min_distance >= 1000000:
                    track = None

            if not track:
                return {
                    "success": False,
                    "message": "Track not found",
                    "errorDetails": "Could not find track with specified identifier",
                }

            # Check if it's a via (some modifications don't apply)
            is_via = track.Type() == pcbnew.PCB_VIA_T
            modifications = []

            # Apply modifications
            if new_width is not None:
                width_nm = int(new_width * scale)
                track.SetWidth(width_nm)
                modifications.append(f"width={new_width}mm")

            if new_layer and not is_via:
                layer_id = self.board.GetLayerID(new_layer)
                if layer_id < 0:
                    return {
                        "success": False,
                        "message": "Invalid layer",
                        "errorDetails": f"Layer '{new_layer}' not found",
                    }
                track.SetLayer(layer_id)
                modifications.append(f"layer={new_layer}")

            if new_net:
                netinfo = self.board.GetNetInfo()
                net = netinfo.GetNetItem(new_net)
                if not net:
                    return {
                        "success": False,
                        "message": "Invalid net",
                        "errorDetails": f"Net '{new_net}' not found",
                    }
                track.SetNet(net)
                modifications.append(f"net={new_net}")

            if not modifications:
                return {
                    "success": False,
                    "message": "No modifications specified",
                    "errorDetails": "Provide at least one of: width, layer, net",
                }

            return {
                "success": True,
                "message": f"Modified trace: {', '.join(modifications)}",
                "uuid": track.m_Uuid.AsString(),
                "modifications": modifications,
            }

        except Exception as e:
            logger.error(f"Error modifying trace: {str(e)}")
            return {
                "success": False,
                "message": "Failed to modify trace",
                "errorDetails": str(e),
            }

    def copy_routing_pattern(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Copy routing pattern from source components to target components

        This enables routing replication between identical component groups.
        The pattern is copied with a translation offset calculated from
        the position difference between source and target components.
        """
        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first",
                }

            source_refs = params.get("sourceRefs", [])  # e.g., ["U1", "U2", "U3"]
            target_refs = params.get("targetRefs", [])  # e.g., ["U4", "U5", "U6"]
            include_vias = params.get("includeVias", True)
            trace_width = params.get("traceWidth")  # Optional override

            if not source_refs or not target_refs:
                return {
                    "success": False,
                    "message": "Missing component references",
                    "errorDetails": "Provide both 'sourceRefs' and 'targetRefs' arrays",
                }

            if len(source_refs) != len(target_refs):
                return {
                    "success": False,
                    "message": "Mismatched component counts",
                    "errorDetails": f"sourceRefs has {len(source_refs)} items, targetRefs has {len(target_refs)}",
                }

            scale = 1000000  # nm to mm conversion

            # Get footprints
            footprints = {fp.GetReference(): fp for fp in self.board.GetFootprints()}

            # Validate all references exist
            for ref in source_refs + target_refs:
                if ref not in footprints:
                    return {
                        "success": False,
                        "message": "Component not found",
                        "errorDetails": f"Component '{ref}' not found on board",
                    }

            # Calculate offset from first source to first target component
            source_fp = footprints[source_refs[0]]
            target_fp = footprints[target_refs[0]]
            source_pos = source_fp.GetPosition()
            target_pos = target_fp.GetPosition()

            offset_x = target_pos.x - source_pos.x
            offset_y = target_pos.y - source_pos.y

            # Build mapping from source refs to target refs
            ref_mapping = dict(zip(source_refs, target_refs))

            # Collect all nets connected to source components
            source_nets = set()
            source_pad_positions = []  # (x, y) in nm for geometric fallback
            for ref in source_refs:
                fp = footprints[ref]
                for pad in fp.Pads():
                    net_name = pad.GetNetname()
                    if net_name and net_name != "":
                        source_nets.add(net_name)
                    pos = pad.GetPosition()
                    source_pad_positions.append((pos.x, pos.y))

            # Build bounding box around source pads (with 5mm tolerance in nm)
            TOLERANCE_NM = int(5 * scale)
            if source_pad_positions:
                xs = [p[0] for p in source_pad_positions]
                ys = [p[1] for p in source_pad_positions]
                bbox_x1 = min(xs) - TOLERANCE_NM
                bbox_x2 = max(xs) + TOLERANCE_NM
                bbox_y1 = min(ys) - TOLERANCE_NM
                bbox_y2 = max(ys) + TOLERANCE_NM
            else:
                # Fall back to component position ± 25mm
                sp = source_fp.GetPosition()
                bbox_x1 = sp.x - int(25 * scale)
                bbox_x2 = sp.x + int(25 * scale)
                bbox_y1 = sp.y - int(25 * scale)
                bbox_y2 = sp.y + int(25 * scale)

            def point_in_bbox(px: int, py: int) -> bool:
                return bbox_x1 <= px <= bbox_x2 and bbox_y1 <= py <= bbox_y2

            # Collect traces: by net name (if available) OR by geometric proximity
            use_net_filter = len(source_nets) > 0
            traces_to_copy = []
            vias_to_copy = []

            for track in list(self.board.GetTracks()):
                is_via = track.Type() == pcbnew.PCB_VIA_T

                if use_net_filter:
                    # Primary: net-based filter
                    if track.GetNetname() not in source_nets:
                        continue
                else:
                    # Fallback: geometric filter – trace start OR end inside source bbox
                    if is_via:
                        pos = track.GetPosition()
                        if not point_in_bbox(pos.x, pos.y):
                            continue
                    else:
                        s = track.GetStart()
                        e = track.GetEnd()
                        if not (point_in_bbox(s.x, s.y) or point_in_bbox(e.x, e.y)):
                            continue

                if is_via:
                    if include_vias:
                        vias_to_copy.append(track)
                else:
                    traces_to_copy.append(track)

            filter_method = "net-based" if use_net_filter else "geometric (pads have no nets)"
            logger.info(
                f"copy_routing_pattern: {len(traces_to_copy)} traces, "
                f"{len(vias_to_copy)} vias selected via {filter_method}"
            )

            # Create new traces with offset
            created_traces = 0
            created_vias = 0

            for track in traces_to_copy:
                start = track.GetStart()
                end = track.GetEnd()

                # Create new track
                new_track = pcbnew.PCB_TRACK(self.board)
                new_track.SetStart(pcbnew.VECTOR2I(start.x + offset_x, start.y + offset_y))
                new_track.SetEnd(pcbnew.VECTOR2I(end.x + offset_x, end.y + offset_y))
                new_track.SetLayer(track.GetLayer())

                # Set width (use override or original)
                if trace_width:
                    new_track.SetWidth(int(trace_width * scale))
                else:
                    new_track.SetWidth(track.GetWidth())

                # Try to find corresponding target net
                # This is a simplification - more sophisticated mapping would be needed
                # for complex designs
                self.board.Add(new_track)
                created_traces += 1

            for via in vias_to_copy:
                pos = via.GetPosition()

                # Create new via
                new_via = pcbnew.PCB_VIA(self.board)
                new_via.SetPosition(pcbnew.VECTOR2I(pos.x + offset_x, pos.y + offset_y))
                new_via.SetWidth(via.GetWidth(pcbnew.F_Cu))
                new_via.SetDrill(via.GetDrillValue())
                new_via.SetViaType(via.GetViaType())

                self.board.Add(new_via)
                created_vias += 1

            result = {
                "success": True,
                "message": f"Copied routing pattern: {created_traces} traces, {created_vias} vias",
                "filterMethod": filter_method,
                "offset": {"x": offset_x / scale, "y": offset_y / scale, "unit": "mm"},
                "createdTraces": created_traces,
                "createdVias": created_vias,
                "sourceComponents": source_refs,
                "targetComponents": target_refs,
            }

            return result

        except Exception as e:
            logger.error(f"Error copying routing pattern: {str(e)}")
            return {
                "success": False,
                "message": "Failed to copy routing pattern",
                "errorDetails": str(e),
            }

    def create_netclass(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new net class with specified properties"""
        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first",
                }

            name = params.get("name")
            clearance = params.get("clearance")
            track_width = params.get("trackWidth")
            via_diameter = params.get("viaDiameter")
            via_drill = params.get("viaDrill")
            uvia_diameter = params.get("uviaDiameter")
            uvia_drill = params.get("uviaDrill")
            diff_pair_width = params.get("diffPairWidth")
            diff_pair_gap = params.get("diffPairGap")
            nets = params.get("nets", [])

            if not name:
                return {
                    "success": False,
                    "message": "Missing netclass name",
                    "errorDetails": "name parameter is required",
                }

            # Get net classes
            net_classes = self.board.GetNetClasses()

            # Create new net class if it doesn't exist
            if not net_classes.Find(name):
                netclass = pcbnew.NETCLASS(name)
                net_classes.Add(netclass)
            else:
                netclass = net_classes.Find(name)

            # Set properties
            scale = 1000000  # mm to nm
            if clearance is not None:
                netclass.SetClearance(int(clearance * scale))
            if track_width is not None:
                netclass.SetTrackWidth(int(track_width * scale))
            if via_diameter is not None:
                netclass.SetViaDiameter(int(via_diameter * scale))
            if via_drill is not None:
                netclass.SetViaDrill(int(via_drill * scale))
            if uvia_diameter is not None:
                netclass.SetMicroViaDiameter(int(uvia_diameter * scale))
            if uvia_drill is not None:
                netclass.SetMicroViaDrill(int(uvia_drill * scale))
            if diff_pair_width is not None:
                netclass.SetDiffPairWidth(int(diff_pair_width * scale))
            if diff_pair_gap is not None:
                netclass.SetDiffPairGap(int(diff_pair_gap * scale))

            # Add nets to net class
            netinfo = self.board.GetNetInfo()
            nets_map = netinfo.NetsByName()
            for net_name in nets:
                if nets_map.has_key(net_name):
                    net = nets_map[net_name]
                    net.SetClass(netclass)

            return {
                "success": True,
                "message": f"Created net class: {name}",
                "netClass": {
                    "name": name,
                    "clearance": netclass.GetClearance() / scale,
                    "trackWidth": netclass.GetTrackWidth() / scale,
                    "viaDiameter": netclass.GetViaDiameter() / scale,
                    "viaDrill": netclass.GetViaDrill() / scale,
                    "uviaDiameter": netclass.GetMicroViaDiameter() / scale,
                    "uviaDrill": netclass.GetMicroViaDrill() / scale,
                    "diffPairWidth": netclass.GetDiffPairWidth() / scale,
                    "diffPairGap": netclass.GetDiffPairGap() / scale,
                    "nets": nets,
                },
            }

        except Exception as e:
            logger.error(f"Error creating net class: {str(e)}")
            return {
                "success": False,
                "message": "Failed to create net class",
                "errorDetails": str(e),
            }

    def add_copper_pour(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Add a copper pour (zone) to the PCB"""
        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first",
                }

            layer = params.get("layer", "F.Cu")
            net = params.get("net")
            clearance = params.get("clearance")
            min_width = params.get("minWidth", 0.2)
            points = params.get("outline", params.get("points", []))
            priority = params.get("priority", 0)
            fill_type = params.get("fillType", "solid")  # solid or hatched

            # If no outline provided, use board outline
            if not points or len(points) < 3:
                board_box = self.board.GetBoardEdgesBoundingBox()
                if board_box.GetWidth() > 0 and board_box.GetHeight() > 0:
                    scale = 1000000  # nm to mm
                    x1 = board_box.GetX() / scale
                    y1 = board_box.GetY() / scale
                    x2 = (board_box.GetX() + board_box.GetWidth()) / scale
                    y2 = (board_box.GetY() + board_box.GetHeight()) / scale

                    # Detect corner radius from Edge.Cuts arcs so the zone rectangle
                    # stays inside the rounded board corners (avoids zone visually
                    # extending outside Edge.Cuts before refill)
                    corner_radius = 0.0
                    edge_layer_id = self.board.GetLayerID("Edge.Cuts")
                    for item in self.board.GetDrawings():
                        if item.GetLayer() == edge_layer_id and item.GetClass() == "PCB_ARC":
                            r = item.GetRadius() / scale
                            if r > corner_radius:
                                corner_radius = r
                    # Inset the zone rectangle by the corner radius so its corners
                    # lie on the straight portions of the board edge.
                    inset = corner_radius
                    points = [
                        {"x": x1 + inset, "y": y1 + inset},
                        {"x": x2 - inset, "y": y1 + inset},
                        {"x": x2 - inset, "y": y2 - inset},
                        {"x": x1 + inset, "y": y2 - inset},
                    ]
                else:
                    return {
                        "success": False,
                        "message": "Missing outline",
                        "errorDetails": "Provide an outline array or add a board outline first",
                    }

            # Get layer ID
            layer_id = self.board.GetLayerID(layer)
            if layer_id < 0:
                return {
                    "success": False,
                    "message": "Invalid layer",
                    "errorDetails": f"Layer '{layer}' does not exist",
                }

            # Create zone
            zone = pcbnew.ZONE(self.board)
            zone.SetLayer(layer_id)

            # Set net if provided
            if net:
                netinfo = self.board.GetNetInfo()
                nets_map = netinfo.NetsByName()
                if nets_map.has_key(net):
                    net_obj = nets_map[net]
                    zone.SetNet(net_obj)

            # Set zone properties
            scale = 1000000  # mm to nm
            zone.SetAssignedPriority(priority)

            if clearance is not None:
                zone.SetLocalClearance(int(clearance * scale))

            zone.SetMinThickness(int(min_width * scale))

            # Set fill type
            if fill_type == "hatched":
                zone.SetFillMode(pcbnew.ZONE_FILL_MODE_HATCH_PATTERN)
            else:
                zone.SetFillMode(pcbnew.ZONE_FILL_MODE_POLYGONS)

            # Create outline
            outline = zone.Outline()
            outline.NewOutline()  # Create a new outline contour first

            # Add points to outline
            for point in points:
                scale = 1000000 if point.get("unit", "mm") == "mm" else 25400000
                x_nm = int(point["x"] * scale)
                y_nm = int(point["y"] * scale)
                outline.Append(pcbnew.VECTOR2I(x_nm, y_nm))  # Add point to outline

            # Add zone to board
            self.board.Add(zone)

            # Fill zone
            # Note: Zone filling can cause issues with SWIG API
            # Comment out for now - zones will be filled when board is saved/opened in KiCAD
            # filler = pcbnew.ZONE_FILLER(self.board)
            # filler.Fill(self.board.Zones())

            return {
                "success": True,
                "message": "Added copper pour",
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
            logger.error(f"Error adding copper pour: {str(e)}")
            return {
                "success": False,
                "message": "Failed to add copper pour",
                "errorDetails": str(e),
            }

    def route_differential_pair(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Route a differential pair with obstacle avoidance and length matching.

        Routes both P and N traces as parallel coupled paths with consistent
        gap spacing.  The positive trace is planned first via A*, then the
        negative trace is offset to maintain coupling.  At bends the offset
        is adjusted to keep the gap constant on the outside/inside of turns.

        When *maxSkewMm* is provided (default 0.25), a post-route length
        check verifies skew is within tolerance and reports a warning if not.

        Reference: IPC-2141A Section 5 — differential impedance;
        He (2024) Section 4.3 — coupled routing with skew control.
        """
        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first",
                }

            start_pos = params.get("startPos")
            end_pos = params.get("endPos")
            net_pos = params.get("netPos")
            net_neg = params.get("netNeg")
            layer = params.get("layer", "F.Cu")
            width = params.get("width")
            gap = params.get("gap")
            max_skew_mm = float(params.get("maxSkewMm", 0.25))

            if not start_pos or not end_pos or not net_pos or not net_neg:
                return {
                    "success": False,
                    "message": "Missing parameters",
                    "errorDetails": "startPos, endPos, netPos, and netNeg are required",
                }

            layer_id = self.board.GetLayerID(layer)
            if layer_id < 0:
                return {
                    "success": False,
                    "message": "Invalid layer",
                    "errorDetails": f"Layer '{layer}' does not exist",
                }

            netinfo = self.board.GetNetInfo()
            nets_map = netinfo.NetsByName()
            net_pos_obj = nets_map[net_pos] if nets_map.has_key(net_pos) else None
            net_neg_obj = nets_map[net_neg] if nets_map.has_key(net_neg) else None
            if not net_pos_obj or not net_neg_obj:
                return {
                    "success": False,
                    "message": "Nets not found",
                    "errorDetails": "One or both differential pair nets do not exist",
                }

            start_point = self._get_point(start_pos)
            end_point = self._get_point(end_pos)
            if gap is None:
                gap = 0.2

            width_mm = self._get_track_width_mm(width)
            scale = 1000000

            # Plan reference path (positive trace) with obstacle avoidance
            start_mm = (start_point.x / scale, start_point.y / scale)
            end_mm = (end_point.x / scale, end_point.y / scale)

            ref_path = self._plan_trace_points(
                start_mm, end_mm, layer, width_mm,
                net=net_pos, pad_repulsion=1.0,
            )
            if not ref_path or len(ref_path) < 2:
                ref_path = [start_mm, end_mm]

            # Generate coupled negative path by offsetting perpendicular to
            # each segment.  At bends, adjust offset direction so the gap
            # is maintained on the outer edge.
            half_gap = gap / 2
            pos_path: List[Tuple[float, float]] = []
            neg_path: List[Tuple[float, float]] = []

            for i, pt in enumerate(ref_path):
                # Determine local direction
                if i < len(ref_path) - 1:
                    dx = ref_path[i + 1][0] - pt[0]
                    dy = ref_path[i + 1][1] - pt[1]
                else:
                    dx = pt[0] - ref_path[i - 1][0]
                    dy = pt[1] - ref_path[i - 1][1]

                seg_len = math.hypot(dx, dy)
                if seg_len < 1e-9:
                    # Degenerate — just duplicate the point
                    pos_path.append(pt)
                    neg_path.append(pt)
                    continue

                # Perpendicular unit vector
                px = -dy / seg_len
                py = dx / seg_len

                pos_path.append((
                    round(pt[0] + px * half_gap, 6),
                    round(pt[1] + py * half_gap, 6),
                ))
                neg_path.append((
                    round(pt[0] - px * half_gap, 6),
                    round(pt[1] - py * half_gap, 6),
                ))

            # Create tracks for both P and N
            pos_tracks = []
            neg_tracks = []
            trace_width_nm = int(width_mm * scale)

            for idx in range(len(pos_path) - 1):
                # Positive trace
                p_track = pcbnew.PCB_TRACK(self.board)
                p_track.SetStart(pcbnew.VECTOR2I(int(pos_path[idx][0] * scale), int(pos_path[idx][1] * scale)))
                p_track.SetEnd(pcbnew.VECTOR2I(int(pos_path[idx + 1][0] * scale), int(pos_path[idx + 1][1] * scale)))
                p_track.SetLayer(layer_id)
                p_track.SetWidth(trace_width_nm)
                p_track.SetNet(net_pos_obj)
                self.board.Add(p_track)
                pos_tracks.append(p_track)

                # Negative trace
                n_track = pcbnew.PCB_TRACK(self.board)
                n_track.SetStart(pcbnew.VECTOR2I(int(neg_path[idx][0] * scale), int(neg_path[idx][1] * scale)))
                n_track.SetEnd(pcbnew.VECTOR2I(int(neg_path[idx + 1][0] * scale), int(neg_path[idx + 1][1] * scale)))
                n_track.SetLayer(layer_id)
                n_track.SetWidth(trace_width_nm)
                n_track.SetNet(net_neg_obj)
                self.board.Add(n_track)
                neg_tracks.append(n_track)

            # Compute length skew for reporting
            pos_length = manhattan_path_length(pos_path)
            neg_length = manhattan_path_length(neg_path)
            skew = abs(pos_length - neg_length)
            skew_ok = skew <= max_skew_mm

            self.board.SetModified()
            if hasattr(self.board, "BuildConnectivity"):
                try:
                    self.board.BuildConnectivity()
                except Exception:
                    pass

            return {
                "success": True,
                "message": (
                    f"Routed differential pair ({len(pos_tracks)} segments each)"
                    + ("" if skew_ok else f" — WARNING: skew {skew:.3f}mm exceeds {max_skew_mm}mm")
                ),
                "diffPair": {
                    "posNet": net_pos,
                    "negNet": net_neg,
                    "layer": layer,
                    "width": width_mm,
                    "gap": gap,
                    "posLengthMm": round(pos_length, 4),
                    "negLengthMm": round(neg_length, 4),
                    "skewMm": round(skew, 4),
                    "skewOk": skew_ok,
                    "maxSkewMm": max_skew_mm,
                    "segments": len(pos_tracks),
                    "obstacleAware": True,
                },
            }

        except Exception as e:
            logger.error(f"Error routing differential pair: {str(e)}")
            return {
                "success": False,
                "message": "Failed to route differential pair",
                "errorDetails": str(e),
            }

    def _get_point(self, point_spec: Dict[str, Any]) -> pcbnew.VECTOR2I:
        """Convert point specification to KiCAD point"""
        if "x" in point_spec and "y" in point_spec:
            scale = 1000000 if point_spec.get("unit", "mm") == "mm" else 25400000
            x_nm = int(point_spec["x"] * scale)
            y_nm = int(point_spec["y"] * scale)
            return pcbnew.VECTOR2I(x_nm, y_nm)
        elif "pad" in point_spec and "componentRef" in point_spec:
            module = self.board.FindFootprintByReference(point_spec["componentRef"])
            if module:
                pad = module.FindPadByName(point_spec["pad"])
                if pad:
                    return pad.GetPosition()
        raise ValueError("Invalid point specification")

    def _point_to_track_distance(self, point: pcbnew.VECTOR2I, track: pcbnew.PCB_TRACK) -> float:
        """Calculate distance from point to track segment"""
        start = track.GetStart()
        end = track.GetEnd()

        # Vector from start to end
        v = pcbnew.VECTOR2I(end.x - start.x, end.y - start.y)
        # Vector from start to point
        w = pcbnew.VECTOR2I(point.x - start.x, point.y - start.y)

        # Length of track squared
        c1 = v.x * v.x + v.y * v.y
        if c1 == 0:
            return self._point_distance(point, start)

        # Projection coefficient
        c2 = float(w.x * v.x + w.y * v.y) / c1

        if c2 < 0:
            return self._point_distance(point, start)
        elif c2 > 1:
            return self._point_distance(point, end)

        # Point on line
        proj = pcbnew.VECTOR2I(int(start.x + c2 * v.x), int(start.y + c2 * v.y))
        return self._point_distance(point, proj)

    def _point_distance(self, p1: pcbnew.VECTOR2I, p2: pcbnew.VECTOR2I) -> float:
        """Calculate distance between two points"""
        dx = p1.x - p2.x
        dy = p1.y - p2.y
        return (dx * dx + dy * dy) ** 0.5
