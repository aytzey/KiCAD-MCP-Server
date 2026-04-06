"""
Constraint-first hybrid autorouting orchestration.

This module adds a staged autorouting pipeline that treats routing as an
orchestration problem instead of a single "magic autorouter" call:

1. Preflight board analysis
2. Net intent extraction
3. Canonical constraint generation
4. KiCad custom rule (.kicad_dru) compilation
5. Critical-net routing with an IPC-first board adapter
6. Bulk routing delegation to Freerouting
7. Post-route tuning hooks
8. DRC + QoR verification

The implementation is intentionally pragmatic for phase 1:
- Critical routing is deterministic and conservative
- Freerouting remains the bulk-router backend
- External OrthoRoute is optional; the built-in orthogonal planner is the
  always-available fallback for critical nets
"""

from __future__ import annotations

import json
import logging
import math
import os
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import pcbnew
from commands.freerouting import DEFAULT_FREEROUTING_JAR, _build_freerouting_cmd

logger = logging.getLogger("kicad_interface")

PointMm = Tuple[float, float]

INTENT_ORDER = [
    "RF",
    "HS_DIFF",
    "HS_SINGLE",
    "POWER_SWITCHING",
    "ANALOG_SENSITIVE",
    "POWER_DC",
    "GROUND",
    "GENERIC",
]
INTENT_PRIORITY = {
    "RF": 100,
    "HS_DIFF": 95,
    "HS_SINGLE": 85,
    "POWER_SWITCHING": 80,
    "ANALOG_SENSITIVE": 70,
    "POWER_DC": 45,
    "GROUND": 20,
    "GENERIC": 10,
}
POWER_NET_HINTS = (
    "VIN",
    "VCC",
    "VBAT",
    "VDD",
    "3V3",
    "5V",
    "12V",
    "24V",
    "POWER",
)
GROUND_NET_HINTS = ("GND", "PGND", "AGND", "DGND", "EARTH")
POWER_SWITCHING_HINTS = ("SW", "PHASE", "LX", "BST", "GH", "GL", "HS", "LS", "GATE")
RF_HINTS = ("RF", "ANT", "LNA", "PA")
ANALOG_HINTS = ("ADC", "DAC", "VREF", "SENSE", "MIC", "AUDIO", "ANALOG")
HS_HINTS = ("USB", "PCIE", "DDR", "HDMI", "ETH", "MIPI", "LVDS", "CLK", "CLOCK")
DIFF_SUFFIXES = [
    ("_P", "_N"),
    ("+", "-"),
    ("DP", "DN"),
    ("TX+", "TX-"),
    ("RX+", "RX-"),
]

PROFILE_DEFAULTS: Dict[str, Dict[str, Any]] = {
    "generic_2layer": {
        "edge_clearance_mm": 0.25,
        "power_min_width_mm": 0.8,
        "hs_diff_gap_mm": {"min": 0.15, "opt": 0.2, "max": 0.25},
        "hs_diff_skew_mm": 0.25,
        "hs_diff_uncoupled_mm": 3.0,
        "hs_via_limit": 2,
        "rf_via_limit": 1,
    },
    "generic_4layer": {
        "edge_clearance_mm": 0.2,
        "power_min_width_mm": 0.6,
        "hs_diff_gap_mm": {"min": 0.12, "opt": 0.16, "max": 0.2},
        "hs_diff_skew_mm": 0.2,
        "hs_diff_uncoupled_mm": 2.0,
        "hs_via_limit": 2,
        "rf_via_limit": 1,
    },
    "high_speed_digital": {
        "edge_clearance_mm": 0.2,
        "power_min_width_mm": 0.6,
        "hs_diff_gap_mm": {"min": 0.1, "opt": 0.14, "max": 0.18},
        "hs_diff_skew_mm": 0.15,
        "hs_diff_uncoupled_mm": 1.5,
        "hs_via_limit": 2,
        "rf_via_limit": 1,
    },
    "rf_mixed_signal": {
        "edge_clearance_mm": 0.35,
        "power_min_width_mm": 0.7,
        "hs_diff_gap_mm": {"min": 0.12, "opt": 0.18, "max": 0.22},
        "hs_diff_skew_mm": 0.15,
        "hs_diff_uncoupled_mm": 1.0,
        "hs_via_limit": 1,
        "rf_via_limit": 1,
    },
    "power": {
        "edge_clearance_mm": 0.3,
        "power_min_width_mm": 1.0,
        "hs_diff_gap_mm": {"min": 0.15, "opt": 0.2, "max": 0.25},
        "hs_diff_skew_mm": 0.25,
        "hs_diff_uncoupled_mm": 3.0,
        "hs_via_limit": 2,
        "rf_via_limit": 1,
    },
    "dense_bga": {
        "edge_clearance_mm": 0.2,
        "power_min_width_mm": 0.6,
        "hs_diff_gap_mm": {"min": 0.09, "opt": 0.12, "max": 0.16},
        "hs_diff_skew_mm": 0.12,
        "hs_diff_uncoupled_mm": 1.0,
        "hs_via_limit": 2,
        "rf_via_limit": 1,
    },
}

INTERFACE_OVERLAYS: Dict[str, Dict[str, Any]] = {
    "USB2": {"hs_diff_gap_mm": {"min": 0.12, "opt": 0.15, "max": 0.18}, "hs_diff_skew_mm": 0.2},
    "USB3": {"hs_diff_gap_mm": {"min": 0.08, "opt": 0.1, "max": 0.14}, "hs_diff_skew_mm": 0.12},
    "PCIe": {"hs_diff_gap_mm": {"min": 0.08, "opt": 0.1, "max": 0.12}, "hs_diff_skew_mm": 0.08},
    "DDR4": {"hs_diff_skew_mm": 0.08},
    "DDR5": {"hs_diff_skew_mm": 0.05},
    "HDMI": {"hs_diff_gap_mm": {"min": 0.08, "opt": 0.1, "max": 0.12}, "hs_diff_skew_mm": 0.1},
    "Ethernet": {
        "hs_diff_gap_mm": {"min": 0.12, "opt": 0.15, "max": 0.18},
        "hs_diff_skew_mm": 0.15,
    },
}


@dataclass
class RoutingIntent:
    net_name: str
    intent: str
    priority: int
    pad_count: int
    track_length_mm: float
    via_count: int
    net_class: str = "Default"
    diff_partner: Optional[str] = None
    component_refs: List[str] = field(default_factory=list)
    layer_restrictions: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class BackendAvailability:
    board_api: str
    ipc_available: bool
    external_orthoroute: Optional[str]
    gpu_available: bool
    internal_orthogonal: bool
    freerouting_ready: bool
    freerouting_mode: str
    freerouting_jar: str
    critical_router_default: str


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _norm(name: str) -> str:
    return (name or "").strip().upper()


def _stem_path(board_path: Path, suffix: str) -> Path:
    return board_path.with_suffix(suffix)


def _safe_mkdir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _track_length_mm(track: Any) -> float:
    try:
        if hasattr(track, "GetLength"):
            return float(track.GetLength()) / 1_000_000
    except Exception:
        pass

    try:
        start = track.GetStart()
        end = track.GetEnd()
        dx = float(end.x - start.x) / 1_000_000
        dy = float(end.y - start.y) / 1_000_000
        return math.hypot(dx, dy)
    except Exception:
        return 0.0


def _track_width_mm(track: Any) -> float:
    try:
        return float(track.GetWidth()) / 1_000_000
    except Exception:
        return 0.0


def _distance_mm(a: PointMm, b: PointMm) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _diff_partner_name(net_name: str) -> Optional[str]:
    name = net_name or ""
    upper = name.upper()
    for pos, neg in DIFF_SUFFIXES:
        if pos == "+" and neg == "-":
            if not any(token in upper for token in HS_HINTS) and not upper.endswith(("D+", "D-")):
                continue
        if upper.endswith(pos):
            return name[: len(name) - len(pos)] + neg
        if upper.endswith(neg):
            return name[: len(name) - len(neg)] + pos
    return None


def _best_intent(net_name: str, net_class: str = "") -> str:
    name = _norm(net_name)
    net_class_name = _norm(net_class)

    if name in GROUND_NET_HINTS or "GND" in name:
        return "GROUND"
    if any(token in name for token in RF_HINTS) or "RF" in net_class_name:
        return "RF"
    if (name.startswith("+") and any(ch.isdigit() for ch in name)) or any(
        token in name for token in POWER_NET_HINTS
    ):
        return "POWER_DC"
    if any(token in name for token in POWER_SWITCHING_HINTS):
        return "POWER_SWITCHING"
    if any(token in name for token in ANALOG_HINTS) or "ANALOG" in net_class_name:
        return "ANALOG_SENSITIVE"
    if any(token in name for token in HS_HINTS) or "HS" in net_class_name:
        return "HS_SINGLE"
    return "GENERIC"


def _profile_merge(profiles: Sequence[str], interfaces: Sequence[str]) -> Dict[str, Any]:
    merged = dict(PROFILE_DEFAULTS["generic_2layer"])
    for profile in profiles:
        merged.update(PROFILE_DEFAULTS.get(profile, {}))
    for overlay in interfaces:
        merged.update(INTERFACE_OVERLAYS.get(overlay, {}))
    return merged


def _condition_for_nets(nets: Iterable[str]) -> Optional[str]:
    net_list = [net for net in sorted(set(nets)) if net]
    if not net_list:
        return None
    return " || ".join(f"A.NetName == '{net}'" for net in net_list)


def compile_kicad_dru(constraints: Dict[str, Any]) -> str:
    """
    Compile canonical routing constraints into a KiCad .kicad_dru custom-rule file.

    Only rules with concrete net targets are emitted to avoid writing invalid or
    overly broad rules into unrelated projects.
    """
    rules = constraints.get("compiledRules", [])
    lines = ["(version 1)", ""]
    for rule in rules:
        condition = rule.get("condition")
        if not condition:
            continue

        lines.append(f'(rule "{rule["name"]}"')
        lines.append(f'  (condition "{condition}")')

        constraint = rule["constraint"]
        if constraint == "diff_pair_gap":
            values = rule["values"]
            lines.append(
                "  (constraint diff_pair_gap "
                f'(min {values["min"]}mm) (opt {values["opt"]}mm) (max {values["max"]}mm))'
            )
        elif constraint == "diff_pair_uncoupled":
            lines.append(f'  (constraint diff_pair_uncoupled (max {rule["max"]}mm))')
        elif constraint == "skew":
            lines.append(f'  (constraint skew (max {rule["max"]}mm))')
        elif constraint == "via_count":
            lines.append(f'  (constraint via_count (max {rule["max"]}))')
        elif constraint == "track_width":
            lines.append(f'  (constraint track_width (min {rule["min"]}mm))')
        elif constraint == "edge_clearance":
            lines.append(f'  (constraint edge_clearance (min {rule["min"]}mm))')
        else:
            lines.append(f"  ; Unsupported constraint emitted as metadata: {constraint}")

        lines.append(")")
        lines.append("")

    return "\n".join(lines).strip() + "\n"


class HybridRouteApplier:
    """Apply already-planned routes using IPC first, then SWIG fallback."""

    def __init__(self, routing_commands: Any, ipc_board_api: Any = None):
        self.routing_commands = routing_commands
        self.ipc_board_api = ipc_board_api

    def route_path(
        self,
        path_points: Sequence[PointMm],
        *,
        layer: str,
        width_mm: float,
        net_name: str,
    ) -> Dict[str, Any]:
        if len(path_points) < 2:
            return {
                "success": False,
                "message": "Route path is too short",
                "errorDetails": "At least two points are required",
            }

        if self.ipc_board_api:
            for start, end in zip(path_points, path_points[1:]):
                ok = self.ipc_board_api.add_track(
                    start[0],
                    start[1],
                    end[0],
                    end[1],
                    width=width_mm,
                    layer=layer,
                    net_name=net_name,
                )
                if not ok:
                    return {
                        "success": False,
                        "message": "IPC track creation failed",
                        "errorDetails": f"Failed while adding {start}->{end} on {layer}",
                    }
            try:
                self.ipc_board_api.save()
            except Exception:
                logger.debug("IPC save after route_path failed", exc_info=True)
            return {
                "success": True,
                "message": f"Added {len(path_points) - 1} segment(s) via IPC",
                "backend": "ipc",
            }

        return self.routing_commands.route_trace(
            {
                "start": {"x": path_points[0][0], "y": path_points[0][1], "unit": "mm"},
                "end": {"x": path_points[-1][0], "y": path_points[-1][1], "unit": "mm"},
                "layer": layer,
                "width": width_mm,
                "net": net_name,
                "waypoints": [
                    {"x": point[0], "y": point[1], "unit": "mm"} for point in path_points[1:-1]
                ],
            }
        )


class AutorouteCFHACommands:
    """Constraint-first hybrid autorouting commands."""

    def __init__(
        self,
        board: Optional[pcbnew.BOARD] = None,
        routing_commands: Any = None,
        freerouting_commands: Any = None,
        design_rule_commands: Any = None,
        ipc_board_api: Any = None,
    ):
        self.board = board
        self.routing_commands = routing_commands
        self.freerouting_commands = freerouting_commands
        self.design_rule_commands = design_rule_commands
        self.ipc_board_api = ipc_board_api

    def set_board(self, board: Optional[pcbnew.BOARD]) -> None:
        self.board = board
        if self.routing_commands is not None:
            self.routing_commands.board = board
        if self.freerouting_commands is not None:
            self.freerouting_commands.board = board
        if self.design_rule_commands is not None:
            self.design_rule_commands.board = board

    def set_ipc_board_api(self, ipc_board_api: Any) -> None:
        self.ipc_board_api = ipc_board_api

    def _ensure_board(self, params: Dict[str, Any]) -> Tuple[Optional[pcbnew.BOARD], Optional[Path], Optional[Dict[str, Any]]]:
        if self.board:
            board_path = self.board.GetFileName()
            if board_path:
                if not params.get("boardPath") or Path(params["boardPath"]).resolve() == Path(
                    board_path
                ).resolve():
                    return self.board, Path(board_path), None

        board_path_param = params.get("boardPath")
        if not board_path_param:
            return None, None, {
                "success": False,
                "message": "No board is loaded",
                "errorDetails": "Open a board first or provide boardPath",
            }

        board_path = Path(board_path_param).expanduser().resolve()
        if not board_path.is_file():
            return None, None, {
                "success": False,
                "message": "Board file not found",
                "errorDetails": str(board_path),
            }

        try:
            board = pcbnew.LoadBoard(str(board_path))
        except Exception as exc:
            return None, board_path, {
                "success": False,
                "message": "Failed to load board",
                "errorDetails": str(exc),
            }

        self.set_board(board)
        return board, board_path, None

    def _detect_backends(self, params: Dict[str, Any]) -> BackendAvailability:
        ipc_available = self.ipc_board_api is not None
        external_orthoroute = params.get("orthorouteExecutable") or os.environ.get("ORTHOROUTE_BIN")
        if external_orthoroute and not shutil.which(external_orthoroute) and not os.path.isfile(
            external_orthoroute
        ):
            external_orthoroute = None

        gpu_available = False
        try:
            gpu_available = shutil.which("nvidia-smi") is not None
            if gpu_available:
                probe = subprocess.run(
                    ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                gpu_available = probe.returncode == 0 and bool((probe.stdout or "").strip())
        except Exception:
            gpu_available = False

        freerouting_check = {"ready": False, "execution_mode": "none"}
        if self.freerouting_commands is not None:
            try:
                freerouting_check = self.freerouting_commands.check_freerouting(params)
            except Exception:
                logger.debug("check_freerouting failed during backend detection", exc_info=True)

        critical_default = "orthoroute-external" if external_orthoroute else "orthoroute-internal"
        return BackendAvailability(
            board_api="ipc" if ipc_available else "swig",
            ipc_available=ipc_available,
            external_orthoroute=external_orthoroute,
            gpu_available=gpu_available,
            internal_orthogonal=True,
            freerouting_ready=bool(freerouting_check.get("ready")),
            freerouting_mode=str(freerouting_check.get("execution_mode", "none")),
            freerouting_jar=params.get("freeroutingJar", DEFAULT_FREEROUTING_JAR),
            critical_router_default=critical_default,
        )

    def _board_layers(self, board: pcbnew.BOARD) -> List[str]:
        layers: List[str] = []
        for layer_id in range(pcbnew.PCB_LAYER_ID_COUNT):
            try:
                if board.IsLayerEnabled(layer_id):
                    name = board.GetLayerName(layer_id)
                    if name.endswith(".Cu"):
                        layers.append(name)
            except Exception:
                continue
        return layers

    def _collect_zones(self, board: pcbnew.BOARD) -> List[Dict[str, Any]]:
        zones: List[Dict[str, Any]] = []
        try:
            for zone in list(board.Zones()):
                zones.append(
                    {
                        "net": zone.GetNetname(),
                        "layer": board.GetLayerName(zone.GetLayer()),
                        "priority": zone.GetAssignedPriority(),
                    }
                )
        except Exception:
            logger.debug("Zone collection failed", exc_info=True)
        return zones

    def _collect_inventory(self, board: pcbnew.BOARD) -> Dict[str, Any]:
        netinfo = board.GetNetInfo()
        nets: Dict[str, Dict[str, Any]] = {}
        for net_code in range(netinfo.GetNetCount()):
            net = netinfo.GetNetItem(net_code)
            if not net:
                continue
            name = net.GetNetname()
            if not name:
                continue
            nets[name] = {
                "name": name,
                "code": net.GetNetCode(),
                "class": getattr(net, "GetNetClassName", lambda: "Default")() or "Default",
                "pads": [],
                "pad_refs": [],
                "track_length_mm": 0.0,
                "track_count": 0,
                "via_count": 0,
                "min_track_width_mm": None,
                "zones": [],
            }

        for footprint in board.GetFootprints():
            ref = footprint.GetReference()
            for pad in footprint.Pads():
                net_name = pad.GetNetname()
                if not net_name or net_name not in nets:
                    continue
                pos = pad.GetPosition()
                nets[net_name]["pads"].append(
                    {
                        "ref": ref,
                        "pad": pad.GetNumber(),
                        "x": pos.x / 1_000_000,
                        "y": pos.y / 1_000_000,
                    }
                )
                nets[net_name]["pad_refs"].append(ref)

        for item in board.GetTracks():
            try:
                net_name = item.GetNetname()
            except Exception:
                net_name = ""
            if not net_name or net_name not in nets:
                continue

            is_via = False
            try:
                is_via = item.Type() == pcbnew.PCB_VIA_T
            except Exception:
                is_via = item.GetClass() == "PCB_VIA"

            if is_via:
                nets[net_name]["via_count"] += 1
            else:
                nets[net_name]["track_count"] += 1
                nets[net_name]["track_length_mm"] += _track_length_mm(item)
                width_mm = _track_width_mm(item)
                current_min = nets[net_name]["min_track_width_mm"]
                if width_mm > 0 and (current_min is None or width_mm < current_min):
                    nets[net_name]["min_track_width_mm"] = width_mm

        for zone in self._collect_zones(board):
            net_name = zone["net"]
            if net_name in nets:
                nets[net_name]["zones"].append(zone)

        return nets

    def analyze_board_routing_context(self, params: Dict[str, Any]) -> Dict[str, Any]:
        board, board_path, error = self._ensure_board(params)
        if error:
            return error

        assert board is not None
        assert board_path is not None

        bbox = board.GetBoardEdgesBoundingBox()
        width_mm = bbox.GetWidth() / 1_000_000
        height_mm = bbox.GetHeight() / 1_000_000
        copper_layers = self._board_layers(board)
        inventory = self._collect_inventory(board)
        zones = self._collect_zones(board)
        backends = self._detect_backends(params)

        dense_refs = [fp.GetReference() for fp in board.GetFootprints() if fp.GetReference().startswith("J")]
        split_risk_layers = sorted(
            {
                zone["layer"]
                for zone in zones
                if sum(1 for other in zones if other["layer"] == zone["layer"]) > 1
            }
        )
        has_ground_plane = any(_best_intent(zone["net"]) == "GROUND" for zone in zones)

        intent_counts: Dict[str, int] = {}
        for net_name in inventory:
            intent_counts[_best_intent(net_name)] = intent_counts.get(_best_intent(net_name), 0) + 1

        inferred_profiles = []
        inferred_profiles.append("generic_4layer" if len(copper_layers) >= 4 else "generic_2layer")
        if intent_counts.get("POWER_SWITCHING", 0) >= 2 or (
            len(copper_layers) >= 4 and intent_counts.get("POWER_DC", 0) >= 3
        ):
            inferred_profiles.append("power")
        if any(
            _best_intent(net_name) == "HS_SINGLE" or _diff_partner_name(net_name) in inventory
            for net_name in inventory
        ):
            inferred_profiles.append("high_speed_digital")
        if any(_best_intent(net_name) == "RF" for net_name in inventory):
            inferred_profiles.append("rf_mixed_signal")

        return {
            "success": True,
            "boardPath": str(board_path),
            "summary": {
                "sizeMm": {"width": round(width_mm, 3), "height": round(height_mm, 3)},
                "copperLayers": copper_layers,
                "netCount": len(inventory),
                "footprintCount": sum(1 for _ in board.GetFootprints()),
                "trackCount": sum(1 for _ in board.GetTracks()),
                "zoneCount": len(zones),
                "hasGroundPlane": has_ground_plane,
                "splitRiskLayers": split_risk_layers,
                "denseConnectorRefs": dense_refs,
            },
            "profiles": list(dict.fromkeys(params.get("profiles") or inferred_profiles)),
            "interfaces": params.get("interfaces", []),
            "backends": asdict(backends),
            "netInventory": inventory,
            "intentCounts": intent_counts,
        }

    def extract_routing_intents(self, params: Dict[str, Any]) -> Dict[str, Any]:
        analysis = params.get("analysis")
        if not analysis:
            analysis = self.analyze_board_routing_context(params)
        if not analysis.get("success"):
            return analysis

        inventory = analysis["netInventory"]
        overrides = params.get("intentOverrides", {})
        intents: List[RoutingIntent] = []
        for net_name, info in inventory.items():
            net_class = info.get("class") or "Default"
            intent_name = overrides.get(net_name) or _best_intent(net_name, net_class)
            diff_partner = _diff_partner_name(net_name)
            if (
                net_name not in overrides
                and diff_partner in inventory
                and intent_name not in {"GROUND", "POWER_DC", "POWER_SWITCHING", "RF", "ANALOG_SENSITIVE"}
            ):
                intent_name = "HS_DIFF"
            else:
                diff_partner = None if intent_name != "HS_DIFF" else diff_partner
            priority = INTENT_PRIORITY.get(intent_name, 0)
            refs = sorted(set(info.get("pad_refs", [])))
            intents.append(
                RoutingIntent(
                    net_name=net_name,
                    intent=intent_name,
                    priority=priority,
                    pad_count=len(info.get("pads", [])),
                    track_length_mm=round(float(info.get("track_length_mm", 0.0)), 4),
                    via_count=int(info.get("via_count", 0)),
                    net_class=net_class,
                    diff_partner=diff_partner if diff_partner in inventory else None,
                    component_refs=refs,
                    metadata={
                        "zoneCount": len(info.get("zones", [])),
                        "trackCount": int(info.get("track_count", 0)),
                    },
                )
            )

        intents.sort(key=lambda item: (-item.priority, item.net_name))
        by_intent: Dict[str, List[str]] = {}
        for intent in intents:
            by_intent.setdefault(intent.intent, []).append(intent.net_name)

        return {
            "success": True,
            "boardPath": analysis["boardPath"],
            "profiles": analysis.get("profiles", []),
            "interfaces": analysis.get("interfaces", []),
            "backends": analysis.get("backends", {}),
            "intents": [asdict(intent) for intent in intents],
            "byIntent": by_intent,
            "analysisSummary": analysis.get("summary", {}),
            "netInventory": inventory,
        }

    def generate_routing_constraints(self, params: Dict[str, Any]) -> Dict[str, Any]:
        intents_result = params.get("intentResult")
        if not intents_result:
            intents_result = self.extract_routing_intents(params)
        if not intents_result.get("success"):
            return intents_result

        board_path = Path(intents_result["boardPath"])
        profiles = list(dict.fromkeys(intents_result.get("profiles") or ["generic_2layer"]))
        interfaces = list(dict.fromkeys(intents_result.get("interfaces") or []))
        merged_defaults = _profile_merge(profiles, interfaces)
        by_intent = intents_result["byIntent"]
        intents = intents_result["intents"]
        inventory = intents_result.get("netInventory", {})
        seed = int(params.get("seed", 42))
        exclude_from_freerouting = list(
            dict.fromkeys(
                params.get("excludeFromFreeRouting")
                or by_intent.get("GROUND", [])
                + by_intent.get("POWER_DC", [])
                + by_intent.get("POWER_SWITCHING", [])
            )
        )

        power_target_width_mm = float(merged_defaults["power_min_width_mm"])
        observed_power_widths = [
            float(inventory[net]["min_track_width_mm"])
            for net in by_intent.get("POWER_DC", [])
            if net in inventory and inventory[net].get("min_track_width_mm") is not None
        ]
        power_rule_min_width_mm = power_target_width_mm
        if observed_power_widths:
            power_rule_min_width_mm = min(power_target_width_mm, min(observed_power_widths))

        compiled_rules: List[Dict[str, Any]] = []
        hs_diff_condition = _condition_for_nets(by_intent.get("HS_DIFF", []))
        if hs_diff_condition:
            compiled_rules.extend(
                [
                    {
                        "name": "cfha_hs_diff_gap",
                        "condition": hs_diff_condition,
                        "constraint": "diff_pair_gap",
                        "values": merged_defaults["hs_diff_gap_mm"],
                    },
                    {
                        "name": "cfha_hs_diff_uncoupled",
                        "condition": hs_diff_condition,
                        "constraint": "diff_pair_uncoupled",
                        "max": merged_defaults["hs_diff_uncoupled_mm"],
                    },
                    {
                        "name": "cfha_hs_diff_skew",
                        "condition": hs_diff_condition,
                        "constraint": "skew",
                        "max": merged_defaults["hs_diff_skew_mm"],
                    },
                ]
            )

        via_limited_nets = by_intent.get("HS_DIFF", []) + by_intent.get("HS_SINGLE", [])
        via_condition = _condition_for_nets(via_limited_nets)
        if via_condition:
            compiled_rules.append(
                {
                    "name": "cfha_hs_via_limit",
                    "condition": via_condition,
                    "constraint": "via_count",
                    "max": merged_defaults["hs_via_limit"],
                }
            )

        power_condition = _condition_for_nets(by_intent.get("POWER_DC", []))
        if power_condition:
            compiled_rules.append(
                {
                    "name": "cfha_power_min_width",
                    "condition": power_condition,
                    "constraint": "track_width",
                    "min": round(power_rule_min_width_mm, 4),
                }
            )

        edge_condition = _condition_for_nets(
            by_intent.get("RF", []) + by_intent.get("HS_DIFF", []) + by_intent.get("HS_SINGLE", [])
        )
        if edge_condition:
            compiled_rules.append(
                {
                    "name": "cfha_board_edge_margin",
                    "condition": edge_condition,
                    "constraint": "edge_clearance",
                    "min": merged_defaults["edge_clearance_mm"],
                }
            )

        constraints = {
            "schemaVersion": 1,
            "generatedAt": _utc_now(),
            "seed": seed,
            "boardPath": str(board_path),
            "profiles": profiles,
            "interfaces": interfaces,
            "stackup": {
                "copperLayers": intents_result["analysisSummary"].get("copperLayers", []),
                "layerCount": len(intents_result["analysisSummary"].get("copperLayers", [])),
            },
            "boardSummary": intents_result.get("analysisSummary", {}),
            "intents": intents,
            "intentGroups": by_intent,
            "defaults": merged_defaults,
            "derived": {
                "powerTargetWidthMm": round(power_target_width_mm, 4),
                "powerRuleMinWidthMm": round(power_rule_min_width_mm, 4),
                "observedPowerMinWidthMm": round(min(observed_power_widths), 4)
                if observed_power_widths
                else None,
            },
            "compiledRules": compiled_rules,
            "excludeFromFreeRouting": exclude_from_freerouting,
            "criticalClasses": params.get(
                "criticalClasses",
                ["RF", "HS_DIFF", "HS_SINGLE", "POWER_SWITCHING", "ANALOG_SENSITIVE"],
            ),
            "qorWeights": params.get(
                "qorWeights",
                {
                    "length": 1.0,
                    "vias": 2.0,
                    "skew": 5.0,
                    "uncoupled": 5.0,
                    "returnPathRisk": 8.0,
                },
            ),
        }

        output_path = Path(
            params.get("outputPath", board_path.with_suffix(".routing_constraints.json"))
        )
        _safe_mkdir(output_path)
        output_path.write_text(json.dumps(constraints, indent=2), encoding="utf-8")

        return {
            "success": True,
            "message": "Generated canonical routing constraints",
            "boardPath": str(board_path),
            "constraintsPath": str(output_path),
            "constraints": constraints,
        }

    def generate_kicad_dru(self, params: Dict[str, Any]) -> Dict[str, Any]:
        constraints_result = params.get("constraintsResult")
        if not constraints_result:
            constraints_result = self.generate_routing_constraints(params)
        if not constraints_result.get("success"):
            return constraints_result

        constraints = constraints_result["constraints"]
        board_path = Path(constraints["boardPath"])
        rules_path = Path(params.get("outputPath", board_path.with_suffix(".kicad_dru")))
        rule_text = compile_kicad_dru(constraints)
        _safe_mkdir(rules_path)
        rules_path.write_text(rule_text, encoding="utf-8")

        return {
            "success": True,
            "message": "Generated KiCad custom rule file",
            "boardPath": str(board_path),
            "rulesPath": str(rules_path),
            "ruleCount": len(constraints.get("compiledRules", [])),
        }

    def route_critical_nets(self, params: Dict[str, Any]) -> Dict[str, Any]:
        board, board_path, error = self._ensure_board(params)
        if error:
            return error
        assert board is not None
        assert board_path is not None

        constraints_result = params.get("constraintsResult")
        if not constraints_result:
            constraints_result = self.generate_routing_constraints(params)
        if not constraints_result.get("success"):
            return constraints_result

        constraints = constraints_result["constraints"]
        critical_classes = set(constraints["criticalClasses"])
        applier = HybridRouteApplier(self.routing_commands, self.ipc_board_api)
        inventory = self._collect_inventory(board)
        footprints = {fp.GetReference(): fp for fp in board.GetFootprints()}
        routed: List[Dict[str, Any]] = []
        skipped: List[Dict[str, Any]] = []

        for intent in constraints["intents"]:
            if intent["intent"] not in critical_classes:
                continue
            if intent["track_length_mm"] > 0:
                skipped.append(
                    {
                        "net": intent["net_name"],
                        "reason": "already_routed",
                        "intent": intent["intent"],
                    }
                )
                continue

            net_info = inventory.get(intent["net_name"], {})
            pads = net_info.get("pads", [])
            if len(pads) != 2:
                skipped.append(
                    {
                        "net": intent["net_name"],
                        "reason": "unsupported_pad_topology",
                        "padCount": len(pads),
                        "intent": intent["intent"],
                    }
                )
                continue

            width_mm = float(params.get("criticalWidthMm") or 0.25)
            if intent["intent"] in {"POWER_DC", "POWER_SWITCHING"}:
                power_target = float(
                    constraints.get("derived", {}).get(
                        "powerTargetWidthMm", constraints["defaults"]["power_min_width_mm"]
                    )
                )
                width_mm = max(width_mm, power_target)

            same_layer_ipc = False
            result: Dict[str, Any]
            if self.ipc_board_api and pads[0]["ref"] in footprints and pads[1]["ref"] in footprints:
                start_layer = board.GetLayerName(footprints[pads[0]["ref"]].GetLayer())
                end_layer = board.GetLayerName(footprints[pads[1]["ref"]].GetLayer())
                if start_layer == end_layer and start_layer in {"F.Cu", "B.Cu"}:
                    start_point = (float(pads[0]["x"]), float(pads[0]["y"]))
                    end_point = (float(pads[1]["x"]), float(pads[1]["y"]))
                    planned = self.routing_commands._plan_trace_points(
                        start_point,
                        end_point,
                        start_layer,
                        width_mm,
                        net=intent["net_name"],
                        ignored_refs=[pads[0]["ref"], pads[1]["ref"]],
                    )
                    result = applier.route_path(
                        planned or [start_point, end_point],
                        layer=start_layer,
                        width_mm=width_mm,
                        net_name=intent["net_name"],
                    )
                    same_layer_ipc = result.get("success", False)
                else:
                    result = {"success": False, "message": "Via-required path kept on SWIG fallback"}
            else:
                result = {"success": False, "message": "IPC unavailable"}

            if not same_layer_ipc:
                result = self.routing_commands.route_pad_to_pad(
                    {
                        "fromRef": pads[0]["ref"],
                        "fromPad": pads[0]["pad"],
                        "toRef": pads[1]["ref"],
                        "toPad": pads[1]["pad"],
                        "layer": params.get("criticalLayer", "F.Cu"),
                        "width": width_mm,
                        "net": intent["net_name"],
                    }
                )
            if result.get("success"):
                routed.append(
                    {
                        "net": intent["net_name"],
                        "intent": intent["intent"],
                        "widthMm": width_mm,
                        "backend": "ipc" if same_layer_ipc else "swig",
                    }
                )
            else:
                skipped.append(
                    {
                        "net": intent["net_name"],
                        "intent": intent["intent"],
                        "reason": "route_failed",
                        "error": result.get("errorDetails", result.get("message")),
                    }
                )

        try:
            board.Save(str(board_path))
        except Exception:
            logger.debug("Board save after route_critical_nets failed", exc_info=True)

        return {
            "success": True,
            "message": f"Critical routing stage completed ({len(routed)} routed, {len(skipped)} skipped)",
            "boardPath": str(board_path),
            "routed": routed,
            "skipped": skipped,
            "backendPreference": "ipc" if self.ipc_board_api else "swig",
        }

    def _probe_freerouting_capabilities(
        self, jar_path: str, execution_mode: str
    ) -> Dict[str, bool]:
        capabilities = {"inc": False, "seed": False}
        if not jar_path or not os.path.isfile(jar_path):
            return capabilities

        try:
            if execution_mode == "docker":
                cmd = _build_freerouting_cmd(jar_path, "/tmp/in.dsn", "/tmp/out.ses", 1, True) + [
                    "-help"
                ]
            else:
                java_exe = shutil.which("java") or "/usr/bin/java"
                cmd = [java_exe, "-jar", jar_path, "-help"]

            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=20,
            )
            output = (proc.stdout or "") + "\n" + (proc.stderr or "")
            capabilities["inc"] = "-inc" in output
            capabilities["seed"] = "--seed" in output or "-seed" in output
        except Exception:
            logger.debug("Freerouting capability probe failed", exc_info=True)
        return capabilities

    def run_freerouting(self, params: Dict[str, Any]) -> Dict[str, Any]:
        board, board_path, error = self._ensure_board(params)
        if error:
            return error
        assert board is not None
        assert board_path is not None

        if self.freerouting_commands is None:
            return {
                "success": False,
                "message": "Freerouting command handler unavailable",
            }

        check = self.freerouting_commands.check_freerouting(params)
        if not check.get("ready"):
            return {
                "success": False,
                "message": "Freerouting is not ready",
                "errorDetails": check,
                "skipped": True,
            }

        constraints_result = params.get("constraintsResult")
        if not constraints_result:
            constraints_result = self.generate_routing_constraints(params)
        constraints = constraints_result.get("constraints", {})
        exclude_nets = params.get("excludeNets") or constraints.get("excludeFromFreeRouting", [])

        export_result = self.freerouting_commands.export_dsn(
            {
                "boardPath": str(board_path),
                "outputPath": params.get("dsnPath") or str(board_path.with_suffix(".dsn")),
            }
        )
        if not export_result.get("success"):
            return export_result

        dsn_path = export_result["path"]
        ses_path = params.get("sesPath") or str(board_path.with_suffix(".ses"))
        jar_path = params.get("freeroutingJar", DEFAULT_FREEROUTING_JAR)
        timeout = int(params.get("timeout", params.get("timeBudgetSec", 300)))
        max_passes = int(params.get("maxPasses", 20))
        execution_mode = str(check.get("execution_mode", "none"))
        use_docker = execution_mode == "docker"
        cmd = _build_freerouting_cmd(jar_path, dsn_path, ses_path, max_passes, use_docker)
        capabilities = self._probe_freerouting_capabilities(jar_path, execution_mode)

        if exclude_nets and capabilities["inc"]:
            for net_name in exclude_nets:
                cmd.extend(["-inc", net_name])

        seed = params.get("seed")
        if seed is not None and capabilities["seed"]:
            cmd.extend(["-seed", str(int(seed))])

        extra_args = params.get("extraFreeroutingArgs", [])
        if extra_args:
            cmd.extend([str(arg) for arg in extra_args])

        start = time.monotonic()
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=str(board_path.parent),
            )
        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "message": f"Freerouting timed out after {timeout}s",
                "dsnPath": dsn_path,
                "sesPath": ses_path,
                "excludedNets": exclude_nets,
                "capabilities": capabilities,
            }
        elapsed = round(time.monotonic() - start, 3)
        if proc.returncode != 0:
            return {
                "success": False,
                "message": f"Freerouting exited with code {proc.returncode}",
                "errorDetails": proc.stderr or proc.stdout,
                "dsnPath": dsn_path,
                "sesPath": ses_path,
                "elapsedSec": elapsed,
                "excludedNets": exclude_nets,
                "capabilities": capabilities,
            }

        import_result = self.freerouting_commands.import_ses(
            {
                "sesPath": ses_path,
                "boardPath": str(board_path),
            }
        )
        import_result.update(
            {
                "dsnPath": dsn_path,
                "sesPath": ses_path,
                "elapsedSec": elapsed,
                "excludedNets": exclude_nets,
                "capabilities": capabilities,
                "mode": execution_mode,
            }
        )
        return import_result

    def post_tune_routes(self, params: Dict[str, Any]) -> Dict[str, Any]:
        board, board_path, error = self._ensure_board(params)
        if error:
            return error
        assert board is not None
        assert board_path is not None

        actions: List[str] = []
        try:
            if hasattr(board, "BuildConnectivity"):
                board.BuildConnectivity()
                actions.append("build_connectivity")
        except Exception:
            logger.debug("BuildConnectivity failed during post_tune_routes", exc_info=True)

        if params.get("refillZones", False):
            refill_result = self.routing_commands.refill_zones({})
            if refill_result.get("success"):
                actions.append("refill_zones")

        try:
            board.Save(str(board_path))
        except Exception:
            logger.debug("Board save after post_tune_routes failed", exc_info=True)

        return {
            "success": True,
            "message": "Post-route tuning hooks completed",
            "actions": actions,
            "boardPath": str(board_path),
        }

    def verify_routing_qor(self, params: Dict[str, Any]) -> Dict[str, Any]:
        board, board_path, error = self._ensure_board(params)
        if error:
            return error
        assert board is not None
        assert board_path is not None

        inventory = self._collect_inventory(board)
        intents_result = params.get("intentResult")
        if not intents_result:
            intents_result = self.extract_routing_intents(params)
        if not intents_result.get("success"):
            return intents_result

        routeable_nets = 0
        completed_nets = 0
        wirelength_mm = 0.0
        via_count = 0
        power_misuse_flags: List[Dict[str, Any]] = []
        return_path_risk_flags: List[Dict[str, Any]] = []
        copper_layers = self._board_layers(board)
        prefer_power_zones = len(copper_layers) >= 4

        for intent in intents_result["intents"]:
            net_name = intent["net_name"]
            info = inventory.get(net_name, {})
            wirelength_mm += float(info.get("track_length_mm", 0.0))
            via_count += int(info.get("via_count", 0))

            pad_count = len(info.get("pads", []))
            has_copper = bool(info.get("track_length_mm", 0.0) > 0 or info.get("zones"))
            if pad_count >= 2:
                routeable_nets += 1
                if has_copper:
                    completed_nets += 1

            if (
                prefer_power_zones
                and intent["intent"] in {"POWER_DC", "POWER_SWITCHING"}
                and not info.get("zones")
            ):
                power_misuse_flags.append(
                    {
                        "net": net_name,
                        "reason": "power_net_without_zone",
                        "trackLengthMm": round(float(info.get("track_length_mm", 0.0)), 3),
                    }
                )

            if intent["intent"] in {"HS_DIFF", "HS_SINGLE", "RF"}:
                if not any(_best_intent(zone["net"]) == "GROUND" for zone in self._collect_zones(board)):
                    return_path_risk_flags.append(
                        {
                            "net": net_name,
                            "reason": "no_ground_reference_zone_detected",
                        }
                    )

        diff_lengths: Dict[str, float] = {}
        uncoupled_estimates: List[float] = []
        seen_pairs: set[Tuple[str, str]] = set()
        for intent in intents_result["intents"]:
            if intent["intent"] != "HS_DIFF" or not intent.get("diff_partner"):
                continue
            a = intent["net_name"]
            b = intent["diff_partner"]
            pair = tuple(sorted((a, b)))
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            len_a = float(inventory.get(a, {}).get("track_length_mm", 0.0))
            len_b = float(inventory.get(b, {}).get("track_length_mm", 0.0))
            diff_lengths[f"{pair[0]}|{pair[1]}"] = round(abs(len_a - len_b), 4)
            uncoupled_estimates.append(abs(len_a - len_b))

        drc_result = self.design_rule_commands.run_drc(
            {"reportPath": params.get("reportPath") or str(board_path.with_suffix(".drc.rpt"))}
        )
        if not drc_result.get("success"):
            return drc_result

        severity = drc_result.get("summary", {}).get("by_severity", {})
        completion_rate = round(completed_nets / routeable_nets, 4) if routeable_nets else 1.0
        report = {
            "success": severity.get("error", 0) == 0,
            "boardPath": str(board_path),
            "completionRate": completion_rate,
            "drc": {
                "errors": int(severity.get("error", 0)),
                "warnings": int(severity.get("warning", 0)),
                "violationsFile": drc_result.get("violationsFile"),
                "reportPath": drc_result.get("reportPath"),
            },
            "metrics": {
                "wirelengthMm": round(wirelength_mm, 3),
                "viaCount": via_count,
                "routeableNetCount": routeable_nets,
                "completedNetCount": completed_nets,
                "maxDiffSkewMm": round(max(diff_lengths.values(), default=0.0), 4),
                "maxUncoupledMm": round(max(uncoupled_estimates, default=0.0), 4),
            },
            "flags": {
                "powerNetMisuse": power_misuse_flags,
                "returnPathRisk": return_path_risk_flags,
            },
            "pairSkewMm": diff_lengths,
        }

        output_path = Path(params.get("qorReportPath", board_path.with_suffix(".autoroute_cfha.json")))
        _safe_mkdir(output_path)
        output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        report["reportPath"] = str(output_path)
        return report

    def autoroute_cfha(self, params: Dict[str, Any]) -> Dict[str, Any]:
        board, board_path, error = self._ensure_board(params)
        if error:
            return error
        assert board is not None
        assert board_path is not None

        stage_times: Dict[str, float] = {}

        def timed(name: str, func, payload: Dict[str, Any]) -> Dict[str, Any]:
            start = time.monotonic()
            result = func(payload)
            stage_times[name] = round(time.monotonic() - start, 3)
            return result

        analysis = timed("analyze", self.analyze_board_routing_context, params)
        if not analysis.get("success"):
            return analysis

        intents = timed(
            "extract_intents",
            self.extract_routing_intents,
            {**params, "analysis": analysis},
        )
        if not intents.get("success"):
            return intents

        constraints = timed(
            "generate_constraints",
            self.generate_routing_constraints,
            {**params, "intentResult": intents},
        )
        if not constraints.get("success"):
            return constraints

        dru = timed(
            "generate_dru",
            self.generate_kicad_dru,
            {**params, "constraintsResult": constraints},
        )
        if not dru.get("success"):
            return dru

        critical = timed(
            "route_critical",
            self.route_critical_nets,
            {**params, "constraintsResult": constraints},
        )
        if not critical.get("success"):
            return critical

        strategy = params.get("strategy", "hybrid")
        bulk = {
            "success": True,
            "message": "Bulk router skipped",
            "skipped": True,
        }
        if strategy not in {"critical_only", "analysis_only"}:
            verify_before_bulk = self.verify_routing_qor(
                {**params, "intentResult": intents, "constraintsResult": constraints}
            )
            if verify_before_bulk.get("completionRate", 0) < 1.0 and not params.get("skipBulkRoute"):
                bulk = timed(
                    "bulk_route",
                    self.run_freerouting,
                    {**params, "constraintsResult": constraints},
                )
            else:
                stage_times["bulk_route"] = 0.0
                bulk["message"] = "Bulk router not required for this board state"
                bulk["completionRateBeforeBulk"] = verify_before_bulk.get("completionRate")

        post = timed("post_tune", self.post_tune_routes, params)
        verify = timed(
            "verify",
            self.verify_routing_qor,
            {**params, "intentResult": intents, "constraintsResult": constraints},
        )
        if not verify.get("success", False) and verify.get("drc", {}).get("errors", 0) > 0:
            success = False
        else:
            success = bool(verify.get("drc", {}).get("errors", 0) == 0)

        return {
            "success": success,
            "strategy": strategy,
            "boardPath": str(board_path),
            "completionRate": verify.get("completionRate"),
            "drc": verify.get("drc"),
            "metrics": {
                **verify.get("metrics", {}),
                "runtimeSec": round(sum(stage_times.values()), 3),
            },
            "artifacts": {
                "constraintsPath": constraints.get("constraintsPath"),
                "rulesPath": dru.get("rulesPath"),
                "dsnPath": bulk.get("dsnPath"),
                "sesPath": bulk.get("sesPath"),
                "reportPath": verify.get("reportPath"),
            },
            "stages": {
                "analysis": analysis.get("summary"),
                "critical": critical,
                "bulk": bulk,
                "postTune": post,
                "timingsSec": stage_times,
            },
            "backends": analysis.get("backends"),
            "flags": verify.get("flags", {}),
        }

    def autoroute_default(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Backwards-compatible entrypoint for the existing `autoroute` tool."""
        return self.autoroute_cfha(params)
