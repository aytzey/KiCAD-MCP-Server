"""
Routing-related command implementations for KiCAD interface
"""

import json
import logging
import math
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Sequence, Tuple

import pcbnew
from commands.orthogonal_router import (
    compress_path,
    inflate_rect,
    manhattan_path_length,
    normalize_rect,
    plan_orthogonal_path,
)
from utils.board_items import delete_board_item

logger = logging.getLogger("kicad_interface")


def _offset_polyline_miter(
    points: Sequence[Tuple[float, float]],
    offset_mm: float,
    *,
    max_miter_ratio: float = 8.0,
) -> List[Tuple[float, float]]:
    """Return a constant-distance signed polyline offset with mitered bends.

    Positive offsets are to the left of each directed segment.  Reversals and
    pathological near-parallel joins are rejected because they cannot preserve
    differential-pair spacing without a dedicated loop/fillet construction.
    """
    path: List[Tuple[float, float]] = []
    for point in points:
        normalized = (float(point[0]), float(point[1]))
        if not path or math.dist(path[-1], normalized) > 1e-9:
            path.append(normalized)
    if len(path) < 2:
        raise ValueError("Differential-pair centerline needs at least two points")

    segments: List[Tuple[float, float, float, float]] = []
    for start, end in zip(path, path[1:]):
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        length = math.hypot(dx, dy)
        if length <= 1e-9:
            raise ValueError("Differential-pair centerline contains a zero-length segment")
        ux, uy = dx / length, dy / length
        segments.append((ux, uy, -uy, ux))

    result = [
        (
            path[0][0] + segments[0][2] * offset_mm,
            path[0][1] + segments[0][3] * offset_mm,
        )
    ]
    for index in range(1, len(path) - 1):
        prev_ux, prev_uy, prev_nx, prev_ny = segments[index - 1]
        next_ux, next_uy, next_nx, next_ny = segments[index]
        denominator = prev_ux * next_uy - prev_uy * next_ux
        direction_dot = prev_ux * next_ux + prev_uy * next_uy
        if abs(denominator) <= 1e-9:
            if direction_dot < 0:
                raise ValueError("Differential-pair centerline contains a 180-degree reversal")
            join = (
                path[index][0] + prev_nx * offset_mm,
                path[index][1] + prev_ny * offset_mm,
            )
        else:
            first = (
                path[index][0] + prev_nx * offset_mm,
                path[index][1] + prev_ny * offset_mm,
            )
            second = (
                path[index][0] + next_nx * offset_mm,
                path[index][1] + next_ny * offset_mm,
            )
            delta_x, delta_y = second[0] - first[0], second[1] - first[1]
            distance_along_prev = (delta_x * next_uy - delta_y * next_ux) / denominator
            join = (
                first[0] + distance_along_prev * prev_ux,
                first[1] + distance_along_prev * prev_uy,
            )
        miter_length = math.hypot(join[0] - path[index][0], join[1] - path[index][1])
        if abs(offset_mm) > 1e-9 and miter_length > abs(offset_mm) * max_miter_ratio:
            raise ValueError("Differential-pair bend requires an unsafe over-limit miter")
        result.append(join)

    result.append(
        (
            path[-1][0] + segments[-1][2] * offset_mm,
            path[-1][1] + segments[-1][3] * offset_mm,
        )
    )
    return [(round(x, 6), round(y, 6)) for x, y in result]


# --- Net class project-file persistence (KiCad 7+) ------------------------
#
# Net class *definitions* live in the project file (``<project>.kicad_pro`` ->
# ``net_settings``), not in the ``.kicad_pcb`` board file, since KiCad 7. The
# SWIG board save only writes ``.kicad_pcb``, so a NETCLASS created on the
# in-memory board never survives a reload on its own (issue #185). These
# helpers write the class definition straight into the project JSON, which is
# what KiCad reads on open. Values are millimetres (the
# ``.kicad_pro`` unit). They are pure module functions so they can be unit
# tested without a live KiCad / SWIG round-trip.

# net_settings.classes numeric fields this tool can set (millimetres). The
# caller passes values already keyed by these names, so the persisted class
# cannot drift from differing request-key spellings (e.g. traceWidth).
_NETCLASS_NUMERIC_FIELDS = (
    "clearance",
    "track_width",
    "via_diameter",
    "via_drill",
    "microvia_diameter",
    "microvia_drill",
    "diff_pair_width",
    "diff_pair_gap",
)

# Fallback field set (KiCad 10 defaults) used only when the project has no
# "Default" class to clone the shape from.
_DEFAULT_NETCLASS_TEMPLATE = {
    "bus_width": 12,
    "clearance": 0.2,
    "diff_pair_gap": 0.25,
    "diff_pair_via_gap": 0.25,
    "diff_pair_width": 0.2,
    "line_style": 0,
    "microvia_diameter": 0.3,
    "microvia_drill": 0.1,
    "pcb_color": "rgba(0, 0, 0, 0.000)",
    "priority": 0,
    "schematic_color": "rgba(0, 0, 0, 0.000)",
    "track_width": 0.2,
    "tuning_profile": "",
    "via_diameter": 0.6,
    "via_drill": 0.3,
    "wire_width": 6,
}


def apply_netclass_to_project_settings(
    data: Dict[str, Any], name: str, props: Dict[str, Any]
) -> Dict[str, Any]:
    """Insert or update a net class *definition* in a parsed ``.kicad_pro`` dict.
    Pure: mutates and returns ``data``; performs no I/O.

    Net class definitions live in the project file's ``net_settings.classes`` on
    KiCad 7+. ``props`` is keyed by ``net_settings.classes`` field names
    (``clearance``/``track_width``/...) in millimetres; the caller normalizes the
    request keys so the persisted class never diverges from the live board. A
    new class is cloned from the project's ``Default`` class (falling back to a
    built-in template) so it carries KiCad's full field set.
    """
    net_settings = data.setdefault("net_settings", {})
    classes = net_settings.setdefault("classes", [])

    cls = next((c for c in classes if c.get("name") == name), None)
    if cls is None:
        template = next((c for c in classes if c.get("name") == "Default"), None)
        cls = dict(template) if template else dict(_DEFAULT_NETCLASS_TEMPLATE)
        cls["name"] = name
        cls["priority"] = 0  # custom classes; the Default class keeps its own priority
        classes.append(cls)

    for key in _NETCLASS_NUMERIC_FIELDS:
        value = props.get(key)
        if value is not None:
            cls[key] = float(value)

    return data


def persist_netclass_to_project(
    pro_path: Optional[str], name: str, props: Dict[str, Any]
) -> Dict[str, Any]:
    """Read/modify/write ``pro_path`` so the net class definition survives a
    reload (KiCad 7+ keeps it in the project file, not the board).

    Returns ``{"persisted": bool, "projectFile"?: str, "warning"?: str}``. Never
    raises: a persistence failure is reported, not fatal, so the in-memory net
    class still stands. The write is atomic (temp file + ``os.replace``) so a
    crash mid-write cannot corrupt the project file.
    """
    if not pro_path or not os.path.exists(pro_path):
        return {
            "persisted": False,
            "warning": "no .kicad_pro project file found; net class set in memory "
            "only and will not persist across a reload",
        }
    try:
        with open(pro_path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        apply_netclass_to_project_settings(data, name, props)

        directory = os.path.dirname(pro_path) or "."
        fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=".netclass-", suffix=".kicad_pro")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, indent=2, sort_keys=True)
                handle.write("\n")
            os.replace(tmp_path, pro_path)
        except Exception:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
            raise
        return {"persisted": True, "projectFile": pro_path}
    except Exception as exc:  # report, never fail the command on a persistence error
        return {
            "persisted": False,
            "warning": f"could not persist net class to {pro_path}: {exc}",
        }


def apply_net_assignment_to_project_settings(
    data: Dict[str, Any], net_name: str, class_name: str
) -> Dict[str, Any]:
    """Insert or update a net's netclass assignment in a parsed ``.kicad_pro`` dict.
    Pure: mutates and returns ``data``; performs no I/O.

    Explicit per-net assignments live in ``net_settings.netclass_assignments``
    on KiCad 9+ (net name -> list of class names). A net keeps only the most
    recent assignment here — composite/multi-class membership is not modeled.

    Note the key is present-but-null in a freshly written project: KiCad emits
    ``"netclass_assignments": null`` when there are no assignments (see
    ``utils/kicad_project.py``, captured from real pcbnew output). ``setdefault``
    would hand back that ``None`` rather than replacing it, so the key has to be
    normalized to a dict explicitly — otherwise assignment raises ``TypeError``
    on every real project file.
    """
    net_settings = data.setdefault("net_settings", {})
    if not isinstance(net_settings, dict):
        net_settings = {}
        data["net_settings"] = net_settings
    assignments = net_settings.get("netclass_assignments")
    if not isinstance(assignments, dict):
        assignments = {}
        net_settings["netclass_assignments"] = assignments
    assignments[net_name] = [class_name]
    return data


def persist_net_assignment_to_project(
    pro_path: Optional[str], net_name: str, class_name: str
) -> Dict[str, Any]:
    """Read/modify/write ``pro_path`` so a net's class assignment survives a
    reload (KiCad 7+ keeps net-to-class membership in the project file, not
    the board).

    Returns ``{"persisted": bool, "projectFile"?: str, "warning"?: str}``. Never
    raises: a persistence failure is reported, not fatal, so the in-memory
    assignment still stands. The write is atomic (temp file + ``os.replace``)
    so a crash mid-write cannot corrupt the project file.
    """
    if not pro_path or not os.path.exists(pro_path):
        return {
            "persisted": False,
            "warning": "no .kicad_pro project file found; net class assignment set "
            "in memory only and will not persist across a reload",
        }
    try:
        with open(pro_path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        apply_net_assignment_to_project_settings(data, net_name, class_name)

        directory = os.path.dirname(pro_path) or "."
        fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=".netassign-", suffix=".kicad_pro")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, indent=2, sort_keys=True)
                handle.write("\n")
            os.replace(tmp_path, pro_path)
        except Exception:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
            raise
        return {"persisted": True, "projectFile": pro_path}
    except Exception as exc:  # report, never fail the command on a persistence error
        return {
            "persisted": False,
            "warning": f"could not persist net class assignment to {pro_path}: {exc}",
        }


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
                abs(point[0] - start_point[0])
                + abs(point[1] - start_point[1])
                + abs(point[0] - end_point[0])
                + abs(point[1] - end_point[1])
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

    def _get_footprint_pad_rect(self, footprint) -> Optional[Tuple[float, float, float, float]]:
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
            target_cost = abs(candidates[idx][0] - target_point[0]) + abs(
                candidates[idx][1] - target_point[1]
            )
            crowd_cost = pad_crowds[idx]
            return edge_cost + 0.5 * target_cost + 2.0 * crowd_cost

        best_idx = min(range(4), key=_escape_score)
        best = candidates[best_idx]
        return (round(best[0], 6), round(best[1], 6))

    @staticmethod
    def _pair_midpoint(
        pos_point: Tuple[float, float],
        neg_point: Tuple[float, float],
    ) -> Tuple[float, float]:
        return (
            round((pos_point[0] + neg_point[0]) / 2.0, 6),
            round((pos_point[1] + neg_point[1]) / 2.0, 6),
        )

    @staticmethod
    def _offset_pair_about_center(
        center: Tuple[float, float],
        guide_point: Tuple[float, float],
        gap: float,
    ) -> Tuple[Tuple[float, float], Tuple[float, float]]:
        dx = guide_point[0] - center[0]
        dy = guide_point[1] - center[1]
        seg_len = math.hypot(dx, dy)
        if seg_len < 1e-9:
            dx = 1.0
            dy = 0.0
            seg_len = 1.0
        px = -dy / seg_len
        py = dx / seg_len
        half_gap = gap / 2.0
        return (
            (round(center[0] + px * half_gap, 6), round(center[1] + py * half_gap, 6)),
            (round(center[0] - px * half_gap, 6), round(center[1] - py * half_gap, 6)),
        )

    @staticmethod
    def _point_hits_obstacle(
        point: Tuple[float, float],
        obstacles: List[Tuple[float, float, float, float]],
    ) -> bool:
        x, y = point
        return any(rect[0] < x < rect[2] and rect[1] < y < rect[3] for rect in obstacles)

    def _select_paired_via_positions(
        self,
        *,
        anchor_mid: Tuple[float, float],
        guide_point: Tuple[float, float],
        from_layer: str,
        to_layer: str,
        gap: float,
        width_mm: float,
        ignored_refs: Optional[List[str]] = None,
        net: Optional[str] = None,
    ) -> Dict[str, Any]:
        keepout_margin = self._get_clearance_mm() + width_mm / 2.0
        obstacles = self._collect_routing_obstacles(
            from_layer,
            keepout_margin,
            ignored_refs=ignored_refs,
            net=net,
        ) + self._collect_routing_obstacles(
            to_layer,
            keepout_margin,
            ignored_refs=ignored_refs,
            net=net,
        )

        dx = guide_point[0] - anchor_mid[0]
        dy = guide_point[1] - anchor_mid[1]
        seg_len = math.hypot(dx, dy)
        if seg_len < 1e-9:
            dx = 1.0
            dy = 0.0
            seg_len = 1.0
        ux = dx / seg_len
        uy = dy / seg_len
        px = -uy
        py = ux
        base_offset = max(gap * 1.5, width_mm * 6.0, keepout_margin * 2.0, 0.8)

        preferred_center = (
            round(anchor_mid[0] + ux * base_offset, 6),
            round(anchor_mid[1] + uy * base_offset, 6),
        )
        candidate_centers = [
            preferred_center,
            (
                round(anchor_mid[0] + ux * base_offset * 1.5, 6),
                round(anchor_mid[1] + uy * base_offset * 1.5, 6),
            ),
            (
                round(anchor_mid[0] + ux * base_offset * 2.0, 6),
                round(anchor_mid[1] + uy * base_offset * 2.0, 6),
            ),
            (
                round(preferred_center[0] + px * gap / 2.0, 6),
                round(preferred_center[1] + py * gap / 2.0, 6),
            ),
            (
                round(preferred_center[0] - px * gap / 2.0, 6),
                round(preferred_center[1] - py * gap / 2.0, 6),
            ),
            self._find_best_via_position(
                anchor_mid,
                preferred_center,
                from_layer,
                to_layer,
                keepout_margin,
                list(ignored_refs or []),
                net,
            ),
        ]

        unique_centers: List[Tuple[float, float]] = []
        seen = set()
        for center in candidate_centers:
            key = (round(center[0], 4), round(center[1], 4))
            if key in seen:
                continue
            seen.add(key)
            unique_centers.append(center)

        ranked: List[Dict[str, Any]] = []
        stitch_offset = max(gap * 1.35, width_mm * 5.0, keepout_margin * 2.5, 0.75)
        for center in unique_centers:
            pos_via, neg_via = self._offset_pair_about_center(center, guide_point, gap)
            reference_candidates = [
                (
                    round(center[0] + px * stitch_offset, 6),
                    round(center[1] + py * stitch_offset, 6),
                ),
                (
                    round(center[0] - px * stitch_offset, 6),
                    round(center[1] - py * stitch_offset, 6),
                ),
            ]
            reference_vias = [
                point
                for point in reference_candidates
                if not self._point_hits_obstacle(point, obstacles)
            ]
            blocked_count = int(self._point_hits_obstacle(pos_via, obstacles)) + int(
                self._point_hits_obstacle(neg_via, obstacles)
            )
            wirelength = (
                abs(center[0] - anchor_mid[0])
                + abs(center[1] - anchor_mid[1])
                + abs(guide_point[0] - center[0])
                + abs(guide_point[1] - center[1])
            )
            ranked.append(
                {
                    "center": center,
                    "posVia": pos_via,
                    "negVia": neg_via,
                    "referenceVias": reference_vias,
                    "referenceBlockedCount": len(reference_candidates) - len(reference_vias),
                    "blockedCount": blocked_count,
                    "wirelengthScore": round(wirelength, 4),
                }
            )

        ranked.sort(
            key=lambda item: (
                item["blockedCount"],
                item["referenceBlockedCount"],
                item["wirelengthScore"],
            )
        )
        selected = ranked[0]
        return {
            "center": selected["center"],
            "posVia": selected["posVia"],
            "negVia": selected["negVia"],
            "referenceVias": selected["referenceVias"],
            "referenceBlockedCount": selected["referenceBlockedCount"],
            "blockedCount": selected["blockedCount"],
            "candidates": ranked,
        }

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
        self,
        layer: str,
        *,
        net: Optional[str] = None,
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

            # Set net class if provided — defensive against KiCad 6/7 vs KiCad 9/10 API.
            if net_class:
                net_classes = self.board.GetNetClasses()
                resolved = None
                if hasattr(net_classes, "Find"):
                    resolved = net_classes.Find(net_class)
                else:
                    try:
                        if net_class in net_classes:
                            resolved = net_classes[net_class]
                    except Exception:
                        resolved = None
                if resolved is not None:
                    net.SetClass(resolved)

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
                )
                end_route = self._plan_trace_points(
                    (via_x, via_y),
                    end_escape,
                    end_layer,
                    width_mm,
                    net=net,
                    ignored_refs=[to_ref],
                )
                if start_route is None or end_route is None:
                    failed_leg = start_layer if start_route is None else end_layer
                    return {
                        "success": False,
                        "message": "Failed to route pad to pad",
                        "errorDetails": (
                            "Obstacle-aware planner could not find a clearance-safe "
                            f"path for the {failed_leg} via leg"
                        ),
                    }

                start_full_route = compress_path([start_point_mm] + start_route)
                end_full_route = compress_path(end_route + [end_point_mm])

                # Trace on start layer: start_pad → via
                r1 = self.route_trace(
                    {
                        "start": {"x": start_point_mm[0], "y": start_point_mm[1], "unit": "mm"},
                        "end": {"x": via_x, "y": via_y, "unit": "mm"},
                        "layer": start_layer,
                        "width": width_mm,
                        "net": net,
                        "waypoints": [
                            {"x": p[0], "y": p[1], "unit": "mm"} for p in start_full_route[1:-1]
                        ],
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
                        "waypoints": [
                            {"x": p[0], "y": p[1], "unit": "mm"} for p in end_full_route[1:-1]
                        ],
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
                if middle_route is None:
                    return {
                        "success": False,
                        "message": "Failed to route pad to pad",
                        "errorDetails": (
                            "Obstacle-aware planner could not find a clearance-safe path "
                            f"on {layer if layer else start_layer}"
                        ),
                    }
                full_route = compress_path([start_point_mm] + middle_route + [end_point_mm])
                result = self.route_trace(
                    {
                        "start": {"x": start_point_mm[0], "y": start_point_mm[1], "unit": "mm"},
                        "end": {"x": end_point_mm[0], "y": end_point_mm[1], "unit": "mm"},
                        "layer": layer if layer else start_layer,
                        "width": width_mm,
                        "net": net,
                        "waypoints": [
                            {"x": p[0], "y": p[1], "unit": "mm"} for p in full_route[1:-1]
                        ],
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
                if planned_points is None:
                    return {
                        "success": False,
                        "message": "Failed to route trace",
                        "errorDetails": (
                            "Obstacle-aware planner could not find a clearance-safe path "
                            f"from {start_mm} to {end_mm} on {layer}"
                        ),
                    }
                path_points = compress_path(planned_points)

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

    def route_arc_trace(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Route a copper arc trace from start/mid/end points."""
        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first",
                }

            start = params.get("start")
            mid = params.get("mid")
            end = params.get("end")
            layer = params.get("layer", "F.Cu")
            width = params.get("width")
            net = params.get("net")

            if not start or not mid or not end:
                return {
                    "success": False,
                    "message": "Missing parameters",
                    "errorDetails": "start, mid and end points are required",
                }

            layer_id = self.board.GetLayerID(layer)
            if layer_id < 0:
                return {
                    "success": False,
                    "message": "Invalid layer",
                    "errorDetails": f"Layer '{layer}' does not exist",
                }

            start_point = self._get_point(start)
            mid_point = self._get_point(mid)
            end_point = self._get_point(end)

            arc = pcbnew.PCB_ARC(self.board)
            arc.SetStart(start_point)
            arc.SetMid(mid_point)
            arc.SetEnd(end_point)
            arc.SetLayer(layer_id)

            if width:
                arc.SetWidth(int(width * 1000000))
            else:
                arc.SetWidth(self.board.GetDesignSettings().GetCurrentTrackWidth())

            if net:
                netinfo = self.board.GetNetInfo()
                nets_map = netinfo.NetsByName()
                if nets_map.has_key(net):
                    arc.SetNet(nets_map[net])

            self.board.Add(arc)

            return {
                "success": True,
                "message": "Added arc trace",
                "arc": {
                    "start": {
                        "x": start_point.x / 1000000,
                        "y": start_point.y / 1000000,
                        "unit": "mm",
                    },
                    "mid": {"x": mid_point.x / 1000000, "y": mid_point.y / 1000000, "unit": "mm"},
                    "end": {"x": end_point.x / 1000000, "y": end_point.y / 1000000, "unit": "mm"},
                    "layer": layer,
                    "width": arc.GetWidth() / 1000000,
                    "net": net,
                },
            }
        except Exception as e:
            logger.error(f"Error routing arc trace: {str(e)}")
            return {
                "success": False,
                "message": "Failed to route arc trace",
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
            scale = (
                1000000
                if position["unit"] == "mm"
                else (25400 if position["unit"] == "mil" else 25400000)
            )  # mm, mil, or inch to nm
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

            # Delete by net name (bulk delete), use "*" to delete all tracks
            if net_name:
                tracks_to_remove = []
                for track in list(self.board.Tracks()):
                    if net_name != "*" and track.GetNetname() != net_name:
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
                    delete_board_item(self.board, track)
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
                for item in list(self.board.Tracks()):
                    if item.m_Uuid.AsString() == trace_uuid:
                        track = item
                        break

                if not track:
                    return {
                        "success": False,
                        "message": "Track not found",
                        "errorDetails": f"Could not find track with UUID: {trace_uuid}",
                    }

                delete_board_item(self.board, track)
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
                scale = (
                    1000000
                    if position["unit"] == "mm"
                    else (25400 if position["unit"] == "mil" else 25400000)
                )  # mm, mil, or inch to nm
                x_nm = int(position["x"] * scale)
                y_nm = int(position["y"] * scale)
                point = pcbnew.VECTOR2I(x_nm, y_nm)

                # Find closest track
                closest_track = None
                min_distance = float("inf")
                for track in list(self.board.Tracks()):
                    dist = self._point_to_track_distance(point, track)
                    if dist < min_distance:
                        min_distance = dist
                        closest_track = track

                if closest_track and min_distance < 1000000:  # Within 1mm
                    delete_board_item(self.board, closest_track)
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
            for track in list(self.board.Tracks()):
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
                        bbox_scale = (
                            scale
                            if bbox_unit == "mm"
                            else (25400 if bbox_unit == "mil" else 25400000)
                        )
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

    def query_zones(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Query copper zones (filled pours) by net, layer, or bounding box.

        Returns one entry per zone with its net, layers, priority, fill state,
        and bounding box. Useful for auditing power planes / GND pours that
        ``query_traces`` does not report (zones are PCB_ZONE_T, not tracks).
        """
        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first",
                }

            net_name = params.get("net")
            layer = params.get("layer")
            bbox = params.get("boundingBox")

            scale = 1000000  # nm -> mm
            target_layer_id = None
            if layer:
                target_layer_id = self.board.GetLayerID(layer)

            bbox_box = None
            if bbox:
                bbox_unit = bbox.get("unit", "mm")
                bbox_scale = scale if bbox_unit == "mm" else 25400000
                bbox_box = (
                    int(bbox.get("x1", 0) * bbox_scale),
                    int(bbox.get("y1", 0) * bbox_scale),
                    int(bbox.get("x2", 0) * bbox_scale),
                    int(bbox.get("y2", 0) * bbox_scale),
                )

            zones_out = []
            for zone in list(self.board.Zones()):
                try:
                    z_net = zone.GetNetname()
                    if net_name and z_net != net_name:
                        continue

                    # A zone can span multiple copper layers; collect them.
                    layer_names = []
                    try:
                        layer_set = zone.GetLayerSet()
                        seq = (
                            layer_set.CuStack()
                            if hasattr(layer_set, "CuStack")
                            else layer_set.Seq()
                        )
                        for lid in seq:
                            layer_names.append(self.board.GetLayerName(lid))
                    except Exception:
                        layer_names = [self.board.GetLayerName(zone.GetLayer())]

                    if target_layer_id is not None:
                        if target_layer_id not in [self.board.GetLayerID(n) for n in layer_names]:
                            continue

                    bb = zone.GetBoundingBox()
                    bb_x1, bb_y1 = bb.GetLeft(), bb.GetTop()
                    bb_x2, bb_y2 = bb.GetRight(), bb.GetBottom()

                    if bbox_box is not None:
                        x1, y1, x2, y2 = bbox_box
                        # Reject if no overlap with filter bbox.
                        if bb_x2 < x1 or bb_x1 > x2 or bb_y2 < y1 or bb_y1 > y2:
                            continue

                    entry = {
                        "uuid": zone.m_Uuid.AsString(),
                        "net": z_net,
                        "netCode": zone.GetNetCode(),
                        "layers": layer_names,
                        "priority": (
                            zone.GetAssignedPriority()
                            if hasattr(zone, "GetAssignedPriority")
                            else 0
                        ),
                        "isFilled": bool(zone.IsFilled()),
                        "minThickness": zone.GetMinThickness() / scale,
                        "boundingBox": {
                            "x1": bb_x1 / scale,
                            "y1": bb_y1 / scale,
                            "x2": bb_x2 / scale,
                            "y2": bb_y2 / scale,
                            "unit": "mm",
                        },
                    }
                    # Area is only available when zone is filled.
                    try:
                        entry["filledArea"] = zone.GetFilledArea() / (scale * scale)
                    except Exception:
                        pass

                    zones_out.append(entry)
                except Exception as zone_err:
                    logger.warning(f"Skipping invalid zone object: {zone_err}")
                    continue

            return {
                "success": True,
                "zoneCount": len(zones_out),
                "zones": zones_out,
            }

        except Exception as e:
            logger.error(f"Error querying zones: {str(e)}")
            return {
                "success": False,
                "message": "Failed to query zones",
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
                for item in list(self.board.Tracks()):
                    if item.m_Uuid.AsString() == trace_uuid:
                        track = item
                        break
            elif position:
                pos_unit = position.get("unit", "mm")
                pos_scale = (
                    scale if pos_unit == "mm" else (25400 if pos_unit == "mil" else 25400000)
                )
                x_nm = int(position["x"] * pos_scale)
                y_nm = int(position["y"] * pos_scale)
                point = pcbnew.VECTOR2I(x_nm, y_nm)

                # Find closest track
                min_distance = float("inf")
                for item in list(self.board.Tracks()):
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

            for track in list(self.board.Tracks()):
                is_via = track.Type() == pcbnew.PCB_VIA_T

                if use_net_filter:
                    # Primary: net-based filter
                    if track.GetNetname() not in source_nets:
                        continue
                else:
                    # Fallback: geometric filter — trace start OR end inside source bbox
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
            # Schema exposes "traceWidth"; older callers may send "trackWidth". Accept both.
            track_width = params.get("traceWidth", params.get("trackWidth"))
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

            # Net class DEFINITIONS live in <project>.kicad_pro (net_settings) on
            # KiCad 7+, not in the .kicad_pcb the SWIG board save writes. Resolve
            # the project file up front so the durable write below runs even if a
            # SWIG API (which shifted across KiCad 6->10) throws (issue #185).
            pro_path = None
            try:
                board_path = self.board.GetFileName()
                if board_path and board_path.endswith(".kicad_pcb"):
                    pro_path = str(Path(board_path).with_suffix(".kicad_pro"))
            except Exception:
                pro_path = None

            scale = 1000000  # mm to nm
            net_class_values: Dict[str, Any] = {}
            in_memory_warning = None

            # Best-effort in-memory NETCLASS for the live session. A SWIG failure
            # here is logged but must NOT skip the .kicad_pro persistence below,
            # which is the deterministic, SWIG-independent part (issue #185).
            try:
                # KiCad 6/7 returns NETCLASSES with .Find/.Add; KiCad 9/10 returns
                # a netclasses_map (SWIG-wrapped std::map) that is dict-like.
                net_classes = self.board.GetNetClasses()

                existing = None
                if hasattr(net_classes, "Find"):
                    existing = net_classes.Find(name)
                else:
                    try:
                        if name in net_classes:
                            existing = net_classes[name]
                    except Exception:
                        existing = None

                if existing is None:
                    netclass = pcbnew.NETCLASS(name)
                    if hasattr(net_classes, "Add"):
                        net_classes.Add(netclass)
                    else:
                        net_classes[name] = netclass
                else:
                    netclass = existing

                # Defensive setters — KiCad 10's NETCLASS dropped some legacy mutators.
                def _safe_set(method_name, value):
                    if value is None:
                        return
                    method = getattr(netclass, method_name, None)
                    if method is None:
                        return
                    try:
                        method(int(value * scale))
                    except Exception:
                        pass

                _safe_set("SetClearance", clearance)
                _safe_set("SetTrackWidth", track_width)
                _safe_set("SetViaDiameter", via_diameter)
                _safe_set("SetViaDrill", via_drill)
                _safe_set("SetMicroViaDiameter", uvia_diameter)
                _safe_set("SetMicroViaDrill", uvia_drill)
                _safe_set("SetDiffPairWidth", diff_pair_width)
                _safe_set("SetDiffPairGap", diff_pair_gap)

                netinfo = self.board.GetNetInfo()
                nets_map = netinfo.NetsByName()
                for net_name in nets:
                    if nets_map.has_key(net_name):
                        net = nets_map[net_name]
                        net.SetClass(netclass)

                # Defensive accessors — KiCad 10's NETCLASS dropped some legacy getters.
                def _safe_get(method_name):
                    method = getattr(netclass, method_name, None)
                    if method is None:
                        return None
                    try:
                        return method() / scale
                    except Exception:
                        return None

                net_class_values = {
                    "clearance": _safe_get("GetClearance"),
                    "trackWidth": _safe_get("GetTrackWidth"),
                    "viaDiameter": _safe_get("GetViaDiameter"),
                    "viaDrill": _safe_get("GetViaDrill"),
                    "uviaDiameter": _safe_get("GetMicroViaDiameter"),
                    "uviaDrill": _safe_get("GetMicroViaDrill"),
                    "diffPairWidth": _safe_get("GetDiffPairWidth"),
                    "diffPairGap": _safe_get("GetDiffPairGap"),
                }
            except Exception as exc:
                in_memory_warning = "in-memory NETCLASS update failed: %s" % exc
                logger.warning("create_netclass: %s", in_memory_warning)

            # Persist the class DEFINITION (net_settings.classes) using the same
            # normalized values as the live path, so the persisted class can never
            # diverge from the request. Membership lives in netclass_patterns and
            # is out of scope here (create_netclass exposes no `nets` field).
            project_props = {
                "clearance": clearance,
                "track_width": track_width,
                "via_diameter": via_diameter,
                "via_drill": via_drill,
                "microvia_diameter": uvia_diameter,
                "microvia_drill": uvia_drill,
                "diff_pair_width": diff_pair_width,
                "diff_pair_gap": diff_pair_gap,
            }
            persist = persist_netclass_to_project(pro_path, name, project_props)

            warnings = [w for w in (in_memory_warning, persist.get("warning")) if w]
            if in_memory_warning and not persist.get("persisted"):
                # Neither the live board nor the project file received the class.
                return {
                    "success": False,
                    "message": "Failed to create net class",
                    "errorDetails": "; ".join(warnings),
                }

            result = {
                "success": True,
                "message": f"Created net class: {name}",
                "netClass": {"name": name, "nets": nets, **net_class_values},
                "persisted": persist.get("persisted", False),
            }
            if persist.get("projectFile"):
                result["projectFile"] = persist["projectFile"]
            if warnings:
                result["warning"] = "; ".join(warnings)
            return result

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
            pad_connection = params.get("padConnection")

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

            if pad_connection is not None:
                connection_names = {
                    "thermal": "ZONE_CONNECTION_THERMAL",
                    "solid": "ZONE_CONNECTION_FULL",
                    "none": "ZONE_CONNECTION_NONE",
                }
                constant_name = connection_names.get(str(pad_connection).lower())
                connection_value = getattr(pcbnew, constant_name, None) if constant_name else None
                setter = getattr(zone, "SetPadConnection", None)
                if connection_value is None or not callable(setter):
                    return {
                        "success": False,
                        "message": f"Unsupported padConnection: {pad_connection}",
                    }
                setter(connection_value)

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
                scale = (
                    1000000
                    if point.get("unit", "mm") == "mm"
                    else (25400 if point.get("unit", "mm") == "mil" else 25400000)
                )
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
                    "padConnection": pad_connection,
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
            start_pos_pos = params.get("startPosPos")
            start_pos_neg = params.get("startPosNeg")
            end_pos_pos = params.get("endPosPos")
            end_pos_neg = params.get("endPosNeg")
            net_pos = params.get("netPos")
            net_neg = params.get("netNeg")
            layer = params.get("layer", "F.Cu")
            start_layer = params.get("startLayer", layer)
            end_layer = params.get("endLayer", layer)
            start_ref = params.get("startRef")
            end_ref = params.get("endRef")
            width = params.get("width")
            gap = params.get("gap")
            max_skew_mm = float(params.get("maxSkewMm", 0.25))
            allow_layer_transitions = bool(params.get("allowLayerTransitions", True))
            reference_net = params.get("referenceNet")
            add_return_path_stitching_param = params.get("addReturnPathStitching")
            add_return_path_stitching = (
                bool(reference_net)
                if add_return_path_stitching_param is None
                else bool(add_return_path_stitching_param)
            )

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
            reference_net_available = bool(reference_net and nets_map.has_key(reference_net))

            start_point = self._get_point(start_pos)
            end_point = self._get_point(end_pos)
            if gap is None:
                gap = 0.2
            gap = float(gap)

            width_mm = self._get_track_width_mm(width)
            scale = 1000000
            start_mid_mm = (start_point.x / scale, start_point.y / scale)
            end_mid_mm = (end_point.x / scale, end_point.y / scale)

            def _point_spec_to_mm(
                point_spec: Optional[Dict[str, Any]],
            ) -> Optional[Tuple[float, float]]:
                if not point_spec:
                    return None
                point = self._get_point(point_spec)
                return (point.x / scale, point.y / scale)

            route_start_pos_mm = _point_spec_to_mm(start_pos_pos)
            route_start_neg_mm = _point_spec_to_mm(start_pos_neg)
            route_end_pos_mm = _point_spec_to_mm(end_pos_pos)
            route_end_neg_mm = _point_spec_to_mm(end_pos_neg)
            transition_via_count = 0
            transition_stitch_via_count = 0
            start_transition: Optional[Dict[str, Any]] = None
            end_transition: Optional[Dict[str, Any]] = None

            def _route_pair_transition(
                *,
                pos_point: Tuple[float, float],
                neg_point: Tuple[float, float],
                from_layer_name: str,
                to_layer_name: str,
                site_mid: Tuple[float, float],
                guide_mid: Tuple[float, float],
                site_ref: Optional[str],
                transition_name: str,
            ) -> Dict[str, Any]:
                if from_layer_name == to_layer_name:
                    return {
                        "success": True,
                        "pos": pos_point,
                        "neg": neg_point,
                        "viaCount": 0,
                        "stitchViaCount": 0,
                        "name": transition_name,
                    }
                if not allow_layer_transitions:
                    return {
                        "success": False,
                        "message": "Differential pair layer transitions are disabled",
                        "errorDetails": {
                            "transition": transition_name,
                            "fromLayer": from_layer_name,
                            "toLayer": to_layer_name,
                        },
                    }

                ignored_refs = [site_ref] if site_ref else []
                via_plan = self._select_paired_via_positions(
                    anchor_mid=site_mid,
                    guide_point=guide_mid,
                    from_layer=from_layer_name,
                    to_layer=to_layer_name,
                    gap=gap,
                    width_mm=width_mm,
                    ignored_refs=ignored_refs,
                    net=net_pos,
                )
                pos_via = via_plan["posVia"]
                neg_via = via_plan["negVia"]

                pos_trace = self.route_trace(
                    {
                        "start": {"x": pos_point[0], "y": pos_point[1], "unit": "mm"},
                        "end": {"x": pos_via[0], "y": pos_via[1], "unit": "mm"},
                        "layer": from_layer_name,
                        "width": width_mm,
                        "net": net_pos,
                        "ignoreRefs": ignored_refs,
                    }
                )
                neg_trace = self.route_trace(
                    {
                        "start": {"x": neg_point[0], "y": neg_point[1], "unit": "mm"},
                        "end": {"x": neg_via[0], "y": neg_via[1], "unit": "mm"},
                        "layer": from_layer_name,
                        "width": width_mm,
                        "net": net_neg,
                        "ignoreRefs": ignored_refs,
                    }
                )
                pos_via_result = self.add_via(
                    {
                        "position": {"x": pos_via[0], "y": pos_via[1], "unit": "mm"},
                        "net": net_pos,
                        "from_layer": from_layer_name,
                        "to_layer": to_layer_name,
                    }
                )
                neg_via_result = self.add_via(
                    {
                        "position": {"x": neg_via[0], "y": neg_via[1], "unit": "mm"},
                        "net": net_neg,
                        "from_layer": from_layer_name,
                        "to_layer": to_layer_name,
                    }
                )
                if not (
                    pos_trace.get("success")
                    and neg_trace.get("success")
                    and pos_via_result.get("success")
                    and neg_via_result.get("success")
                ):
                    return {
                        "success": False,
                        "message": f"Failed to create {transition_name} differential-pair transition",
                        "errorDetails": {
                            "transition": transition_name,
                            "posTrace": pos_trace,
                            "negTrace": neg_trace,
                            "posVia": pos_via_result,
                            "negVia": neg_via_result,
                        },
                    }
                stitch_vias: List[Dict[str, Any]] = []
                stitch_failures: List[Dict[str, Any]] = []
                stitch_skipped_reason: Optional[str] = None
                if add_return_path_stitching and reference_net:
                    if not reference_net_available:
                        stitch_skipped_reason = "reference_net_not_found"
                    else:
                        for stitch_point in via_plan.get("referenceVias", []):
                            stitch_params = {
                                "position": {
                                    "x": stitch_point[0],
                                    "y": stitch_point[1],
                                    "unit": "mm",
                                },
                                "net": reference_net,
                                "from_layer": from_layer_name,
                                "to_layer": to_layer_name,
                            }
                            stitch_result = self.add_via(stitch_params)
                            stitch_record = {
                                "position": stitch_params["position"],
                                "net": reference_net,
                                "fromLayer": from_layer_name,
                                "toLayer": to_layer_name,
                            }
                            if stitch_result.get("success"):
                                stitch_vias.append(stitch_record)
                            else:
                                stitch_record["errorDetails"] = stitch_result
                                stitch_failures.append(stitch_record)
                return {
                    "success": True,
                    "name": transition_name,
                    "fromLayer": from_layer_name,
                    "toLayer": to_layer_name,
                    "center": {
                        "x": via_plan["center"][0],
                        "y": via_plan["center"][1],
                        "unit": "mm",
                    },
                    "pos": pos_via,
                    "neg": neg_via,
                    "viaCount": 2,
                    "referenceNet": reference_net,
                    "stitchViaCount": len(stitch_vias),
                    "stitchVias": stitch_vias,
                    "stitchFailures": stitch_failures,
                    "stitchSkippedReason": stitch_skipped_reason,
                    "referenceBlockedCandidates": via_plan.get("referenceBlockedCount", 0),
                    "blockedCandidates": via_plan["blockedCount"],
                }

            if start_layer != layer:
                if route_start_pos_mm is None or route_start_neg_mm is None:
                    return {
                        "success": False,
                        "message": "Missing start pair geometry for differential-pair transition",
                        "errorDetails": "startPosPos and startPosNeg are required when startLayer != layer",
                    }
                start_transition = _route_pair_transition(
                    pos_point=route_start_pos_mm,
                    neg_point=route_start_neg_mm,
                    from_layer_name=start_layer,
                    to_layer_name=layer,
                    site_mid=start_mid_mm,
                    guide_mid=end_mid_mm,
                    site_ref=start_ref,
                    transition_name="start",
                )
                if not start_transition.get("success"):
                    return start_transition
                route_start_pos_mm = start_transition["pos"]
                route_start_neg_mm = start_transition["neg"]
                transition_via_count += int(start_transition.get("viaCount", 0))
                transition_stitch_via_count += int(start_transition.get("stitchViaCount", 0))

            if end_layer != layer:
                if route_end_pos_mm is None or route_end_neg_mm is None:
                    return {
                        "success": False,
                        "message": "Missing end pair geometry for differential-pair transition",
                        "errorDetails": "endPosPos and endPosNeg are required when endLayer != layer",
                    }
                end_transition = _route_pair_transition(
                    pos_point=route_end_pos_mm,
                    neg_point=route_end_neg_mm,
                    from_layer_name=end_layer,
                    to_layer_name=layer,
                    site_mid=end_mid_mm,
                    guide_mid=start_mid_mm,
                    site_ref=end_ref,
                    transition_name="end",
                )
                if not end_transition.get("success"):
                    return end_transition
                route_end_pos_mm = end_transition["pos"]
                route_end_neg_mm = end_transition["neg"]
                transition_via_count += int(end_transition.get("viaCount", 0))
                transition_stitch_via_count += int(end_transition.get("stitchViaCount", 0))

            route_start_mid_mm = (
                self._pair_midpoint(route_start_pos_mm, route_start_neg_mm)
                if route_start_pos_mm is not None and route_start_neg_mm is not None
                else start_mid_mm
            )
            route_end_mid_mm = (
                self._pair_midpoint(route_end_pos_mm, route_end_neg_mm)
                if route_end_pos_mm is not None and route_end_neg_mm is not None
                else end_mid_mm
            )
            if route_start_pos_mm is None or route_start_neg_mm is None:
                route_start_pos_mm, route_start_neg_mm = self._offset_pair_about_center(
                    route_start_mid_mm,
                    route_end_mid_mm,
                    gap,
                )
            if route_end_pos_mm is None or route_end_neg_mm is None:
                route_end_pos_mm, route_end_neg_mm = self._offset_pair_about_center(
                    route_end_mid_mm,
                    route_start_mid_mm,
                    gap,
                )

            # Plan reference path (positive trace) with obstacle avoidance
            ref_path = self._plan_trace_points(
                route_start_mid_mm,
                route_end_mid_mm,
                layer,
                width_mm + gap,
                net=net_pos,
                pad_repulsion=1.0,
            )
            if not ref_path or len(ref_path) < 2:
                return {
                    "success": False,
                    "message": "Failed to route differential pair",
                    "errorDetails": (
                        "Obstacle-aware planner could not find a path for the full "
                        "differential-pair envelope"
                    ),
                }

            # Generate coupled negative path by offsetting perpendicular to
            # each segment.  At bends, adjust offset direction so the gap
            # is maintained on the outer edge.
            half_gap = gap / 2
            left_path = _offset_polyline_miter(ref_path, half_gap)
            right_path = _offset_polyline_miter(ref_path, -half_gap)

            def endpoint_mismatch(
                candidate_pos: Sequence[Tuple[float, float]],
                candidate_neg: Sequence[Tuple[float, float]],
            ) -> Tuple[float, float]:
                distances = [
                    math.dist(candidate_pos[0], route_start_pos_mm),
                    math.dist(candidate_pos[-1], route_end_pos_mm),
                    math.dist(candidate_neg[0], route_start_neg_mm),
                    math.dist(candidate_neg[-1], route_end_neg_mm),
                ]
                return sum(distances), max(distances)

            normal_cost = endpoint_mismatch(left_path, right_path)
            swapped_cost = endpoint_mismatch(right_path, left_path)
            if swapped_cost[0] < normal_cost[0]:
                pos_path, neg_path = right_path, left_path
                selected_mismatch = swapped_cost[1]
            else:
                pos_path, neg_path = left_path, right_path
                selected_mismatch = normal_cost[1]

            endpoint_tolerance = max(0.05, width_mm * 0.75)
            if selected_mismatch > endpoint_tolerance:
                return {
                    "success": False,
                    "message": "Failed to route differential pair",
                    "errorDetails": (
                        "Pair endpoints do not align with the requested center spacing; "
                        "a dedicated fanout transition is required"
                    ),
                }

            pos_path[0] = route_start_pos_mm
            neg_path[0] = route_start_neg_mm
            pos_path[-1] = route_end_pos_mm
            neg_path[-1] = route_end_neg_mm

            # Create tracks for both P and N
            pos_tracks = []
            neg_tracks = []

            for idx in range(len(pos_path) - 1):
                pos_tracks.append(
                    self._add_track_segment(
                        pcbnew.VECTOR2I(
                            int(pos_path[idx][0] * scale), int(pos_path[idx][1] * scale)
                        ),
                        pcbnew.VECTOR2I(
                            int(pos_path[idx + 1][0] * scale), int(pos_path[idx + 1][1] * scale)
                        ),
                        layer_id,
                        width_mm,
                        net_pos,
                    )
                )
                neg_tracks.append(
                    self._add_track_segment(
                        pcbnew.VECTOR2I(
                            int(neg_path[idx][0] * scale), int(neg_path[idx][1] * scale)
                        ),
                        pcbnew.VECTOR2I(
                            int(neg_path[idx + 1][0] * scale), int(neg_path[idx + 1][1] * scale)
                        ),
                        layer_id,
                        width_mm,
                        net_neg,
                    )
                )

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
                    "viaCount": transition_via_count,
                    "stitchViaCount": transition_stitch_via_count,
                    "returnPathStitching": transition_stitch_via_count > 0,
                    "returnPathStitchingRequested": bool(
                        add_return_path_stitching and reference_net
                    ),
                    "referenceNet": reference_net,
                    "pairedTransitions": transition_via_count > 0,
                    "startTransition": start_transition,
                    "endTransition": end_transition,
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
            scale = (
                1000000
                if point_spec.get("unit", "mm") == "mm"
                else (25400 if point_spec.get("unit", "mm") == "mil" else 25400000)
            )
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

    # -----------------------------------------------------------------------
    # add_gnd_stitching_vias
    #
    # Originally prototyped in morningfire-pcb-automation:
    #   https://github.com/NiNjA-CodE/morningfire-pcb-automation
    #   (scripts/ground/add_gnd_vias.py — regex-on-PCB-text version)
    #
    # The version here uses the pcbnew API so it handles arbitrary
    # rotations, gets net IDs / clearances from the loaded board, and
    # works against the live in-memory board state (so two calls in
    # sequence — e.g. "around U1" then "across the board" — both see
    # the first call's placements). All copper layers are checked
    # because a through-hole via penetrates the full stackup; missing a
    # B.Cu collision check is the classic way GND-stitching tools
    # create silent shorts.
    # -----------------------------------------------------------------------
    def add_gnd_stitching_vias(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Drop GND stitching vias across the board, collision-checked on every copper layer.

        Strategies (combine freely):
          - ``grid``        Place candidates on a regular grid across the board
                            interior. Each candidate is accepted only if its
                            full keep-out radius is clear of every non-GND
                            segment / via / pad on every copper layer.
          - ``around_refs`` For each named footprint, try a small radius of
                            grid points around its anchor. Good for densifying
                            ground around noisy ICs (MCUs, switching
                            regulators, RF parts).
          - ``in_zones``    Restrict candidates to points actually inside the
                            filled polygons of GND copper zones, so each new
                            via lands on copper that's already a GND
                            equipotential. Highly recommended on boards where
                            the GND zone is fragmented — these vias
                            actually stitch the zones, not just float on
                            silkscreen.

        Args:
            gndNet: name of the ground net. Default: auto-detect from
                ``GND`` / ``GROUND`` / ``VSS`` in that order, else error.
            strategies: list of strategy names. Default ``["grid"]``.
                Pass ``["grid", "around_refs", "in_zones"]`` for the kitchen
                sink — collision check + intra-call dedupe means the
                strategies compose safely.
            viaSize: pad diameter mm. Default 0.6.
            viaDrill: drill diameter mm. Default 0.3.
            clearance: extra clearance beyond required mm. Default 0.2.
            spacing: grid spacing mm for ``grid`` and ``around_refs``.
                Default 5.0.
            densifyRefs: list of refs for ``around_refs``. Default [].
            densifyRadius: how many grid cells around each ref to try.
                Default 2 (5x5 candidate field per ref).
            edgeMargin: distance from board edge mm. Default 0.5.
            maxVias: maximum total placements (across all strategies).
                Default unlimited.
            dryRun: don't write, just return placements.

        Returns:
            ``{"success": True, "placed": [{"x", "y", "unit"}, ...],
                "summary": {...}}``
        """
        if not self.board:
            return {
                "success": False,
                "message": "No board is loaded",
                "errorDetails": "Load or create a board first",
            }

        try:
            return self._do_add_gnd_stitching(params)
        except Exception as e:
            import traceback

            logger.error(f"add_gnd_stitching_vias failed: {e}\n{traceback.format_exc()}")
            return {
                "success": False,
                "message": "add_gnd_stitching_vias failed",
                "errorDetails": str(e),
            }

    def _do_add_gnd_stitching(self, params: Dict[str, Any]) -> Dict[str, Any]:
        # --- Parse params ---
        gnd_net_name = params.get("gndNet")
        strategies = list(params.get("strategies") or ["grid"])
        for s in strategies:
            if s not in ("grid", "around_refs", "in_zones"):
                return {
                    "success": False,
                    "message": f"Unknown strategy '{s}'",
                    "errorDetails": "Valid strategies: grid, around_refs, in_zones",
                }

        via_size_mm = float(params.get("viaSize", 0.6))
        via_drill_mm = float(params.get("viaDrill", 0.3))
        if via_drill_mm >= via_size_mm:
            return {
                "success": False,
                "message": "Invalid via geometry",
                "errorDetails": "viaDrill must be smaller than viaSize",
            }
        clearance_mm = float(params.get("clearance", 0.2))
        spacing_mm = float(params.get("spacing", 5.0))
        if spacing_mm <= 0:
            return {
                "success": False,
                "message": "Invalid via spacing",
                "errorDetails": "spacing must be greater than zero",
            }
        densify_refs = list(params.get("densifyRefs") or [])
        densify_radius = int(params.get("densifyRadius", 2))
        edge_margin_mm = float(params.get("edgeMargin", 0.5))
        max_vias_raw = params.get("maxVias")
        max_vias = int(max_vias_raw) if max_vias_raw is not None else None
        dry_run = bool(params.get("dryRun", False))

        scale = 1_000_000  # mm -> nm
        via_size_nm = int(via_size_mm * scale)
        via_drill_nm = int(via_drill_mm * scale)
        via_radius_nm = via_size_nm // 2
        clearance_nm = int(clearance_mm * scale)
        spacing_nm = int(spacing_mm * scale)
        if spacing_nm <= 0:
            return {
                "success": False,
                "message": "Invalid via spacing",
                "errorDetails": "spacing must be at least one KiCad internal unit",
            }
        edge_margin_nm = int(edge_margin_mm * scale)

        # --- Resolve GND net ---
        netinfo = self.board.GetNetInfo()
        nets_by_name = netinfo.NetsByName()
        gnd_net = None
        if gnd_net_name:
            if nets_by_name.has_key(gnd_net_name):
                gnd_net = nets_by_name[gnd_net_name]
            else:
                return {
                    "success": False,
                    "message": f"Net '{gnd_net_name}' not found",
                    "errorDetails": "Pass a net that exists on this board",
                }
        else:
            for candidate in ("GND", "GROUND", "VSS", "/GND"):
                if nets_by_name.has_key(candidate):
                    gnd_net = nets_by_name[candidate]
                    gnd_net_name = candidate
                    break
            if gnd_net is None:
                return {
                    "success": False,
                    "message": "No GND net detected",
                    "errorDetails": (
                        "Pass gndNet explicitly. Auto-detect tries " "GND / GROUND / VSS / /GND."
                    ),
                }
        gnd_net_code = gnd_net.GetNetCode()

        # --- Board outline bbox (for the grid + edge guard) ---
        edge_bb = self.board.GetBoardEdgesBoundingBox()
        if edge_bb.GetWidth() <= 0 or edge_bb.GetHeight() <= 0:
            return {
                "success": False,
                "message": "Board outline is missing or empty",
                "errorDetails": "Define Edge.Cuts before stitching vias",
            }
        x_min = edge_bb.GetLeft() + edge_margin_nm
        y_min = edge_bb.GetTop() + edge_margin_nm
        x_max = edge_bb.GetRight() - edge_margin_nm
        y_max = edge_bb.GetBottom() - edge_margin_nm
        if x_max <= x_min or y_max <= y_min:
            return {
                "success": False,
                "message": "Edge margin too large for this board",
                "errorDetails": "Reduce edgeMargin or increase the outline",
            }

        # --- Gather obstacles (everything on a non-GND net we must dodge) ---
        # Tracks: list of (x1, y1, x2, y2, half_width)
        # Vias:   list of (cx, cy, radius)
        # Pads:   list of (cx, cy, half_extent) — bbox-circle approximation
        obstacle_tracks: List[tuple] = []
        obstacle_vias: List[tuple] = []
        obstacle_pads: List[tuple] = []

        for track in self.board.GetTracks():
            if track.GetNetCode() == gnd_net_code:
                continue
            # The rest of this module uses the string-class check rather
            # than `isinstance(track, pcbnew.PCB_VIA)` — match that for
            # consistency and because isinstance against the SWIG type
            # works unreliably under test stubs.
            is_via = False
            try:
                is_via = track.GetClass() == "PCB_VIA"
            except Exception:
                is_via = False
            if is_via:
                pos = track.GetPosition()
                width = track.GetWidth()
                drill = 0
                try:
                    drill = track.GetDrill()
                except Exception:
                    pass
                obstacle_vias.append((pos.x, pos.y, max(width, drill) // 2))
            else:
                half_width = track.GetWidth() // 2
                # A PCB_ARC recorded as the straight chord between its
                # endpoints UNDER-estimates the region it occupies: a via
                # sitting in the bulge between chord and arc passes the
                # clearance check and shorts the trace (#192). Approximate the
                # arc by a chain of short chords instead — over-approximating
                # an obstacle is safe, under-approximating is the bug.
                arc_points = _arc_polyline_points(track)
                if arc_points:
                    for (ax1, ay1), (ax2, ay2) in zip(arc_points, arc_points[1:]):
                        obstacle_tracks.append((ax1, ay1, ax2, ay2, half_width))
                else:
                    s, e = track.GetStart(), track.GetEnd()
                    obstacle_tracks.append((s.x, s.y, e.x, e.y, half_width))

        for fp in self.board.GetFootprints():
            for pad in fp.Pads():
                pad_net = pad.GetNetCode()
                if pad_net == gnd_net_code:
                    continue
                p = pad.GetPosition()
                sz = pad.GetSize()
                half_extent = max(sz.x, sz.y) // 2
                # Inflate for pad-shape variation (round vs rect)
                obstacle_pads.append((p.x, p.y, half_extent))

        logger.info(
            f"add_gnd_stitching_vias: {len(obstacle_tracks)} tracks, "
            f"{len(obstacle_vias)} vias, {len(obstacle_pads)} pads to avoid"
        )

        # --- In-zone test (cached per call) ---
        gnd_zones = [z for z in self.board.Zones() if z.GetNetCode() == gnd_net_code]

        def in_any_gnd_zone(x_nm: int, y_nm: int) -> bool:
            pt = pcbnew.VECTOR2I(x_nm, y_nm)
            for z in gnd_zones:
                try:
                    if z.HitTestFilledArea(z.GetLayer(), pt, 0):
                        return True
                except Exception:
                    # API variant: take any zone in whose bbox we sit
                    bb = z.GetBoundingBox()
                    if (
                        bb.GetLeft() <= x_nm <= bb.GetRight()
                        and bb.GetTop() <= y_nm <= bb.GetBottom()
                    ):
                        return True
            return False

        # --- Collision check closure (all-layer) ---
        placed_via_centres: List[tuple] = []  # nm coords of vias placed this call

        def can_place(x_nm: int, y_nm: int) -> bool:
            # Boundary
            if not (x_min <= x_nm <= x_max and y_min <= y_nm <= y_max):
                return False

            # Distance against placed-this-call vias (avoid clumping)
            min_self = via_size_nm + clearance_nm
            for ox, oy in placed_via_centres:
                dx = x_nm - ox
                dy = y_nm - oy
                if dx * dx + dy * dy < min_self * min_self:
                    return False

            # Tracks
            for x1, y1, x2, y2, hw in obstacle_tracks:
                min_dist = via_radius_nm + hw + clearance_nm
                if _point_to_segment_distance_nm(x_nm, y_nm, x1, y1, x2, y2) < min_dist:
                    return False

            # Vias
            for vx, vy, vr in obstacle_vias:
                min_dist = via_radius_nm + vr + clearance_nm
                dx = x_nm - vx
                dy = y_nm - vy
                if dx * dx + dy * dy < min_dist * min_dist:
                    return False

            # Pads (bbox-circle approximation, intentionally conservative)
            for px, py, ph in obstacle_pads:
                min_dist = via_radius_nm + ph + clearance_nm
                dx = x_nm - px
                dy = y_nm - py
                if dx * dx + dy * dy < min_dist * min_dist:
                    return False

            return True

        # --- Prepare a streaming candidate sequence per strategy ---
        around_footprints: List[Any] = []
        offsets = range(-densify_radius, densify_radius + 1)
        if "around_refs" in strategies:
            if not densify_refs:
                logger.warning("around_refs strategy requested but densifyRefs is empty")
            fps_by_ref = {fp.GetReference(): fp for fp in self.board.GetFootprints()}
            for ref in densify_refs:
                fp = fps_by_ref.get(ref)
                if not fp:
                    logger.warning(f"densifyRefs: {ref!r} not found")
                    continue
                around_footprints.append(fp)

        grid_enabled = "grid" in strategies or "in_zones" in strategies
        candidate_count = len(around_footprints) * len(offsets) * len(offsets)
        if grid_enabled:
            candidate_count += ((x_max - x_min) // spacing_nm + 1) * (
                (y_max - y_min) // spacing_nm + 1
            )

        def iter_candidates() -> Iterator[Tuple[int, int]]:
            for fp in around_footprints:
                cx = fp.GetPosition().x
                cy = fp.GetPosition().y
                for dx in offsets:
                    for dy in offsets:
                        yield cx + dx * spacing_nm, cy + dy * spacing_nm

            if grid_enabled:
                x = x_min
                while x <= x_max:
                    y = y_min
                    while y <= y_max:
                        yield x, y
                        y += spacing_nm
                    x += spacing_nm

        # --- Filter + place ---
        in_zones_only = "in_zones" in strategies
        skipped_by_zone = 0
        skipped_by_collision = 0
        placed_meta: List[Dict[str, Any]] = []

        for cx, cy in iter_candidates():
            if max_vias is not None and len(placed_meta) >= max_vias:
                break
            if in_zones_only and not in_any_gnd_zone(cx, cy):
                skipped_by_zone += 1
                continue
            if not can_place(cx, cy):
                skipped_by_collision += 1
                continue
            placed_via_centres.append((cx, cy))
            placed_meta.append(
                {
                    "x": round(cx / scale, 3),
                    "y": round(cy / scale, 3),
                    "unit": "mm",
                }
            )

        # --- Write to board ---
        if not dry_run:
            f_cu = self.board.GetLayerID("F.Cu")
            b_cu = self.board.GetLayerID("B.Cu")
            for cx, cy in placed_via_centres:
                via = pcbnew.PCB_VIA(self.board)
                via.SetPosition(pcbnew.VECTOR2I(cx, cy))
                via.SetWidth(via_size_nm)
                via.SetDrill(via_drill_nm)
                via.SetLayerPair(f_cu, b_cu)
                via.SetNet(gnd_net)
                self.board.Add(via)

        return {
            "success": True,
            "placed": placed_meta,
            "summary": {
                "gnd_net": gnd_net_name,
                "placed_count": len(placed_meta),
                "candidates_evaluated": candidate_count,
                "skipped_by_zone_membership": skipped_by_zone,
                "skipped_by_collision": skipped_by_collision,
                "strategies": strategies,
                "dry_run": dry_run,
                "via_size_mm": via_size_mm,
                "via_drill_mm": via_drill_mm,
                "clearance_mm": clearance_mm,
                "spacing_mm": spacing_mm,
            },
        }


# ---------------------------------------------------------------------------
# Module-level geometry helper (used by add_gnd_stitching_vias collision check)
# ---------------------------------------------------------------------------


# Chord count for arc approximation. 8 chords keeps the worst-case sagitta
# (the gap between a chord and the arc it spans) under ~2% of the radius, which
# is far below any realistic via-to-track clearance, while staying cheap in the
# obstacle-gathering loop.
_ARC_CHORD_SEGMENTS = 8


def _arc_polyline_points(track: Any) -> List[Tuple[int, int]]:
    """Sample a PCB_ARC into points for a chord-chain approximation.

    Returns ``[]`` for anything that is not an arc, so the caller falls back to
    its straight-segment handling. Never raises: an obstacle we cannot sample
    must degrade to the chord rather than abort the whole stitching run.

    The module checks item class by ``GetClass()`` string rather than
    ``isinstance`` -- see the note in ``add_gnd_stitching_vias`` -- and the test
    doubles set ``GetClass`` directly, so this matches that convention.
    """
    try:
        if track.GetClass() != "PCB_ARC":
            return []
    except Exception:
        return []

    try:
        centre = track.GetCenter()
        cx, cy = int(centre.x), int(centre.y)
        start, end = track.GetStart(), track.GetEnd()
        sx, sy = int(start.x), int(start.y)
        ex, ey = int(end.x), int(end.y)
    except Exception:
        return []

    radius = math.hypot(sx - cx, sy - cy)
    if radius <= 0:
        return []

    start_angle = math.atan2(sy - cy, sx - cx)
    end_angle = math.atan2(ey - cy, ex - cx)
    sweep = end_angle - start_angle

    # Pick the sweep direction that passes through the arc's midpoint, so a
    # major arc is not approximated by the minor one on the other side.
    try:
        mid = track.GetMid()
        mid_angle = math.atan2(int(mid.y) - cy, int(mid.x) - cx)

        def _normalise(a: float) -> float:
            while a <= -math.pi:
                a += 2 * math.pi
            while a > math.pi:
                a -= 2 * math.pi
            return a

        # If the midpoint does not lie within the shorter sweep, go the long way.
        short = _normalise(sweep)
        to_mid = _normalise(mid_angle - start_angle)
        if short == 0 or (to_mid / short) < 0 or abs(to_mid) > abs(short):
            sweep = short - math.copysign(2 * math.pi, short)
        else:
            sweep = short
    except Exception:
        # No usable midpoint: fall back to the shorter sweep.
        while sweep <= -math.pi:
            sweep += 2 * math.pi
        while sweep > math.pi:
            sweep -= 2 * math.pi

    # Sample on a slightly LARGER radius so the chords circumscribe the arc
    # instead of cutting inside it. Chords through points on the true arc are
    # secants: their midpoints sag inward by r*(1 - cos(half_step)), which
    # under-states the obstacle — the same defect as #192, just smaller.
    # Dividing by cos(half_step) puts each chord's midpoint back on the true
    # radius, so the chain never reads as further from a point than the arc is.
    half_step = abs(sweep) / (2 * _ARC_CHORD_SEGMENTS)
    sample_radius = radius / math.cos(half_step) if half_step else radius

    points: List[Tuple[int, int]] = []
    for i in range(_ARC_CHORD_SEGMENTS + 1):
        angle = start_angle + sweep * (i / _ARC_CHORD_SEGMENTS)
        points.append(
            (
                int(cx + sample_radius * math.cos(angle)),
                int(cy + sample_radius * math.sin(angle)),
            )
        )
    return points


def _point_to_segment_distance_nm(px: int, py: int, x1: int, y1: int, x2: int, y2: int) -> float:
    """Shortest distance (nm) from point (px,py) to segment (x1,y1)-(x2,y2).

    Pure integer-friendly variant of the standard projection formula;
    used in the hot loop of GND-stitching collision detection so we
    avoid building VECTOR2I objects per call.
    """
    dx = x2 - x1
    dy = y2 - y1
    if dx == 0 and dy == 0:
        ex: float = px - x1
        ey: float = py - y1
        return (ex * ex + ey * ey) ** 0.5
    denom = dx * dx + dy * dy
    t = ((px - x1) * dx + (py - y1) * dy) / denom
    if t < 0:
        t = 0
    elif t > 1:
        t = 1
    proj_x = x1 + t * dx
    proj_y = y1 + t * dy
    ex = px - proj_x
    ey = py - proj_y
    return (ex * ex + ey * ey) ** 0.5
