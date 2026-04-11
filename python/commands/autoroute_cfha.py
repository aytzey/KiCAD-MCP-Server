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
import re
import shutil
import subprocess
import sys
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
INTERFACE_BUS_PREFIX_HINTS: Dict[str, Tuple[str, ...]] = {
    "DDR4": ("DQ", "DQS", "DM", "ADDR", "A", "BA", "BG", "CS", "CKE", "ODT", "WE", "RAS", "CAS"),
    "DDR5": ("DQ", "DQS", "DM", "CA", "A", "BA", "BG", "CS", "CKE", "ODT", "ACT", "ALERT"),
}

PROFILE_DEFAULTS: Dict[str, Dict[str, Any]] = {
    "generic_2layer": {
        "edge_clearance_mm": 0.25,
        "power_min_width_mm": 0.8,
        "hs_diff_gap_mm": {"min": 0.15, "opt": 0.2, "max": 0.25},
        "hs_diff_skew_mm": 0.25,
        "hs_diff_uncoupled_mm": 3.0,
        "hs_via_limit": 2,
        "rf_via_limit": 1,
        "crosstalk_guard_mm": 0.5,
        "analog_guard_mm": 1.0,
        "rf_guard_mm": 1.5,
    },
    "generic_4layer": {
        "edge_clearance_mm": 0.2,
        "power_min_width_mm": 0.6,
        "hs_diff_gap_mm": {"min": 0.12, "opt": 0.16, "max": 0.2},
        "hs_diff_skew_mm": 0.2,
        "hs_diff_uncoupled_mm": 2.0,
        "hs_via_limit": 2,
        "rf_via_limit": 1,
        "crosstalk_guard_mm": 0.4,
        "analog_guard_mm": 0.8,
        "rf_guard_mm": 1.2,
    },
    "high_speed_digital": {
        "edge_clearance_mm": 0.2,
        "power_min_width_mm": 0.6,
        "hs_diff_gap_mm": {"min": 0.1, "opt": 0.14, "max": 0.18},
        "hs_diff_skew_mm": 0.15,
        "hs_diff_uncoupled_mm": 1.5,
        "hs_via_limit": 2,
        "rf_via_limit": 1,
        "crosstalk_guard_mm": 0.35,
        "analog_guard_mm": 0.6,
        "rf_guard_mm": 1.0,
    },
    "rf_mixed_signal": {
        "edge_clearance_mm": 0.35,
        "power_min_width_mm": 0.7,
        "hs_diff_gap_mm": {"min": 0.12, "opt": 0.18, "max": 0.22},
        "hs_diff_skew_mm": 0.15,
        "hs_diff_uncoupled_mm": 1.0,
        "hs_via_limit": 1,
        "rf_via_limit": 1,
        "crosstalk_guard_mm": 0.5,
        "analog_guard_mm": 1.0,
        "rf_guard_mm": 2.0,
    },
    "power": {
        "edge_clearance_mm": 0.3,
        "power_min_width_mm": 1.0,
        "hs_diff_gap_mm": {"min": 0.15, "opt": 0.2, "max": 0.25},
        "hs_diff_skew_mm": 0.25,
        "hs_diff_uncoupled_mm": 3.0,
        "hs_via_limit": 2,
        "rf_via_limit": 1,
        "crosstalk_guard_mm": 0.5,
        "analog_guard_mm": 1.0,
        "rf_guard_mm": 1.5,
    },
    "dense_bga": {
        "edge_clearance_mm": 0.2,
        "power_min_width_mm": 0.6,
        "hs_diff_gap_mm": {"min": 0.09, "opt": 0.12, "max": 0.16},
        "hs_diff_skew_mm": 0.12,
        "hs_diff_uncoupled_mm": 1.0,
        "hs_via_limit": 2,
        "rf_via_limit": 1,
        "crosstalk_guard_mm": 0.25,
        "analog_guard_mm": 0.5,
        "rf_guard_mm": 0.8,
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


def _path_length_mm(points: Sequence[PointMm]) -> float:
    total = 0.0
    for start, end in zip(points, points[1:]):
        total += _distance_mm(start, end)
    return total


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


def _bus_member_signature(net_name: str) -> Optional[Tuple[str, int]]:
    name = (net_name or "").strip()
    if not name:
        return None

    bracket_match = re.match(r"^(?P<prefix>.+?)[\[\<](?P<index>\d+)[\]\>]$", name)
    if bracket_match:
        prefix = re.sub(r"[_\-\s]+$", "", bracket_match.group("prefix") or "")
        if prefix:
            return (_norm(prefix), int(bracket_match.group("index")))

    suffix_match = re.match(r"^(?P<prefix>.*?[A-Za-z])(?:[_\-])?(?P<index>\d+)$", name)
    if suffix_match:
        prefix = re.sub(r"[_\-\s]+$", "", suffix_match.group("prefix") or "")
        if prefix:
            return (_norm(prefix), int(suffix_match.group("index")))

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


def _clearance_condition_for_nets(
    source_nets: Iterable[str],
    *,
    exclude_nets: Optional[Iterable[str]] = None,
) -> Optional[str]:
    """Build KiCad clearance-rule conditions with explicit B-net exclusions."""
    sources = [net for net in sorted(set(source_nets)) if net]
    if not sources:
        return None

    excluded = {net for net in (exclude_nets or []) if net}
    clauses: List[str] = []
    for net in sources:
        parts = [f"A.NetName == '{net}'"]
        for other in sorted(excluded):
            if other == net:
                parts.append(f"B.NetName != '{other}'")
            else:
                parts.append(f"B.NetName != '{other}'")
        clauses.append("(" + " && ".join(parts) + ")")
    return " || ".join(clauses)


# ---------------------------------------------------------------------------
#  IPC-2221 current capacity calculation
# ---------------------------------------------------------------------------

def ipc2221_trace_width_mm(
    current_a: float,
    temp_rise_c: float = 10.0,
    copper_oz: float = 1.0,
    is_external: bool = True,
) -> float:
    """Calculate minimum trace width for a given current using IPC-2221.

    Formula: I = k * dT^0.44 * A^0.725
    where A = cross-section area in mil^2, dT = temp rise in C.
    k = 0.048 for external layers, 0.024 for internal layers.

    Reference: IPC-2221A Section 6.2 (charts 6-4 / 6-3).
    Also validated against He (2024) Table 4.2 clearance defaults.
    """
    if current_a <= 0 or temp_rise_c <= 0 or copper_oz <= 0:
        return 0.0
    k = 0.048 if is_external else 0.024
    # Solve for A (mil^2): A = (I / (k * dT^0.44))^(1/0.725)
    area_mil2 = (current_a / (k * (temp_rise_c ** 0.44))) ** (1.0 / 0.725)
    thickness_mil = copper_oz * 1.378  # 1 oz = 1.378 mil (35 um)
    width_mil = area_mil2 / thickness_mil
    width_mm = width_mil * 0.0254
    return round(max(width_mm, 0.1), 4)  # floor at 0.1mm


def compute_weighted_qor_score(
    metrics: Dict[str, Any],
    flags: Dict[str, Any],
    weights: Dict[str, float],
    constraints: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Compute a single weighted QoR score from routing metrics.

    Normalises each metric to [0,1] where 1 = perfect, then computes a
    weighted geometric mean.  The individual sub-scores are returned so
    the caller can see which dimension is worst.

    Weight keys: length, vias, skew, uncoupled, returnPathRisk, completion,
                 drcErrors.

    Reference: Inspired by He (2024) Eq 3.1 composite reward and
    FreeRouting's internal score (wirelength + gamma_g * N_via).
    """
    w = {
        "completion": 10.0,
        "drcErrors": 8.0,
        "length": 1.0,
        "vias": 2.0,
        "skew": 5.0,
        "uncoupled": 5.0,
        "returnPathRisk": 8.0,
    }
    w.update(weights or {})

    sub: Dict[str, float] = {}

    # Completion: 1.0 = all routed
    sub["completion"] = float(metrics.get("completionRate", 0.0))

    # DRC: 1.0 = zero errors
    drc_errors = int(metrics.get("drcErrors", 0))
    sub["drcErrors"] = 1.0 / (1.0 + drc_errors)

    # Wirelength: lower is better — normalise against a soft upper bound
    wl = float(metrics.get("wirelengthMm", 0))
    # Soft reference: 500mm (typical small board), scales logarithmically
    sub["length"] = 1.0 / (1.0 + wl / 500.0)

    # Via count: fewer is better (He 2024: gamma_g=5 penalty per via)
    vias = int(metrics.get("viaCount", 0))
    sub["vias"] = 1.0 / (1.0 + vias / 10.0)

    # Diff pair skew: closer to zero is better
    skew = float(metrics.get("maxDiffSkewMm", 0))
    skew_limit = 0.25  # default
    if constraints:
        skew_limit = float(
            constraints.get("defaults", {}).get("hs_diff_skew_mm", 0.25)
        )
    diff_skew_ratio = skew / max(skew_limit, 0.01)
    matched_group_skew_ratio = float(metrics.get("maxMatchedGroupSkewRatio", 0.0))
    worst_skew_ratio = max(diff_skew_ratio, matched_group_skew_ratio)
    sub["skew"] = max(0.0, 1.0 - max(0.0, worst_skew_ratio - 1.0))

    # Uncoupled: closer to zero is better
    uncoupled = float(metrics.get("maxUncoupledMm", 0))
    uncoupled_limit = 3.0
    if constraints:
        uncoupled_limit = float(
            constraints.get("defaults", {}).get("hs_diff_uncoupled_mm", 3.0)
        )
    uncoupled_ratio = uncoupled / max(uncoupled_limit, 0.01)
    sub["uncoupled"] = max(0.0, 1.0 - max(0.0, uncoupled_ratio - 1.0))

    # Return path risk: binary per-flag (1.0 if no flags)
    risk_count = len(flags.get("returnPathRisk", []))
    sub["returnPathRisk"] = 1.0 / (1.0 + risk_count)

    # Weighted geometric mean (avoids one bad metric drowning everything)
    total_weight = sum(w.get(k, 0) for k in sub)
    if total_weight <= 0:
        return {"score": 0.0, "subScores": sub}

    log_sum = sum(w.get(k, 0) * math.log(max(v, 1e-9)) for k, v in sub.items())
    score = math.exp(log_sum / total_weight)

    return {
        "score": round(score, 4),
        "subScores": {k: round(v, 4) for k, v in sub.items()},
        "weights": {k: w.get(k, 0) for k in sub},
        "grade": (
            "A" if score >= 0.85 else
            "B" if score >= 0.70 else
            "C" if score >= 0.50 else
            "D" if score >= 0.30 else
            "F"
        ),
    }


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
        elif constraint == "clearance":
            lines.append(f'  (constraint clearance (min {rule["min"]}mm))')
        elif constraint == "length":
            lines.append(f'  (constraint length (max {rule["max"]}mm))')
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

    @staticmethod
    def _board_bounds_mm(board: pcbnew.BOARD) -> Optional[Tuple[float, float, float, float]]:
        try:
            bbox = board.GetBoardEdgesBoundingBox()
            return (
                float(bbox.GetLeft()) / 1_000_000,
                float(bbox.GetTop()) / 1_000_000,
                float(bbox.GetRight()) / 1_000_000,
                float(bbox.GetBottom()) / 1_000_000,
            )
        except Exception:
            return None

    @staticmethod
    def _zone_bbox_mm(zone) -> Optional[Tuple[float, float, float, float]]:
        try:
            bbox = zone.GetBoundingBox()
            left = float(bbox.GetLeft()) / 1_000_000
            top = float(bbox.GetTop()) / 1_000_000
            right = float(bbox.GetRight()) / 1_000_000
            bottom = float(bbox.GetBottom()) / 1_000_000
        except Exception:
            return None
        if right <= left or bottom <= top:
            return None
        return (left, top, right, bottom)

    @staticmethod
    def _preferred_edge_from_bias(bias: float, *, threshold: float = 0.15) -> str:
        if abs(bias) < threshold:
            return "balanced"
        return "right" if bias > 0 else "left"

    def _collect_zones(self, board: pcbnew.BOARD) -> List[Dict[str, Any]]:
        zones: List[Dict[str, Any]] = []
        bounds = self._board_bounds_mm(board)
        center_x = ((bounds[0] + bounds[2]) / 2.0) if bounds else None
        try:
            for zone in list(board.Zones()):
                zone_data: Dict[str, Any] = {
                    "net": zone.GetNetname(),
                    "layer": board.GetLayerName(zone.GetLayer()),
                    "priority": zone.GetAssignedPriority(),
                }
                bbox = self._zone_bbox_mm(zone)
                if bbox:
                    left, top, right, bottom = bbox
                    zone_data["bboxMm"] = {
                        "left": round(left, 4),
                        "top": round(top, 4),
                        "right": round(right, 4),
                        "bottom": round(bottom, 4),
                    }
                    zone_data["centroidXmm"] = round((left + right) / 2.0, 4)
                    if bounds is not None and center_x is not None:
                        board_left, board_top, board_right, board_bottom = bounds
                        overlap_top = max(board_top, top)
                        overlap_bottom = min(board_bottom, bottom)
                        if overlap_bottom > overlap_top:
                            height = overlap_bottom - overlap_top
                            left_width = max(0.0, min(right, center_x) - max(left, board_left))
                            right_width = max(0.0, min(right, board_right) - max(left, center_x))
                            left_area = left_width * height
                            right_area = right_width * height
                            total_area = left_area + right_area
                            if total_area > 0:
                                edge_bias = (right_area - left_area) / total_area
                            else:
                                edge_bias = ((left + right) / 2.0 - center_x) / max(board_right - board_left, 1e-6)
                            zone_data["leftArea"] = round(left_area, 4)
                            zone_data["rightArea"] = round(right_area, 4)
                            zone_data["edgeBias"] = round(edge_bias, 4)
                            zone_data["preferredEdge"] = self._preferred_edge_from_bias(edge_bias)
                zones.append(zone_data)
        except Exception:
            logger.debug("Zone collection failed", exc_info=True)
        return zones

    def _track_pressure_by_layer(self, board: pcbnew.BOARD) -> Dict[str, float]:
        pressure: Dict[str, float] = {}
        for item in board.GetTracks():
            try:
                is_via = item.Type() == pcbnew.PCB_VIA_T
            except Exception:
                is_via = item.GetClass() == "PCB_VIA"
            if is_via:
                continue
            try:
                layer_name = board.GetLayerName(item.GetLayer())
            except Exception:
                continue
            pressure[layer_name] = pressure.get(layer_name, 0.0) + _track_length_mm(item)
        return pressure

    def _track_edge_pressure_by_layer(self, board: pcbnew.BOARD) -> Dict[str, Dict[str, float]]:
        profile: Dict[str, Dict[str, float]] = {}
        bounds = self._board_bounds_mm(board)
        left_edge = bounds[0] if bounds else None
        right_edge = bounds[2] if bounds else None
        width = max((right_edge - left_edge), 1e-6) if bounds else None

        for item in board.GetTracks():
            try:
                is_via = item.Type() == pcbnew.PCB_VIA_T
            except Exception:
                is_via = item.GetClass() == "PCB_VIA"
            if is_via:
                continue
            try:
                layer_name = board.GetLayerName(item.GetLayer())
            except Exception:
                continue

            length_mm = _track_length_mm(item)
            if length_mm <= 0:
                continue

            bucket = "center"
            if bounds is not None and left_edge is not None and right_edge is not None and width is not None:
                midpoint_x: Optional[float] = None
                try:
                    start = item.GetStart()
                    end = item.GetEnd()
                    midpoint_x = (float(start.x) + float(end.x)) / 2_000_000
                except Exception:
                    try:
                        pos = item.GetPosition()
                        midpoint_x = float(pos.x) / 1_000_000
                    except Exception:
                        midpoint_x = None
                if midpoint_x is not None:
                    relative_x = (midpoint_x - left_edge) / width
                    if relative_x <= 0.33:
                        bucket = "left"
                    elif relative_x >= 0.67:
                        bucket = "right"

            layer_profile = profile.setdefault(
                layer_name,
                {"total": 0.0, "left": 0.0, "right": 0.0, "center": 0.0},
            )
            layer_profile["total"] += length_mm
            layer_profile[bucket] += length_mm

        return {
            layer: {bucket: round(value, 4) for bucket, value in buckets.items()}
            for layer, buckets in profile.items()
        }

    def _reference_zone_outline(
        self,
        board: pcbnew.BOARD,
        *,
        inset_mm: float,
    ) -> Optional[List[Dict[str, float]]]:
        try:
            bbox = board.GetBoardEdgesBoundingBox()
            x1 = bbox.GetLeft() / 1_000_000
            y1 = bbox.GetTop() / 1_000_000
            x2 = bbox.GetRight() / 1_000_000
            y2 = bbox.GetBottom() / 1_000_000
        except Exception:
            logger.debug("Board bounding box unavailable for reference zone", exc_info=True)
            return None

        inset = max(0.0, float(inset_mm))
        if x2 - x1 <= inset * 2 or y2 - y1 <= inset * 2:
            return None

        return [
            {"x": round(x1 + inset, 6), "y": round(y1 + inset, 6)},
            {"x": round(x2 - inset, 6), "y": round(y1 + inset, 6)},
            {"x": round(x2 - inset, 6), "y": round(y2 - inset, 6)},
            {"x": round(x1 + inset, 6), "y": round(y2 - inset, 6)},
        ]

    def _select_reference_zone_layer(
        self,
        board: pcbnew.BOARD,
        *,
        zones: Sequence[Dict[str, Any]],
    ) -> Optional[str]:
        copper_layers = self._board_layers(board)
        if not copper_layers:
            return None

        occupied_ground_layers = {
            zone.get("layer")
            for zone in zones
            if _best_intent(zone.get("net", "")) == "GROUND"
        }
        internal_layers = [
            layer
            for layer in copper_layers
            if layer not in {"F.Cu", "B.Cu"} and layer not in occupied_ground_layers
        ]
        if internal_layers:
            return internal_layers[0]

        pressure = self._track_pressure_by_layer(board)
        candidates = [layer for layer in copper_layers if layer not in occupied_ground_layers]
        if not candidates:
            return None

        return min(
            candidates,
            key=lambda layer: (
                pressure.get(layer, 0.0),
                0 if layer == "B.Cu" else 1,
                layer,
            ),
        )

    def _preferred_signal_layer_for_reference(
        self,
        *,
        copper_layers: Sequence[str],
        reference_layer: Optional[str],
        split_risk_layers: Sequence[str],
        track_pressure_by_layer: Dict[str, Any],
        edge_pressure_by_layer: Dict[str, Dict[str, Any]],
        preferred_entry_edge: Optional[str],
        reference_continuity_score: float,
    ) -> Tuple[Optional[str], List[Dict[str, Any]]]:
        if not copper_layers:
            return None, []

        candidate_layers = [layer for layer in copper_layers if layer != reference_layer] or list(copper_layers)
        candidates: List[Dict[str, Any]] = []
        split_risk_set = {str(layer) for layer in split_risk_layers}

        for layer in candidate_layers:
            if not reference_layer:
                adjacency_rank = 0 if layer == "F.Cu" else 1
            elif reference_layer == "B.Cu":
                adjacency_rank = 0 if layer == "F.Cu" else (1 if layer.startswith("In") else 2)
            elif reference_layer == "F.Cu":
                adjacency_rank = 0 if layer == "B.Cu" else (1 if layer.startswith("In") else 2)
            elif reference_layer.startswith("In"):
                adjacency_rank = 0 if layer in {"F.Cu", "B.Cu"} else 1
            else:
                adjacency_rank = 1

            total_pressure = float(track_pressure_by_layer.get(layer, 0.0) or 0.0)
            layer_edge_profile = edge_pressure_by_layer.get(layer, {})
            edge_bucket = preferred_entry_edge if preferred_entry_edge in {"left", "right"} else "center"
            edge_pressure = float(layer_edge_profile.get(edge_bucket, total_pressure) or 0.0)
            weighted_edge_pressure = edge_pressure * (1.0 + max(0.0, float(reference_continuity_score or 0.0)))
            if reference_layer and str(reference_layer).startswith("In"):
                outer_bias_rank = 0 if layer == "F.Cu" else (1 if layer == "B.Cu" else 2)
            else:
                outer_bias_rank = 0 if layer == "B.Cu" else (1 if layer == "F.Cu" else 2)
            candidates.append(
                {
                    "layer": layer,
                    "splitRisk": layer in split_risk_set,
                    "adjacencyRank": adjacency_rank,
                    "totalPressure": round(total_pressure, 4),
                    "edgePressure": round(edge_pressure, 4),
                    "weightedEdgePressure": round(weighted_edge_pressure, 4),
                    "edgeBucket": edge_bucket,
                    "outerBiasRank": outer_bias_rank,
                }
            )

        candidates.sort(
            key=lambda item: (
                1 if item["splitRisk"] else 0,
                int(item["adjacencyRank"]),
                float(item["weightedEdgePressure"]),
                float(item["totalPressure"]),
                int(item["outerBiasRank"]),
                item["layer"],
            )
        )
        return str(candidates[0]["layer"]), candidates

    @staticmethod
    def _inventory_pad_refs(info: Dict[str, Any]) -> List[str]:
        refs = {
            str(ref)
            for ref in info.get("pad_refs", []) or []
            if ref
        }
        for pad in info.get("pads", []) or []:
            ref = pad.get("ref")
            if ref:
                refs.add(str(ref))
        return sorted(refs)

    @staticmethod
    def _inventory_pad_points(
        info: Dict[str, Any],
        *,
        refs_filter: Optional[Sequence[str]] = None,
    ) -> List[PointMm]:
        allowed_refs = {str(ref) for ref in refs_filter or [] if ref}
        points: List[PointMm] = []
        for pad in info.get("pads", []) or []:
            ref = str(pad.get("ref") or "")
            if allowed_refs and ref not in allowed_refs:
                continue
            x = pad.get("x")
            y = pad.get("y")
            if x is None or y is None:
                continue
            try:
                points.append((float(x), float(y)))
            except (TypeError, ValueError):
                continue
        return points

    @staticmethod
    def _point_centroid(points: Sequence[PointMm]) -> Optional[PointMm]:
        if not points:
            return None
        return (
            sum(point[0] for point in points) / len(points),
            sum(point[1] for point in points) / len(points),
        )

    @staticmethod
    def _mean_distance_to_point(
        points: Sequence[PointMm],
        target: Optional[PointMm],
    ) -> Optional[float]:
        if not points or target is None:
            return None
        return sum(math.hypot(point[0] - target[0], point[1] - target[1]) for point in points) / len(points)

    def _select_reference_ground_net(
        self,
        *,
        ground_candidates: Sequence[str],
        sensitive_nets: Sequence[str],
        intents: Sequence[Dict[str, Any]],
        inventory: Dict[str, Any],
    ) -> Tuple[Optional[str], Dict[str, Any]]:
        candidate_names = list(dict.fromkeys(str(name) for name in ground_candidates if name))
        sensitive_names = {
            str(name)
            for name in sensitive_nets
            if name and str(name) in inventory
        }
        sensitive_refs = set()
        sensitive_points: List[PointMm] = []
        for net_name in sensitive_names:
            info = inventory.get(net_name, {})
            sensitive_refs.update(self._inventory_pad_refs(info))
            sensitive_points.extend(self._inventory_pad_points(info))
        for item in intents:
            net_name = str(item.get("net_name") or "")
            if net_name not in sensitive_names:
                continue
            for ref in item.get("component_refs", []) or []:
                if ref:
                    sensitive_refs.add(str(ref))
        sensitive_ref_list = sorted(sensitive_refs)
        sensitive_centroid = self._point_centroid(sensitive_points)

        if not candidate_names:
            return None, {
                "strategy": "local_overlap_then_name",
                "basis": "no_ground_candidates",
                "sensitiveRefs": sensitive_ref_list,
                "candidateScores": [],
            }

        score_rows: List[Dict[str, Any]] = []
        for net_name in candidate_names:
            info = inventory.get(net_name, {})
            refs = set(self._inventory_pad_refs(info))
            shared_refs = sorted(refs & sensitive_refs)
            all_points = self._inventory_pad_points(info)
            local_points = self._inventory_pad_points(info, refs_filter=shared_refs)
            distance_points = local_points or all_points
            avg_distance = self._mean_distance_to_point(distance_points, sensitive_centroid)
            score_rows.append(
                {
                    "net": net_name,
                    "sharedRefCount": len(shared_refs),
                    "sharedPadCount": len(local_points),
                    "sharedRefs": shared_refs,
                    "avgDistanceMm": round(avg_distance, 4) if avg_distance is not None else None,
                    "existingZoneLayers": sorted(
                        {
                            zone.get("layer")
                            for zone in info.get("zones", [])
                            if zone.get("layer")
                        }
                    ),
                }
            )

        def _candidate_key(row: Dict[str, Any]) -> Tuple[Any, ...]:
            name = row["net"]
            avg_distance = row.get("avgDistanceMm")
            return (
                -int(row.get("sharedPadCount", 0)),
                -int(row.get("sharedRefCount", 0)),
                avg_distance if avg_distance is not None else float("inf"),
                0 if name == "GND" else 1,
                0 if name == "AGND" else 1,
                0 if name == "PGND" else 1,
                len(name),
                name,
            )

        selected = min(score_rows, key=_candidate_key)
        if selected.get("sharedPadCount", 0) > 0 or selected.get("sharedRefCount", 0) > 0:
            basis = "local_overlap"
        elif selected.get("avgDistanceMm") is not None:
            basis = "geometric_proximity"
        else:
            basis = "name_bias"

        return selected["net"], {
            "strategy": "local_overlap_then_name",
            "basis": basis,
            "sensitiveRefs": sensitive_ref_list,
            "candidateScores": score_rows,
        }

    def _reference_entry_topology(
        self,
        *,
        ground_net: Optional[str],
        ground_selection: Dict[str, Any],
        sensitive_nets: Sequence[str],
        inventory: Dict[str, Any],
    ) -> Dict[str, Any]:
        if not ground_net:
            return {
                "preferredEntryEdge": "balanced",
                "entryEdgeBias": 0.0,
                "referenceContinuityScore": 0.0,
                "topologyCueSource": "none",
                "sensitiveCentroidXmm": None,
                "groundCentroidXmm": None,
            }

        ground_info = inventory.get(ground_net, {})
        zone_biases: List[Tuple[float, float]] = []
        zone_centroids: List[float] = []
        for zone in ground_info.get("zones", []) or []:
            try:
                bias = float(zone.get("edgeBias"))
            except (TypeError, ValueError):
                continue
            try:
                weight = float(zone.get("leftArea", 0.0)) + float(zone.get("rightArea", 0.0))
            except (TypeError, ValueError):
                weight = 0.0
            zone_biases.append((bias, weight if weight > 0 else 1.0))
            try:
                zone_centroids.append(float(zone.get("centroidXmm")))
            except (TypeError, ValueError):
                pass

        if zone_biases:
            total_weight = sum(weight for _, weight in zone_biases) or 1.0
            avg_bias = sum(bias * weight for bias, weight in zone_biases) / total_weight
            ground_centroid_x = (
                sum(zone_centroids) / len(zone_centroids)
                if zone_centroids
                else None
            )
            return {
                "preferredEntryEdge": self._preferred_edge_from_bias(avg_bias),
                "entryEdgeBias": round(avg_bias, 4),
                "referenceContinuityScore": round(min(1.0, abs(avg_bias)), 4),
                "topologyCueSource": "zone_affinity",
                "sensitiveCentroidXmm": None,
                "groundCentroidXmm": round(ground_centroid_x, 4) if ground_centroid_x is not None else None,
            }

        sensitive_refs = list(ground_selection.get("sensitiveRefs", []) or [])
        sensitive_points: List[PointMm] = []
        for net_name in sensitive_nets:
            sensitive_points.extend(
                self._inventory_pad_points(
                    inventory.get(net_name, {}),
                    refs_filter=sensitive_refs or None,
                )
            )

        ground_points = self._inventory_pad_points(
            ground_info,
            refs_filter=sensitive_refs or None,
        ) or self._inventory_pad_points(ground_info)

        sensitive_centroid = self._point_centroid(sensitive_points)
        ground_centroid = self._point_centroid(ground_points)

        all_x: List[float] = []
        for info in inventory.values():
            for point in self._inventory_pad_points(info):
                all_x.append(point[0])

        if not all_x:
            return {
                "preferredEntryEdge": "balanced",
                "entryEdgeBias": 0.0,
                "referenceContinuityScore": 0.0,
                "topologyCueSource": "none",
                "sensitiveCentroidXmm": round(sensitive_centroid[0], 4) if sensitive_centroid else None,
                "groundCentroidXmm": round(ground_centroid[0], 4) if ground_centroid else None,
            }

        left_edge = min(all_x)
        right_edge = max(all_x)
        width = max(right_edge - left_edge, 1e-6)
        center_x = (left_edge + right_edge) / 2.0
        centroid_samples = [
            centroid[0]
            for centroid in (sensitive_centroid, ground_centroid)
            if centroid is not None
        ]
        if not centroid_samples:
            return {
                "preferredEntryEdge": "balanced",
                "entryEdgeBias": 0.0,
                "referenceContinuityScore": 0.0,
                "topologyCueSource": "none",
                "sensitiveCentroidXmm": None,
                "groundCentroidXmm": None,
            }

        target_x = sum(centroid_samples) / len(centroid_samples)
        raw_bias = (target_x - center_x) / (width / 2.0)
        edge_bias = max(-1.0, min(1.0, raw_bias))
        continuity_score = abs(edge_bias)
        if ground_selection.get("basis") == "local_overlap":
            continuity_score = min(1.0, continuity_score + 0.15)

        return {
            "preferredEntryEdge": self._preferred_edge_from_bias(edge_bias),
            "entryEdgeBias": round(edge_bias, 4),
            "referenceContinuityScore": round(continuity_score, 4),
            "topologyCueSource": "pad_centroid",
            "sensitiveCentroidXmm": round(sensitive_centroid[0], 4) if sensitive_centroid else None,
            "groundCentroidXmm": round(ground_centroid[0], 4) if ground_centroid else None,
        }

    def _synthesize_reference_planning(
        self,
        *,
        by_intent: Dict[str, List[str]],
        intents: Sequence[Dict[str, Any]],
        inventory: Dict[str, Any],
        analysis_summary: Dict[str, Any],
    ) -> Dict[str, Any]:
        copper_layers = list(analysis_summary.get("copperLayers", []) or [])
        split_risk_layers = list(analysis_summary.get("splitRiskLayers", []) or [])
        hs_nets = list(
            dict.fromkeys(
                by_intent.get("HS_DIFF", [])
                + by_intent.get("HS_SINGLE", [])
                + by_intent.get("RF", [])
            )
        )
        ground_candidates = [
            net_name
            for net_name, info in inventory.items()
            if _best_intent(net_name) == "GROUND" and info.get("pads")
        ]
        ground_net, ground_selection = self._select_reference_ground_net(
            ground_candidates=ground_candidates,
            sensitive_nets=hs_nets,
            intents=intents,
            inventory=inventory,
        )

        all_ground_zone_layers = sorted(
            {
                zone.get("layer")
                for net_name in ground_candidates
                for zone in inventory.get(net_name, {}).get("zones", [])
                if zone.get("layer")
            }
        )
        existing_ground_zone_layers = sorted(
            {
                zone.get("layer")
                for zone in (inventory.get(ground_net, {}) if ground_net else {}).get("zones", [])
                if zone.get("layer")
            }
        )
        other_ground_zone_layers = sorted(
            set(all_ground_zone_layers) - set(existing_ground_zone_layers)
        )
        zone_layer_candidates = existing_ground_zone_layers or all_ground_zone_layers

        preferred_zone_layer: Optional[str] = None
        if zone_layer_candidates:
            preferred_zone_layer = min(
                zone_layer_candidates,
                key=lambda layer: (
                    1 if layer in split_risk_layers else 0,
                    0 if layer.startswith("In") else 1,
                    0 if layer == "B.Cu" else 1,
                    layer,
                ),
            )
        elif copper_layers:
            internal_layers = [
                layer
                for layer in copper_layers
                if layer not in {"F.Cu", "B.Cu"}
            ]
            if internal_layers:
                preferred_zone_layer = min(
                    internal_layers,
                    key=lambda layer: (
                        1 if layer in split_risk_layers else 0,
                        layer,
                    ),
                )
            else:
                outer_candidates = [layer for layer in copper_layers if layer in {"F.Cu", "B.Cu"}] or copper_layers
                preferred_zone_layer = min(
                    outer_candidates,
                    key=lambda layer: (
                        1 if layer in split_risk_layers else 0,
                        0 if layer == "B.Cu" else 1,
                        layer,
                    ),
                )

        topology_cue = self._reference_entry_topology(
            ground_net=ground_net,
            ground_selection=ground_selection,
            sensitive_nets=hs_nets,
            inventory=inventory,
        )
        preferred_signal_layer, signal_layer_candidates = self._preferred_signal_layer_for_reference(
            copper_layers=copper_layers,
            reference_layer=preferred_zone_layer,
            split_risk_layers=split_risk_layers,
            track_pressure_by_layer=dict(analysis_summary.get("trackPressureByLayer", {}) or {}),
            edge_pressure_by_layer=dict(analysis_summary.get("edgePressureByLayer", {}) or {}),
            preferred_entry_edge=topology_cue["preferredEntryEdge"],
            reference_continuity_score=float(topology_cue["referenceContinuityScore"] or 0.0),
        )
        should_auto_create = bool(hs_nets and ground_net and not existing_ground_zone_layers)

        if not hs_nets:
            reason = "no_high_speed_nets"
        elif not ground_net:
            reason = "no_ground_net"
        elif existing_ground_zone_layers:
            reason = "selected_ground_zone_already_present"
        elif other_ground_zone_layers:
            reason = "selected_ground_net_needs_local_reference_plane"
        else:
            reason = "high_speed_nets_need_reference_plane"

        return {
            "groundNet": ground_net,
            "highSpeedNets": hs_nets,
            "existingGroundZoneLayers": existing_ground_zone_layers,
            "allGroundZoneLayers": all_ground_zone_layers,
            "otherGroundZoneLayers": other_ground_zone_layers,
            "preferredZoneLayer": preferred_zone_layer,
            "preferredSignalLayer": preferred_signal_layer,
            "signalLayerCandidates": signal_layer_candidates,
            "splitRiskLayers": split_risk_layers,
            "shouldAutoCreate": should_auto_create,
            "reason": reason,
            "sensitiveRefs": ground_selection.get("sensitiveRefs", []),
            "groundNetSelection": ground_selection,
            "preferredEntryEdge": topology_cue["preferredEntryEdge"],
            "entryEdgeBias": topology_cue["entryEdgeBias"],
            "referenceContinuityScore": topology_cue["referenceContinuityScore"],
            "topologyCueSource": topology_cue["topologyCueSource"],
            "sensitiveCentroidXmm": topology_cue["sensitiveCentroidXmm"],
            "groundCentroidXmm": topology_cue["groundCentroidXmm"],
        }

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

    def _collect_net_via_positions(
        self,
        board: pcbnew.BOARD,
    ) -> Dict[str, List[PointMm]]:
        via_positions: Dict[str, List[PointMm]] = {}
        for item in board.GetTracks():
            try:
                is_via = item.Type() == pcbnew.PCB_VIA_T
            except Exception:
                is_via = item.GetClass() == "PCB_VIA"
            if not is_via:
                continue

            try:
                net_name = item.GetNetname()
            except Exception:
                net_name = ""
            if not net_name:
                continue

            try:
                position = item.GetPosition()
            except Exception:
                continue

            via_positions.setdefault(net_name, []).append(
                (position.x / 1_000_000, position.y / 1_000_000)
            )
        return via_positions

    def _ensure_reference_ground_zone(
        self,
        board: pcbnew.BOARD,
        board_path: Path,
        *,
        constraints_data: Dict[str, Any],
        params: Dict[str, Any],
    ) -> Dict[str, Any]:
        if not params.get("autoCreateReferenceZones", True):
            return {
                "success": True,
                "created": False,
                "message": "Reference-zone synthesis disabled",
            }

        if self.routing_commands is None or not hasattr(self.routing_commands, "add_copper_pour"):
            return {
                "success": True,
                "created": False,
                "message": "Reference-zone synthesis unavailable",
            }

        zones = self._collect_zones(board)
        inventory = self._collect_inventory(board)
        reference_planning = dict(constraints_data.get("referencePlanning") or {})
        sensitive_nets = [
            item.get("net_name")
            for item in constraints_data.get("intents", [])
            if item.get("intent") in {"HS_SINGLE", "HS_DIFF", "RF"}
        ]
        if not sensitive_nets:
            sensitive_nets = [
                net_name
                for net_name in inventory
                if _best_intent(net_name) in {"HS_SINGLE", "RF"} or _diff_partner_name(net_name) in inventory
            ]
        if not sensitive_nets:
            return {
                "success": True,
                "created": False,
                "message": "No high-speed nets require a reference zone",
            }

        explicit_net = params.get("referenceZoneNet") or reference_planning.get("groundNet")
        if explicit_net:
            ground_net = str(explicit_net)
            if ground_net not in inventory:
                return {
                    "success": False,
                    "created": False,
                    "message": f"Reference-zone net '{ground_net}' does not exist on the board",
                }
        else:
            ground_candidates = [
                net_name
                for net_name, info in inventory.items()
                if _best_intent(net_name) == "GROUND" and info.get("pads")
            ]
            if not ground_candidates:
                return {
                    "success": True,
                    "created": False,
                    "message": "No ground net is present on the board",
                }
            ground_net, _ = self._select_reference_ground_net(
                ground_candidates=ground_candidates,
                sensitive_nets=sensitive_nets,
                intents=constraints_data.get("intents", []),
                inventory=inventory,
            )

        selected_ground_zone_layers = sorted(
            {
                zone.get("layer")
                for zone in zones
                if zone.get("net") == ground_net and zone.get("layer")
            }
        )
        if selected_ground_zone_layers:
            return {
                "success": True,
                "created": False,
                "message": f"Ground reference zone already exists for {ground_net}",
                "net": ground_net,
                "existingLayers": selected_ground_zone_layers,
            }

        layer = (
            params.get("referenceZoneLayer")
            or reference_planning.get("preferredZoneLayer")
            or self._select_reference_zone_layer(board, zones=zones)
        )
        if not layer:
            return {
                "success": True,
                "created": False,
                "message": "No suitable copper layer available for a reference zone",
            }

        defaults = constraints_data.get("defaults", {})
        inset_mm = float(
            params.get(
                "referenceZoneInsetMm",
                max(float(defaults.get("edge_clearance_mm", 0.25)), 0.25),
            )
        )
        outline = self._reference_zone_outline(board, inset_mm=inset_mm)
        if not outline:
            return {
                "success": True,
                "created": False,
                "message": "Board extents are too small for a reference-zone inset",
            }

        clearance_mm = float(
            params.get(
                "referenceZoneClearanceMm",
                max(0.2, float(defaults.get("edge_clearance_mm", 0.25))),
            )
        )
        min_width_mm = float(params.get("referenceZoneMinWidthMm", 0.2))
        priority = int(params.get("referenceZonePriority", 0))

        result = self.routing_commands.add_copper_pour(
            {
                "layer": layer,
                "net": ground_net,
                "points": outline,
                "unit": "mm",
                "clearance": clearance_mm,
                "minWidth": min_width_mm,
                "priority": priority,
                "fillType": "solid",
            }
        )
        if not result.get("success"):
            return {
                "success": False,
                "created": False,
                "message": result.get("message", "Reference-zone synthesis failed"),
                "errorDetails": result.get("errorDetails"),
            }

        try:
            if hasattr(board, "BuildConnectivity"):
                board.BuildConnectivity()
        except Exception:
            logger.debug("BuildConnectivity failed after reference-zone creation", exc_info=True)

        return {
            "success": True,
            "created": True,
            "message": "Created automatic ground reference zone",
            "net": ground_net,
            "layer": layer,
            "insetMm": round(inset_mm, 4),
            "clearanceMm": round(clearance_mm, 4),
            "minWidthMm": round(min_width_mm, 4),
        }

    def _prepare_pre_route_reference(
        self,
        board: pcbnew.BOARD,
        board_path: Path,
        *,
        constraints_data: Dict[str, Any],
        params: Dict[str, Any],
    ) -> Dict[str, Any]:
        reference_planning = dict(constraints_data.get("referencePlanning") or {})
        actions: List[str] = []
        critical_layer_source = "user"
        critical_layer = params.get("criticalLayer")
        if not critical_layer:
            critical_layer = reference_planning.get("preferredSignalLayer")
            critical_layer_source = "referencePlanning"
        if not critical_layer:
            copper_layers = self._board_layers(board)
            critical_layer = "F.Cu" if "F.Cu" in copper_layers else (copper_layers[0] if copper_layers else None)
            critical_layer_source = "default"

        stage_params = dict(params)
        if reference_planning.get("groundNet") and not stage_params.get("referenceZoneNet"):
            stage_params["referenceZoneNet"] = reference_planning["groundNet"]
        if reference_planning.get("preferredZoneLayer") and not stage_params.get("referenceZoneLayer"):
            stage_params["referenceZoneLayer"] = reference_planning["preferredZoneLayer"]

        if reference_planning.get("shouldAutoCreate"):
            reference_zone_result = self._ensure_reference_ground_zone(
                board,
                board_path,
                constraints_data=constraints_data,
                params=stage_params,
            )
            if not reference_zone_result.get("success"):
                return {
                    "success": False,
                    "message": reference_zone_result.get("message", "Pre-route reference planning failed"),
                    "referencePlanning": reference_planning,
                    "referenceZone": reference_zone_result,
                    "criticalLayer": critical_layer,
                    "criticalLayerSource": critical_layer_source,
                    "actions": actions,
                }
            if reference_zone_result.get("created"):
                actions.append("reference_ground_zone")
        else:
            reason = reference_planning.get("reason", "planning_not_required")
            reference_zone_result = {
                "success": True,
                "created": False,
                "message": f"Pre-route reference-zone synthesis not required ({reason})",
            }

        if critical_layer:
            actions.append("critical_layer_plan")

        return {
            "success": True,
            "message": "Pre-route reference planning completed",
            "referencePlanning": reference_planning,
            "referenceZone": reference_zone_result,
            "criticalLayer": critical_layer,
            "criticalLayerSource": critical_layer_source,
            "actions": actions,
        }

    def _refill_zones(self, board: pcbnew.BOARD, board_path: Path) -> Dict[str, Any]:
        """Refill zones using the best available backend, with a subprocess fallback."""
        if self.routing_commands is not None and hasattr(self.routing_commands, "refill_zones"):
            try:
                return self.routing_commands.refill_zones({})
            except Exception:
                logger.debug("routing_commands.refill_zones failed", exc_info=True)

        if self.ipc_board_api is not None and hasattr(self.ipc_board_api, "refill_zones"):
            try:
                ok = self.ipc_board_api.refill_zones()
                if ok:
                    return {
                        "success": True,
                        "message": "Zones refilled via IPC backend",
                    }
            except Exception:
                logger.debug("IPC zone refill failed", exc_info=True)

        try:
            board.Save(str(board_path))
        except Exception:
            logger.debug("Board save before zone refill fallback failed", exc_info=True)

        script = (
            "import pcbnew\n"
            f"board = pcbnew.LoadBoard({str(board_path)!r})\n"
            "filler = pcbnew.ZONE_FILLER(board)\n"
            "filler.Fill(board.Zones())\n"
            f"board.Save({str(board_path)!r})\n"
            "print('ok')\n"
        )
        try:
            proc = subprocess.run(
                [sys.executable, "-c", script],
                capture_output=True,
                text=True,
                timeout=60,
            )
        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "message": "Zone refill timed out in fallback subprocess",
            }

        if proc.returncode == 0 and "ok" in (proc.stdout or ""):
            return {
                "success": True,
                "message": "Zones refilled via subprocess fallback",
            }
        return {
            "success": False,
            "message": "Zone refill failed",
            "errorDetails": (proc.stderr or proc.stdout or "").strip()[:400],
        }

    @staticmethod
    def _parse_unconnected_item_blocks(report_text: str) -> List[Dict[str, Any]]:
        """Extract `unconnected_items` entries from KiCad text DRC reports."""
        blocks: List[Dict[str, Any]] = []
        current: Optional[Dict[str, Any]] = None
        header_re = re.compile(r"^\[(?P<type>[^\]]+)\]:\s*(?P<message>.+)$")
        item_re = re.compile(
            r"^\s*@\((?P<x>-?\d+(?:\.\d+)?)\s*mm,\s*(?P<y>-?\d+(?:\.\d+)?)\s*mm\):\s*"
            r"(?P<kind>[A-Za-z]+)(?:\s+[^\[]*)?\s*\[(?P<net>[^\]]+)\]"
            r"(?:.*?\bon\b\s+(?P<layer>[A-Za-z0-9_.]+))?.*$"
        )

        def _flush() -> None:
            nonlocal current
            if current and current.get("type") == "unconnected_items" and current.get("items"):
                blocks.append(current)
            current = None

        for raw_line in report_text.splitlines():
            line = raw_line.rstrip()
            header = header_re.match(line)
            if header:
                _flush()
                current = {
                    "type": header.group("type"),
                    "message": header.group("message").strip(),
                    "items": [],
                }
                continue

            if current is None:
                continue

            item = item_re.match(line)
            if not item:
                continue

            current["items"].append(
                {
                    "kind": item.group("kind"),
                    "net": (item.group("net") or "").strip(),
                    "layer": (item.group("layer") or "").strip(),
                    "x": float(item.group("x")),
                    "y": float(item.group("y")),
                }
            )

        _flush()
        return blocks

    @staticmethod
    def _point_near_existing(point: PointMm, candidates: Sequence[PointMm], tolerance_mm: float = 0.3) -> bool:
        return any(_distance_mm(point, candidate) <= tolerance_mm for candidate in candidates)

    @staticmethod
    def _orthogonal_segment_hits_rect(
        start: PointMm,
        end: PointMm,
        rect: Tuple[float, float, float, float],
    ) -> bool:
        if math.isclose(start[0], end[0], abs_tol=1e-6):
            x = start[0]
            y0, y1 = sorted((start[1], end[1]))
            return rect[0] <= x <= rect[2] and max(y0, rect[1]) <= min(y1, rect[3])
        if math.isclose(start[1], end[1], abs_tol=1e-6):
            y = start[1]
            x0, x1 = sorted((start[0], end[0]))
            return rect[1] <= y <= rect[3] and max(x0, rect[0]) <= min(x1, rect[2])
        return True

    def _plan_support_bridge_path(
        self,
        board: pcbnew.BOARD,
        *,
        layer: str,
        net_name: str,
        start_point: PointMm,
        end_point: PointMm,
        width_mm: float,
    ) -> Optional[List[PointMm]]:
        collect_obstacles = getattr(self.routing_commands, "_collect_routing_obstacles", None)
        if not callable(collect_obstacles):
            return None

        clearance = 0.2
        get_clearance = getattr(self.routing_commands, "_get_clearance_mm", None)
        if callable(get_clearance):
            clearance = float(get_clearance())
        keepout_margin = clearance + width_mm / 2

        try:
            obstacles = collect_obstacles(layer, keepout_margin, net=net_name)
        except Exception:
            logger.debug("Support bridge obstacle collection failed", exc_info=True)
            return None

        try:
            bbox = board.GetBoardEdgesBoundingBox()
            bounds = (
                bbox.GetLeft() / 1_000_000,
                bbox.GetTop() / 1_000_000,
                bbox.GetRight() / 1_000_000,
                bbox.GetBottom() / 1_000_000,
            )
        except Exception:
            return None

        lane_margin = max(keepout_margin + 0.4, 1.0)
        left, top, right, bottom = bounds
        y_candidates = {
            round(top + lane_margin, 6),
            round(bottom - lane_margin, 6),
            round(min(start_point[1], end_point[1]) - lane_margin, 6),
            round(max(start_point[1], end_point[1]) + lane_margin, 6),
        }
        x_candidates = {
            round(left + lane_margin, 6),
            round(right - lane_margin, 6),
            round(min(start_point[0], end_point[0]) - lane_margin, 6),
            round(max(start_point[0], end_point[0]) + lane_margin, 6),
        }

        candidates: List[List[PointMm]] = []
        for y in sorted(y_candidates):
            if top + keepout_margin <= y <= bottom - keepout_margin:
                candidates.append([start_point, (start_point[0], y), (end_point[0], y), end_point])
        for x in sorted(x_candidates):
            if left + keepout_margin <= x <= right - keepout_margin:
                candidates.append([start_point, (x, start_point[1]), (x, end_point[1]), end_point])

        best_path: Optional[List[PointMm]] = None
        best_length = float("inf")
        for path in candidates:
            segments = list(zip(path, path[1:]))
            if any(
                self._orthogonal_segment_hits_rect(seg_start, seg_end, rect)
                for seg_start, seg_end in segments
                for rect in obstacles
            ):
                continue
            length = sum(_distance_mm(seg_start, seg_end) for seg_start, seg_end in segments)
            if length < best_length:
                best_length = length
                best_path = path

        return best_path

    @staticmethod
    def _track_uuid(item: Any) -> str:
        try:
            return item.m_Uuid.AsString()
        except Exception:
            return ""

    def _collect_net_track_segments(
        self,
        board: pcbnew.BOARD,
        net_name: str,
    ) -> List[Dict[str, Any]]:
        segments: List[Dict[str, Any]] = []
        for item in list(board.GetTracks()):
            try:
                if item.GetNetname() != net_name or item.Type() == pcbnew.PCB_VIA_T:
                    continue
                start = item.GetStart()
                end = item.GetEnd()
                start_mm = (start.x / 1_000_000, start.y / 1_000_000)
                end_mm = (end.x / 1_000_000, end.y / 1_000_000)
                segments.append(
                    {
                        "item": item,
                        "uuid": self._track_uuid(item),
                        "layer": board.GetLayerName(item.GetLayer()),
                        "width_mm": _track_width_mm(item),
                        "start": start_mm,
                        "end": end_mm,
                        "length_mm": _track_length_mm(item),
                    }
                )
            except Exception:
                logger.debug("Net track segment collection failed", exc_info=True)
        segments.sort(key=lambda entry: (-entry["length_mm"], entry["layer"], entry["uuid"]))
        return segments

    def _footprint_refs_near_points(
        self,
        board: pcbnew.BOARD,
        points: Sequence[PointMm],
        *,
        tolerance_mm: float = 0.9,
    ) -> List[str]:
        refs: List[str] = []
        for footprint in board.GetFootprints():
            ref = footprint.GetReference()
            matched = False
            for pad in footprint.Pads():
                try:
                    pos = pad.GetPosition()
                    pad_point = (pos.x / 1_000_000, pos.y / 1_000_000)
                except Exception:
                    continue
                if any(_distance_mm(pad_point, point) <= tolerance_mm for point in points):
                    matched = True
                    break
            if matched:
                refs.append(ref)
        return sorted(set(refs))

    def _add_direct_track_segment(
        self,
        board: pcbnew.BOARD,
        *,
        start: PointMm,
        end: PointMm,
        layer: str,
        width_mm: float,
        net_name: str,
    ) -> None:
        layer_id = board.GetLayerID(layer)
        if layer_id < 0:
            raise ValueError(f"Layer '{layer}' does not exist")

        netinfo = board.GetNetInfo()
        nets_map = netinfo.NetsByName()
        net_obj = nets_map[net_name] if nets_map.has_key(net_name) else None
        if net_obj is None:
            raise ValueError(f"Net '{net_name}' does not exist")

        track = pcbnew.PCB_TRACK(board)
        track.SetStart(pcbnew.VECTOR2I(int(start[0] * 1_000_000), int(start[1] * 1_000_000)))
        track.SetEnd(pcbnew.VECTOR2I(int(end[0] * 1_000_000), int(end[1] * 1_000_000)))
        track.SetLayer(layer_id)
        track.SetWidth(int(width_mm * 1_000_000))
        track.SetNet(net_obj)
        board.Add(track)

    def _segments_hit_obstacles(
        self,
        path: Sequence[PointMm],
        obstacles: Sequence[Tuple[float, float, float, float]],
    ) -> bool:
        return any(
            self._orthogonal_segment_hits_rect(seg_start, seg_end, rect)
            for seg_start, seg_end in zip(path, path[1:])
            for rect in obstacles
        )

    def _plan_meander_replacement_path(
        self,
        board: pcbnew.BOARD,
        *,
        layer: str,
        net_name: str,
        start_point: PointMm,
        end_point: PointMm,
        width_mm: float,
        target_extra_mm: float,
        max_bumps: int = 3,
    ) -> Optional[Dict[str, Any]]:
        collect_obstacles = getattr(self.routing_commands, "_collect_routing_obstacles", None)
        if not callable(collect_obstacles):
            return None

        if target_extra_mm <= 0:
            return None

        clearance = 0.2
        get_clearance = getattr(self.routing_commands, "_get_clearance_mm", None)
        if callable(get_clearance):
            clearance = float(get_clearance())

        keepout_margin = clearance + width_mm / 2
        min_depth = max(width_mm * 0.6, 0.12)
        if target_extra_mm < 2 * min_depth - 1e-6:
            return None

        try:
            ignored_refs = self._footprint_refs_near_points(
                board,
                [start_point, end_point],
                tolerance_mm=max(keepout_margin * 2, 0.9),
            )
            obstacles = collect_obstacles(
                layer,
                keepout_margin,
                ignored_refs=ignored_refs,
                net=net_name,
            )
        except Exception:
            logger.debug("Matched-length obstacle collection failed", exc_info=True)
            return None

        try:
            bbox = board.GetBoardEdgesBoundingBox()
            bounds = (
                bbox.GetLeft() / 1_000_000,
                bbox.GetTop() / 1_000_000,
                bbox.GetRight() / 1_000_000,
                bbox.GetBottom() / 1_000_000,
            )
        except Exception:
            return None

        horizontal = math.isclose(start_point[1], end_point[1], abs_tol=1e-6)
        vertical = math.isclose(start_point[0], end_point[0], abs_tol=1e-6)
        if not (horizontal or vertical):
            return None

        start = start_point
        end = end_point
        reversed_path = False
        if horizontal and start[0] > end[0]:
            start, end = end, start
            reversed_path = True
        if vertical and start[1] > end[1]:
            start, end = end, start
            reversed_path = True

        segment_length = _distance_mm(start, end)
        min_bump_span = max(width_mm * 3.0, 0.8)
        overshoot_limit = max(keepout_margin * 0.75, 0.15)

        def _horizontal_path(bump_count: int, y_offset: float) -> Optional[List[PointMm]]:
            if segment_length <= min_bump_span * bump_count:
                return None
            lead = max(min_bump_span / 2, min(segment_length * 0.1, 1.0))
            if segment_length <= 2 * lead + bump_count * min_bump_span:
                return None
            bump_span = max(min_bump_span, (segment_length - 2 * lead) / bump_count * 0.6)
            gap_count = max(bump_count - 1, 1)
            free_gap = max(segment_length - 2 * lead - bump_count * bump_span, 0.0)
            gap = free_gap / gap_count if bump_count > 1 else 0.0
            y0 = start[1]
            path: List[PointMm] = [start]
            cursor = start[0]
            for index in range(bump_count):
                enter_x = start[0] + lead + index * (bump_span + gap)
                exit_x = min(enter_x + bump_span, end[0] - lead)
                if enter_x > cursor + 1e-6:
                    path.append((round(enter_x, 6), round(y0, 6)))
                path.extend(
                    [
                        (round(enter_x, 6), round(y_offset, 6)),
                        (round(exit_x, 6), round(y_offset, 6)),
                        (round(exit_x, 6), round(y0, 6)),
                    ]
                )
                cursor = exit_x
            if cursor < end[0] - 1e-6:
                path.append(end)
            elif path[-1] != end:
                path.append(end)
            return path

        def _vertical_path(bump_count: int, x_offset: float) -> Optional[List[PointMm]]:
            if segment_length <= min_bump_span * bump_count:
                return None
            lead = max(min_bump_span / 2, min(segment_length * 0.1, 1.0))
            if segment_length <= 2 * lead + bump_count * min_bump_span:
                return None
            bump_span = max(min_bump_span, (segment_length - 2 * lead) / bump_count * 0.6)
            gap_count = max(bump_count - 1, 1)
            free_gap = max(segment_length - 2 * lead - bump_count * bump_span, 0.0)
            gap = free_gap / gap_count if bump_count > 1 else 0.0
            x0 = start[0]
            path: List[PointMm] = [start]
            cursor = start[1]
            for index in range(bump_count):
                enter_y = start[1] + lead + index * (bump_span + gap)
                exit_y = min(enter_y + bump_span, end[1] - lead)
                if enter_y > cursor + 1e-6:
                    path.append((round(x0, 6), round(enter_y, 6)))
                path.extend(
                    [
                        (round(x_offset, 6), round(enter_y, 6)),
                        (round(x_offset, 6), round(exit_y, 6)),
                        (round(x0, 6), round(exit_y, 6)),
                    ]
                )
                cursor = exit_y
            if cursor < end[1] - 1e-6:
                path.append(end)
            elif path[-1] != end:
                path.append(end)
            return path

        best_plan: Optional[Dict[str, Any]] = None
        for bump_count in range(1, max_bumps + 1):
            depth = round(target_extra_mm / (2 * bump_count), 6)
            if depth < min_depth:
                continue
            actual_extra = round(2 * bump_count * depth, 6)
            if actual_extra - target_extra_mm > overshoot_limit:
                continue
            for side_sign in (1, -1):
                if horizontal:
                    y_offset = round(start[1] + side_sign * depth, 6)
                    if not (bounds[1] + keepout_margin <= y_offset <= bounds[3] - keepout_margin):
                        continue
                    path = _horizontal_path(bump_count, y_offset)
                else:
                    x_offset = round(start[0] + side_sign * depth, 6)
                    if not (bounds[0] + keepout_margin <= x_offset <= bounds[2] - keepout_margin):
                        continue
                    path = _vertical_path(bump_count, x_offset)

                if not path or not self._path_is_orthogonal(path):
                    continue
                if self._segments_hit_obstacles(path, obstacles):
                    continue

                candidate = {
                    "path": list(reversed(path)) if reversed_path else path,
                    "addedLengthMm": round(_path_length_mm(path) - segment_length, 6),
                    "bumpCount": bump_count,
                    "offsetDepthMm": depth,
                }
                if candidate["addedLengthMm"] < target_extra_mm - 1e-6:
                    continue
                if best_plan is None or (
                    abs(candidate["addedLengthMm"] - target_extra_mm),
                    candidate["bumpCount"],
                ) < (
                    abs(best_plan["addedLengthMm"] - target_extra_mm),
                    best_plan["bumpCount"],
                ):
                    best_plan = candidate

        return best_plan

    def _insert_length_compensation_for_net(
        self,
        board: pcbnew.BOARD,
        *,
        net_name: str,
        target_extra_mm: float,
        preferred_width_mm: Optional[float] = None,
    ) -> Dict[str, Any]:
        if self.routing_commands is None:
            return {"success": False, "message": "Routing commands unavailable"}

        for segment in self._collect_net_track_segments(board, net_name):
            plan = self._plan_meander_replacement_path(
                board,
                layer=segment["layer"],
                net_name=net_name,
                start_point=segment["start"],
                end_point=segment["end"],
                width_mm=float(preferred_width_mm or segment["width_mm"] or 0.25),
                target_extra_mm=target_extra_mm,
            )
            if not plan:
                continue

            width_mm = float(preferred_width_mm or segment["width_mm"] or 0.25)
            original_item = segment["item"]
            board.Remove(original_item)
            route_result = self.routing_commands.route_trace(
                {
                    "start": {"x": plan["path"][0][0], "y": plan["path"][0][1], "unit": "mm"},
                    "end": {"x": plan["path"][-1][0], "y": plan["path"][-1][1], "unit": "mm"},
                    "layer": segment["layer"],
                    "width": width_mm,
                    "net": net_name,
                    "waypoints": [
                        {"x": point[0], "y": point[1], "unit": "mm"}
                        for point in plan["path"][1:-1]
                    ],
                }
            )
            if route_result.get("success"):
                return {
                    "success": True,
                    "net": net_name,
                    "layer": segment["layer"],
                    "start": {"x": round(plan["path"][0][0], 4), "y": round(plan["path"][0][1], 4)},
                    "end": {"x": round(plan["path"][-1][0], 4), "y": round(plan["path"][-1][1], 4)},
                    "replacedSegmentUuid": segment["uuid"],
                    "originalLengthMm": round(segment["length_mm"], 4),
                    "addedLengthMm": round(plan["addedLengthMm"], 4),
                    "targetExtraMm": round(target_extra_mm, 4),
                    "bumpCount": int(plan["bumpCount"]),
                    "offsetDepthMm": round(plan["offsetDepthMm"], 4),
                }

            self._add_direct_track_segment(
                board,
                start=segment["start"],
                end=segment["end"],
                layer=segment["layer"],
                width_mm=width_mm,
                net_name=net_name,
            )

        return {
            "success": False,
            "net": net_name,
            "message": "No viable matched-length compensation segment found",
            "targetExtraMm": round(target_extra_mm, 4),
        }

    def _tune_matched_length_groups(
        self,
        board: pcbnew.BOARD,
        board_path: Path,
        *,
        matched_groups: Sequence[Dict[str, Any]],
        min_extra_mm: float = 0.3,
        max_nets_per_group: int = 4,
    ) -> Dict[str, Any]:
        if not matched_groups:
            return {
                "success": True,
                "message": "Matched-length tuning skipped",
                "tunedNets": [],
                "skipped": [],
            }

        inventory = self._collect_inventory(board)
        tuned_nets: List[Dict[str, Any]] = []
        skipped: List[Dict[str, Any]] = []

        for group in matched_groups:
            group_type = str(group.get("type", "bus"))
            nets = list(dict.fromkeys(group.get("nets", []) or []))
            valid_nets = [net for net in nets if net in inventory and inventory[net].get("track_count", 0) > 0]
            if len(valid_nets) < 2:
                skipped.append({"group": nets, "reason": "insufficient_routed_nets"})
                continue
            if len(valid_nets) > max_nets_per_group:
                skipped.append({"group": valid_nets, "reason": "group_too_large"})
                continue
            if group_type == "diff_pair":
                skipped.append({"group": valid_nets, "reason": "diff_pair_groups_reserved_for_future_tuning"})
                continue

            raw_max_skew = group.get("maxSkewMm")
            max_skew = float(raw_max_skew) if raw_max_skew is not None else 0.5
            observed = {
                net_name: float(inventory[net_name].get("track_length_mm", 0.0))
                for net_name in valid_nets
            }
            target_floor = max(observed.values()) - max_skew
            if target_floor <= min(observed.values()) + 1e-6:
                continue

            width_hint = min(
                [
                    float(inventory[net].get("min_track_width_mm"))
                    for net in valid_nets
                    if inventory[net].get("min_track_width_mm") is not None
                ]
                or [0.25]
            )

            for net_name, length_mm in sorted(observed.items(), key=lambda item: item[1]):
                extra_needed = round(target_floor - length_mm, 6)
                if extra_needed < min_extra_mm:
                    if extra_needed > 0.02:
                        skipped.append(
                            {
                                "group": valid_nets,
                                "net": net_name,
                                "reason": "required_compensation_below_meander_floor",
                                "requiredExtraMm": round(extra_needed, 4),
                            }
                        )
                    continue

                tune_result = self._insert_length_compensation_for_net(
                    board,
                    net_name=net_name,
                    target_extra_mm=extra_needed,
                    preferred_width_mm=width_hint,
                )
                if tune_result.get("success"):
                    tune_result["group"] = valid_nets
                    tune_result["type"] = group_type
                    tune_result["maxSkewMm"] = round(max_skew, 4)
                    tuned_nets.append(tune_result)
                    inventory = self._collect_inventory(board)
                else:
                    skipped.append(
                        {
                            "group": valid_nets,
                            "net": net_name,
                            "reason": "no_viable_meander_path",
                            "requiredExtraMm": round(extra_needed, 4),
                        }
                    )

        try:
            if hasattr(board, "BuildConnectivity"):
                board.BuildConnectivity()
        except Exception:
            logger.debug("BuildConnectivity failed during matched-length tuning", exc_info=True)

        try:
            board.Save(str(board_path))
        except Exception:
            logger.debug("Board save after matched-length tuning failed", exc_info=True)

        return {
            "success": True,
            "message": f"Matched-length tuning adjusted {len(tuned_nets)} net(s)",
            "tunedNets": tuned_nets,
            "skipped": skipped,
        }

    def _infer_auto_matched_length_groups(
        self,
        intents: Sequence[Dict[str, Any]],
        *,
        interfaces: Sequence[str],
        default_max_skew_mm: float,
        params: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        if not params.get("inferMatchedLengthGroups", True):
            return []

        min_group_size = int(params.get("autoMatchedLengthMinGroupSize", 3))
        max_group_size = int(params.get("autoMatchedLengthMaxGroupSize", 16))
        if min_group_size < 2 or max_group_size < min_group_size:
            return []

        interface_prefixes = {
            prefix
            for interface in interfaces
            for prefix in INTERFACE_BUS_PREFIX_HINTS.get(interface, ())
        }
        groups: Dict[str, List[Tuple[int, str]]] = {}
        for intent in intents:
            if intent.get("diff_partner") or intent.get("intent") in {
                "HS_DIFF",
                "GROUND",
                "POWER_DC",
                "POWER_SWITCHING",
                "RF",
                "ANALOG_SENSITIVE",
            }:
                continue

            signature = _bus_member_signature(intent.get("net_name", ""))
            if not signature:
                continue

            stem, index = signature
            if interface_prefixes:
                if not any(stem == prefix or stem.startswith(prefix) for prefix in interface_prefixes):
                    continue
            else:
                if intent.get("intent") != "HS_SINGLE" or len(stem) < 2:
                    continue

            groups.setdefault(stem, []).append((index, intent["net_name"]))

        inferred: List[Dict[str, Any]] = []
        raw_auto_skew = params.get("autoMatchedLengthMaxSkewMm")
        if raw_auto_skew is None:
            max_skew_mm = float(default_max_skew_mm)
        else:
            max_skew_mm = max(0.0, float(raw_auto_skew))
        for stem, members in sorted(groups.items()):
            ordered = sorted({(index, net_name) for index, net_name in members})
            nets = [net_name for _, net_name in ordered]
            if len(nets) < min_group_size or len(nets) > max_group_size:
                continue
            inferred.append(
                {
                    "nets": nets,
                    "maxSkewMm": round(max_skew_mm, 4),
                    "type": "bus_auto",
                    "inferredFrom": {
                        "stem": stem,
                        "interfaces": list(interfaces),
                    },
                }
            )

        return inferred

    def _heal_support_net_connectivity(
        self,
        board: pcbnew.BOARD,
        board_path: Path,
        *,
        report_path: Path,
        max_passes: int = 2,
        max_vias_per_net: int = 4,
    ) -> Dict[str, Any]:
        """Use DRC `unconnected_items` output to stitch support nets into zones."""
        if self.design_rule_commands is None or self.routing_commands is None:
            return {
                "success": False,
                "message": "Support-net healing unavailable",
                "errorDetails": "Missing design_rule_commands or routing_commands",
            }

        zone_layers_by_net: Dict[str, List[str]] = {}
        for zone in self._collect_zones(board):
            net_name = zone.get("net") or ""
            layer = zone.get("layer") or ""
            if not net_name or not layer.endswith(".Cu"):
                continue
            zone_layers_by_net.setdefault(net_name, [])
            if layer not in zone_layers_by_net[net_name]:
                zone_layers_by_net[net_name].append(layer)

        if not zone_layers_by_net:
            return {
                "success": True,
                "message": "No copper zones available for support-net healing",
                "addedVias": [],
                "passes": 0,
            }

        known_vias = self._collect_net_via_positions(board)
        inventory = self._collect_inventory(board)
        added_vias: List[Dict[str, Any]] = []
        added_bridges: List[Dict[str, Any]] = []
        net_via_budget: Dict[str, int] = {}
        attempted_bridges: set[Tuple[str, str, PointMm, PointMm]] = set()

        for pass_index in range(max_passes):
            drc_result = self.design_rule_commands.run_drc({"reportPath": str(report_path)})
            if not drc_result.get("success"):
                return {
                    "success": False,
                    "message": "Support-net healing could not inspect DRC state",
                    "errorDetails": drc_result,
                    "addedVias": added_vias,
                    "passes": pass_index,
                }

            report_file = Path(drc_result.get("reportPath") or report_path)
            if not report_file.exists():
                break

            issues = self._parse_unconnected_item_blocks(
                report_file.read_text(encoding="utf-8", errors="replace")
            )
            stitched_this_pass = 0

            for issue in issues:
                nets = sorted({item["net"] for item in issue.get("items", []) if item.get("net")})
                if len(nets) != 1:
                    continue

                net_name = nets[0]
                if _best_intent(net_name) not in {"GROUND", "POWER_DC"}:
                    continue

                zone_layers = zone_layers_by_net.get(net_name, [])
                if not zone_layers:
                    continue

                candidate_items = [
                    item for item in issue.get("items", [])
                    if item.get("kind") == "Track" and item.get("layer", "").endswith(".Cu")
                ]
                if not candidate_items:
                    continue

                item_layers = {item["layer"] for item in candidate_items}
                if len(candidate_items) >= 2 and len(item_layers) == 1:
                    start_item = candidate_items[0]
                    end_item = candidate_items[1]
                    layer = start_item["layer"]
                    start_point = (start_item["x"], start_item["y"])
                    end_point = (end_item["x"], end_item["y"])
                    bridge_key = (
                        net_name,
                        layer,
                        tuple(round(v, 4) for v in start_point),
                        tuple(round(v, 4) for v in end_point),
                    )
                    if bridge_key not in attempted_bridges:
                        attempted_bridges.add(bridge_key)
                        width_mm = float(
                            inventory.get(net_name, {}).get("min_track_width_mm")
                            or self.routing_commands._get_track_width_mm(None)
                        )
                        bridge_path = self._plan_support_bridge_path(
                            board,
                            layer=layer,
                            net_name=net_name,
                            start_point=start_point,
                            end_point=end_point,
                            width_mm=width_mm,
                        )
                        bridge_payload = {
                            "start": {"x": start_point[0], "y": start_point[1], "unit": "mm"},
                            "end": {"x": end_point[0], "y": end_point[1], "unit": "mm"},
                            "layer": layer,
                            "width": width_mm,
                            "net": net_name,
                        }
                        if bridge_path and len(bridge_path) > 2:
                            bridge_payload["waypoints"] = [
                                {"x": point[0], "y": point[1], "unit": "mm"}
                                for point in bridge_path[1:-1]
                            ]
                        bridge_result = self.routing_commands.route_trace(bridge_payload)
                        bridge_success = bool(bridge_result.get("success"))

                        if bridge_success:
                            added_bridges.append(
                                {
                                    "net": net_name,
                                    "layer": layer,
                                    "start": {"x": round(start_point[0], 4), "y": round(start_point[1], 4)},
                                    "end": {"x": round(end_point[0], 4), "y": round(end_point[1], 4)},
                                    "widthMm": round(width_mm, 4),
                                    "pass": pass_index + 1,
                                    "reason": "same_layer_unconnected_track_bridge",
                                }
                            )
                            stitched_this_pass += 1
                            continue

                known_vias.setdefault(net_name, [])
                for item in candidate_items:
                    if net_via_budget.get(net_name, 0) >= max_vias_per_net:
                        break

                    item_layer = item["layer"]
                    target_layer = next((layer for layer in zone_layers if layer != item_layer), None)
                    if not target_layer:
                        continue

                    point = (item["x"], item["y"])
                    if self._point_near_existing(point, known_vias[net_name]):
                        continue

                    via_result = self.routing_commands.add_via(
                        {
                            "position": {"x": point[0], "y": point[1], "unit": "mm"},
                            "net": net_name,
                            "from_layer": item_layer,
                            "to_layer": target_layer,
                        }
                    )
                    if not via_result.get("success"):
                        continue

                    added_vias.append(
                        {
                            "net": net_name,
                            "x": round(point[0], 4),
                            "y": round(point[1], 4),
                            "fromLayer": item_layer,
                            "toLayer": target_layer,
                            "pass": pass_index + 1,
                            "reason": "support_net_unconnected_items",
                        }
                    )
                    known_vias[net_name].append(point)
                    net_via_budget[net_name] = net_via_budget.get(net_name, 0) + 1
                    stitched_this_pass += 1

            if stitched_this_pass == 0:
                break

            try:
                if hasattr(board, "BuildConnectivity"):
                    board.BuildConnectivity()
            except Exception:
                logger.debug("BuildConnectivity failed during support-net healing", exc_info=True)

            try:
                refill_result = self._refill_zones(board, board_path)
                if not refill_result.get("success"):
                    logger.debug("Zone refill after support-net healing returned no success flag")
            except Exception:
                logger.debug("Zone refill failed during support-net healing", exc_info=True)

            try:
                board.Save(str(board_path))
            except Exception:
                logger.debug("Board save after support-net healing failed", exc_info=True)

        return {
            "success": True,
            "message": (
                f"Added {len(added_bridges)} support-net bridge(s) and "
                f"{len(added_vias)} stitch via(s)"
            ),
            "addedBridges": added_bridges,
            "addedVias": added_vias,
            "passes": max(
                [entry["pass"] for entry in added_vias + added_bridges],
                default=0,
            ),
        }

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
        track_pressure_by_layer = self._track_pressure_by_layer(board)
        edge_pressure_by_layer = self._track_edge_pressure_by_layer(board)
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
                "trackPressureByLayer": {
                    layer: round(value, 4)
                    for layer, value in track_pressure_by_layer.items()
                },
                "edgePressureByLayer": edge_pressure_by_layer,
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
        profiles = list(dict.fromkeys(analysis.get("profiles") or ["generic_2layer"]))
        interfaces = list(dict.fromkeys(analysis.get("interfaces") or []))
        merged_defaults = _profile_merge(profiles, interfaces)
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

        auto_groups = self._infer_auto_matched_length_groups(
            [asdict(intent) for intent in intents],
            interfaces=interfaces,
            default_max_skew_mm=float(merged_defaults["hs_diff_skew_mm"]),
            params=params,
        )
        auto_group_nets = {
            net_name
            for group in auto_groups
            for net_name in group.get("nets", [])
        }
        if auto_group_nets and any(interface in {"DDR4", "DDR5"} for interface in interfaces):
            for intent in intents:
                if intent.net_name in auto_group_nets and intent.intent == "GENERIC":
                    intent.intent = "HS_SINGLE"
                    intent.priority = INTENT_PRIORITY["HS_SINGLE"]
                    intent.metadata["autoBusPromoted"] = True

        intents.sort(key=lambda item: (-item.priority, item.net_name))
        by_intent: Dict[str, List[str]] = {}
        for intent in intents:
            by_intent.setdefault(intent.intent, []).append(intent.net_name)

        return {
            "success": True,
            "boardPath": analysis["boardPath"],
            "profiles": profiles,
            "interfaces": interfaces,
            "backends": analysis.get("backends", {}),
            "intents": [asdict(intent) for intent in intents],
            "byIntent": by_intent,
            "analysisSummary": analysis.get("summary", {}),
            "netInventory": inventory,
            "inferredMatchedLengthGroups": auto_groups,
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
        analysis_summary = intents_result.get("analysisSummary", {})
        reference_planning = self._synthesize_reference_planning(
            by_intent=by_intent,
            intents=intents,
            inventory=inventory,
            analysis_summary=analysis_summary,
        )
        seed = int(params.get("seed", 42))
        if "excludeFromFreeRouting" in params and params.get("excludeFromFreeRouting") is not None:
            exclude_candidates = params.get("excludeFromFreeRouting") or []
        else:
            exclude_candidates = (
                by_intent.get("GROUND", [])
                + by_intent.get("POWER_DC", [])
                + by_intent.get("POWER_SWITCHING", [])
            )
        exclude_from_freerouting = list(dict.fromkeys(exclude_candidates))

        # --- Power trace width: use IPC-2221 if current estimate available ---
        power_target_width_mm = float(merged_defaults["power_min_width_mm"])
        power_current_a = float(params.get("powerCurrentA", 0))
        copper_oz = float(params.get("copperOz", 1.0))
        temp_rise_c = float(params.get("tempRiseC", 10.0))
        if power_current_a > 0:
            ipc_width = ipc2221_trace_width_mm(
                power_current_a, temp_rise_c, copper_oz, is_external=True
            )
            power_target_width_mm = max(power_target_width_mm, ipc_width)
            logger.info(
                f"IPC-2221: {power_current_a}A @ {temp_rise_c}°C rise → "
                f"min width {ipc_width}mm (using {power_target_width_mm}mm)"
            )

        observed_power_widths = [
            float(inventory[net]["min_track_width_mm"])
            for net in by_intent.get("POWER_DC", [])
            if net in inventory and inventory[net].get("min_track_width_mm") is not None
        ]
        power_rule_min_width_mm = power_target_width_mm
        if observed_power_widths:
            power_rule_min_width_mm = min(power_target_width_mm, min(observed_power_widths))

        compiled_rules: List[Dict[str, Any]] = []
        coupled_hs_diff_nets: List[str] = []
        diff_skew_condition = _condition_for_nets(by_intent.get("HS_DIFF", []))
        width_for_coupling = float(params.get("criticalWidthMm") or 0.25)
        target_center_spacing = width_for_coupling + float(merged_defaults["hs_diff_gap_mm"]["opt"])
        tolerance_mm = max(0.12, width_for_coupling * 0.75)
        seen_diff_pairs: set[Tuple[str, str]] = set()
        for intent_item in intents:
            if intent_item.get("intent") != "HS_DIFF" or not intent_item.get("diff_partner"):
                continue
            pair = tuple(sorted((intent_item["net_name"], intent_item["diff_partner"])))
            if pair in seen_diff_pairs:
                continue
            seen_diff_pairs.add(pair)
            if self._diff_pair_is_coupling_eligible(
                pair[0],
                pair[1],
                inventory,
                target_center_spacing=target_center_spacing,
                tolerance_mm=tolerance_mm,
            ):
                coupled_hs_diff_nets.extend(pair)

        hs_diff_condition = _condition_for_nets(sorted(dict.fromkeys(coupled_hs_diff_nets)))
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
                ]
            )
        if diff_skew_condition:
            compiled_rules.append(
                {
                    "name": "cfha_hs_diff_skew",
                    "condition": diff_skew_condition,
                    "constraint": "skew",
                    "max": merged_defaults["hs_diff_skew_mm"],
                }
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

        rf_condition = _condition_for_nets(by_intent.get("RF", []))
        if rf_condition:
            compiled_rules.append(
                {
                    "name": "cfha_rf_via_limit",
                    "condition": rf_condition,
                    "constraint": "via_count",
                    "max": merged_defaults["rf_via_limit"],
                    "metadata": {"reason": "RF nets should minimize discontinuities and reference-plane breaks"},
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

        # --- Length matching for high-speed nets ---
        # Reference: Mustafa Ozdal & Wong (2006) — Lagrangian min-max length
        # Reference: Lin et al. (2021a) — concurrent hierarchical wire snaking
        hs_single_condition = _condition_for_nets(by_intent.get("HS_SINGLE", []))
        max_length_mm = float(params.get("maxLengthMm", 0))
        if max_length_mm > 0 and hs_single_condition:
            compiled_rules.append(
                {
                    "name": "cfha_hs_max_length",
                    "condition": hs_single_condition,
                    "constraint": "length",
                    "max": max_length_mm,
                    "metadata": {"reason": "HS single-ended length ceiling"},
                }
            )

        # Matched-length groups: diff pairs auto-detected from intent partners
        matched_group_map: Dict[Tuple[str, ...], Dict[str, Any]] = {}
        matched_group_order: List[Tuple[str, ...]] = []

        def _upsert_matched_group(group: Dict[str, Any], *, replace: bool) -> None:
            nets = tuple(sorted(dict.fromkeys(group.get("nets", []) or [])))
            if len(nets) < 2:
                return
            raw_max_skew = group.get("maxSkewMm")
            normalized = {
                "nets": list(nets),
                "maxSkewMm": (
                    max(0.0, float(raw_max_skew))
                    if raw_max_skew is not None
                    else float(merged_defaults["hs_diff_skew_mm"])
                ),
                "type": group.get("type", "bus"),
            }
            if "inferredFrom" in group:
                normalized["inferredFrom"] = group["inferredFrom"]
            if nets not in matched_group_map:
                matched_group_order.append(nets)
                matched_group_map[nets] = normalized
            elif replace:
                matched_group_map[nets] = normalized

        seen_pairs: set = set()
        for intent_item in intents:
            if intent_item.get("intent") == "HS_DIFF" and intent_item.get("diff_partner"):
                a_name = intent_item["net_name"]
                b_name = intent_item["diff_partner"]
                pair_key = tuple(sorted((a_name, b_name)))
                if pair_key not in seen_pairs:
                    seen_pairs.add(pair_key)
                    _upsert_matched_group(
                        {
                            "nets": list(pair_key),
                            "maxSkewMm": merged_defaults["hs_diff_skew_mm"],
                            "type": "diff_pair",
                        },
                        replace=False,
                    )

        for group in (
            intents_result.get("inferredMatchedLengthGroups")
            or self._infer_auto_matched_length_groups(
                intents,
                interfaces=interfaces,
                default_max_skew_mm=float(merged_defaults["hs_diff_skew_mm"]),
                params=params,
            )
        ):
            _upsert_matched_group(group, replace=False)

        # User-supplied matched-length groups (e.g. DDR data bus)
        for group in params.get("matchedLengthGroups", []):
            raw_max_skew = group.get("maxSkewMm")
            _upsert_matched_group(
                {
                    "nets": group.get("nets", []),
                    "maxSkewMm": float(raw_max_skew) if raw_max_skew is not None else 0.5,
                    "type": group.get("type", "bus"),
                },
                replace=True,
            )
        matched_groups = [matched_group_map[key] for key in matched_group_order]

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

        # --- Crosstalk guard spacing ---
        # HS nets need guard spacing from other signal nets to prevent crosstalk.
        # Rule: 3x trace width is the industry-standard minimum; we use the
        # profile-specific guard value which already accounts for stackup.
        # Reference: IPC-2141A Section 5.3 — crosstalk coupling.
        hs_all_nets = by_intent.get("HS_DIFF", []) + by_intent.get("HS_SINGLE", [])
        crosstalk_guard = float(merged_defaults.get("crosstalk_guard_mm", 0.4))
        if hs_all_nets and crosstalk_guard > 0:
            hs_condition = _clearance_condition_for_nets(
                hs_all_nets,
                exclude_nets=hs_all_nets + by_intent.get("GROUND", []),
            )
            if hs_condition:
                compiled_rules.append({
                    "name": "cfha_crosstalk_guard",
                    "condition": hs_condition,
                    "constraint": "clearance",
                    "min": crosstalk_guard,
                    "metadata": {"reason": "Crosstalk guard spacing (IPC-2141A)"},
                })

        # --- Analog/RF isolation ---
        # Analog-sensitive and RF nets need extra clearance from digital signals.
        # Reference: Henry Ott "Electromagnetic Compatibility Engineering" Ch 18.
        analog_guard = float(merged_defaults.get("analog_guard_mm", 1.0))
        analog_condition = _clearance_condition_for_nets(
            by_intent.get("ANALOG_SENSITIVE", []),
            exclude_nets=by_intent.get("ANALOG_SENSITIVE", []) + by_intent.get("GROUND", []),
        )
        if analog_condition and analog_guard > 0:
            compiled_rules.append({
                "name": "cfha_analog_isolation",
                "condition": analog_condition,
                "constraint": "clearance",
                "min": analog_guard,
                "metadata": {"reason": "Analog isolation from noisy digital or switching nets"},
            })

        rf_guard = float(merged_defaults.get("rf_guard_mm", analog_guard))
        if rf_condition and rf_guard > 0:
            compiled_rules.append({
                "name": "cfha_rf_clearance",
                "condition": _clearance_condition_for_nets(
                    by_intent.get("RF", []),
                    exclude_nets=by_intent.get("RF", []) + by_intent.get("GROUND", []),
                ),
                "constraint": "clearance",
                "min": rf_guard,
                "metadata": {"reason": "RF keepout / guard corridor to limit coupling and impedance discontinuities"},
            })

        # --- Power switching noise isolation ---
        # Switching power nets (LX, PHASE, BST) should be kept away from
        # sensitive analog/RF traces.
        switching_nets = by_intent.get("POWER_SWITCHING", [])
        if switching_nets:
            switching_condition = _clearance_condition_for_nets(
                switching_nets,
                exclude_nets=(
                    switching_nets
                    + by_intent.get("GROUND", [])
                    + by_intent.get("POWER_DC", [])
                ),
            )
            if switching_condition:
                compiled_rules.append({
                    "name": "cfha_switching_isolation",
                    "condition": switching_condition,
                    "constraint": "clearance",
                    "min": max(analog_guard, rf_guard, 1.5),
                    "metadata": {"reason": "Switching noise isolation from sensitive nets"},
                })

        constraints = {
            "schemaVersion": 1,
            "generatedAt": _utc_now(),
            "seed": seed,
            "boardPath": str(board_path),
            "profiles": profiles,
            "interfaces": interfaces,
            "stackup": {
                "copperLayers": analysis_summary.get("copperLayers", []),
                "layerCount": len(analysis_summary.get("copperLayers", [])),
            },
            "boardSummary": analysis_summary,
            "intents": intents,
            "intentGroups": by_intent,
            "defaults": merged_defaults,
            "derived": {
                "powerTargetWidthMm": round(power_target_width_mm, 4),
                "powerRuleMinWidthMm": round(power_rule_min_width_mm, 4),
                "observedPowerMinWidthMm": round(min(observed_power_widths), 4)
                if observed_power_widths
                else None,
                "ipc2221": {
                    "currentA": power_current_a,
                    "copperOz": copper_oz,
                    "tempRiseC": temp_rise_c,
                    "calculatedWidthMm": round(
                        ipc2221_trace_width_mm(power_current_a, temp_rise_c, copper_oz), 4
                    ) if power_current_a > 0 else None,
                },
            },
            "referencePlanning": reference_planning,
            "matchedLengthGroups": matched_groups,
            "compiledRules": compiled_rules,
            "excludeFromFreeRouting": exclude_from_freerouting,
            "criticalClasses": params.get(
                "criticalClasses",
                ["RF", "HS_DIFF", "HS_SINGLE", "POWER_SWITCHING", "ANALOG_SENSITIVE"],
            ),
            "policy": {
                "criticalOrdering": [
                    "intent_priority",
                    "escape_complexity",
                    "breakout_pressure",
                    "reference_alignment",
                    "local_congestion",
                ],
                "placementCoupling": {
                    "expectEdgeConnectors": True,
                    "expectLocalDecoupling": True,
                    "reserveConnectorBreakouts": True,
                    "preferReferenceContinuity": True,
                    "avoidSplitReferenceLayers": bool(reference_planning.get("splitRiskLayers")),
                    "preferredReferenceLayer": reference_planning.get("preferredZoneLayer"),
                    "preferredSignalLayer": reference_planning.get("preferredSignalLayer"),
                },
                "compiledRuleFamilies": [rule["name"] for rule in compiled_rules],
            },
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

    def _estimate_net_congestion(
        self,
        pads: List[Dict[str, Any]],
        board: pcbnew.BOARD,
    ) -> float:
        """Estimate routing congestion for a net based on pad density.

        Nets in congested regions should be routed earlier to secure channels.
        Congestion = number of nearby pads from other nets within 3mm radius.

        Reference: Rubin (1974) congestion-driven ordering; modern EDA tools
        use similar heuristics for net ordering in sequential routers.
        """
        if not pads:
            return 0.0
        radius_mm = 3.0
        total_nearby = 0
        pad_positions = [(float(p["x"]), float(p["y"])) for p in pads]
        for fp in board.GetFootprints():
            for pad in fp.Pads():
                pos = pad.GetPosition()
                px = pos.x / 1_000_000
                py = pos.y / 1_000_000
                for cx, cy in pad_positions:
                    if math.hypot(px - cx, py - cy) < radius_mm:
                        total_nearby += 1
                        break
        return float(total_nearby)

    def _estimate_escape_complexity(
        self,
        net_name: str,
        pads: List[Dict[str, Any]],
        footprints: Dict[str, Any],
    ) -> float:
        """Estimate how urgently a net should reserve escape channels.

        Ordered-escape routing literature consistently prioritizes dense pin
        arrays, differential pairs, and blockage-sensitive connector breakouts.
        This heuristic collapses those signals into a single ordering term so
        critical nets that are hardest to escape are routed before easier nets.
        """
        if len(pads) < 2:
            return 0.0

        unique_refs = sorted({pad["ref"] for pad in pads})
        score = 0.0
        for ref in unique_refs:
            footprint = footprints.get(ref)
            if footprint is None:
                continue
            try:
                pad_count = sum(1 for _ in footprint.Pads())
            except Exception:
                pad_count = 0

            score += min(pad_count, 64) / 8.0
            ref_upper = ref.upper()
            if ref_upper.startswith(("J", "P", "X")):
                score += 2.0
            if pad_count >= 16:
                score += 2.0
            if pad_count >= 48:
                score += 2.0

        if _diff_partner_name(net_name):
            score += 2.5
        if len(unique_refs) > 2:
            score += (len(unique_refs) - 2) * 1.5
        if _best_intent(net_name) in {"HS_DIFF", "HS_SINGLE", "RF"}:
            score += 1.0
        return round(score, 4)

    def _estimate_breakout_pressure(
        self,
        net_name: str,
        pads: List[Dict[str, Any]],
        board: pcbnew.BOARD,
        footprints: Dict[str, Any],
    ) -> float:
        """Estimate how strongly a net should reserve breakout resources early."""
        if len(pads) < 2:
            return 0.0

        bounds = self._board_bounds_mm(board)

        pads_by_ref: Dict[str, List[Dict[str, Any]]] = {}
        for pad in pads:
            pads_by_ref.setdefault(pad["ref"], []).append(pad)

        score = 0.0
        for ref, ref_pads in pads_by_ref.items():
            footprint = footprints.get(ref)
            try:
                pad_count = sum(1 for _ in footprint.Pads()) if footprint is not None else 0
            except Exception:
                pad_count = 0

            ref_upper = ref.upper()
            if ref_upper.startswith(("J", "P", "X")):
                score += 2.5 + min(pad_count, 40) / 12.0
            elif pad_count >= 24:
                score += 2.0
            elif pad_count >= 12:
                score += 1.0

            if bounds is not None:
                left, top, right, bottom = bounds
                edge_distance = min(
                    min(float(pad["x"]) - left, right - float(pad["x"])) for pad in ref_pads
                )
                edge_distance = min(
                    edge_distance,
                    min(
                        min(float(pad["y"]) - top, bottom - float(pad["y"])) for pad in ref_pads
                    ),
                )
                if edge_distance <= 2.0:
                    score += 1.5
                elif edge_distance <= 5.0:
                    score += 0.75

        if _diff_partner_name(net_name):
            score += 1.5
        if len(pads_by_ref) > 2:
            score += (len(pads_by_ref) - 2) * 0.75
        if _best_intent(net_name) in {"HS_DIFF", "HS_SINGLE", "RF"}:
            score += 0.5
        return round(score, 4)

    def _estimate_reference_alignment_pressure(
        self,
        net_name: str,
        pads: List[Dict[str, Any]],
        board: pcbnew.BOARD,
        reference_planning: Dict[str, Any],
    ) -> float:
        """Favor edge-near nets that match the selected reference continuity side."""
        preferred_edge = str(reference_planning.get("preferredEntryEdge") or "")
        if preferred_edge not in {"left", "right"} or len(pads) < 2:
            return 0.0

        high_speed_nets = {
            str(name)
            for name in reference_planning.get("highSpeedNets", []) or []
            if name
        }
        if high_speed_nets and net_name not in high_speed_nets and _diff_partner_name(net_name) not in high_speed_nets:
            return 0.0

        bounds = self._board_bounds_mm(board)
        if bounds is None:
            return 0.0
        left, _, right, _ = bounds

        try:
            edge_distance = min(
                (float(pad["x"]) - left) if preferred_edge == "left" else (right - float(pad["x"]))
                for pad in pads
                if pad.get("x") is not None
            )
        except (TypeError, ValueError):
            return 0.0

        if edge_distance <= 2.0:
            proximity = 2.0
        elif edge_distance <= 5.0:
            proximity = 1.25
        elif edge_distance <= 10.0:
            proximity = 0.5
        else:
            proximity = 0.0
        if proximity <= 0.0:
            return 0.0

        continuity_score = float(reference_planning.get("referenceContinuityScore") or 0.0)
        source = str(reference_planning.get("topologyCueSource") or "")
        source_bonus = 0.25 if source == "zone_affinity" else 0.0
        score = proximity * (0.6 + continuity_score + source_bonus)
        return round(score, 4)

    def _net_side_topology(
        self,
        pads: List[Dict[str, Any]],
        board: pcbnew.BOARD,
    ) -> Dict[str, Any]:
        bounds = self._board_bounds_mm(board)
        if bounds is None:
            return {"bucket": "center", "edgeBias": 0.0, "centroidXmm": None}

        points: List[PointMm] = []
        for pad in pads:
            try:
                points.append((float(pad["x"]), float(pad["y"])))
            except (TypeError, ValueError, KeyError):
                continue
        centroid = self._point_centroid(points)
        if centroid is None:
            return {"bucket": "center", "edgeBias": 0.0, "centroidXmm": None}

        left, _, right, _ = bounds
        width = max(right - left, 1e-6)
        relative_x = (centroid[0] - left) / width
        if relative_x <= 0.33:
            bucket = "left"
        elif relative_x >= 0.67:
            bucket = "right"
        else:
            bucket = "center"
        edge_bias = max(-1.0, min(1.0, ((centroid[0] - ((left + right) / 2.0)) / (width / 2.0))))
        return {
            "bucket": bucket,
            "edgeBias": round(edge_bias, 4),
            "centroidXmm": round(centroid[0], 4),
        }

    def _select_critical_route_layer(
        self,
        *,
        intent: Dict[str, Any],
        pads: List[Dict[str, Any]],
        board: pcbnew.BOARD,
        reference_planning: Dict[str, Any],
        board_summary: Dict[str, Any],
        default_layer: Optional[str],
        forced_layer: Optional[str],
        footprints: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if forced_layer:
            return {
                "layer": str(forced_layer),
                "source": "user",
                "bucket": "forced",
                "centroidXmm": None,
                "candidates": [],
            }

        sensitive_intents = {"HS_DIFF", "HS_SINGLE", "RF"}
        intent_name = str(intent.get("intent") or "")
        if intent_name not in sensitive_intents:
            return {
                "layer": default_layer,
                "source": "critical_default",
                "bucket": "nonsensitive",
                "centroidXmm": None,
                "candidates": [],
            }

        signal_candidates = list(reference_planning.get("signalLayerCandidates") or [])
        if not signal_candidates:
            fallback_layer = default_layer or reference_planning.get("preferredSignalLayer")
            return {
                "layer": fallback_layer,
                "source": "referencePlanning",
                "bucket": "fallback",
                "centroidXmm": None,
                "candidates": [],
            }

        side_info = self._net_side_topology(pads, board)
        bucket = str(side_info.get("bucket") or "center")
        preferred_edge = str(reference_planning.get("preferredEntryEdge") or "")
        continuity_score = float(reference_planning.get("referenceContinuityScore") or 0.0)
        edge_pressure_by_layer = dict(board_summary.get("edgePressureByLayer", {}) or {})
        track_pressure_by_layer = dict(board_summary.get("trackPressureByLayer", {}) or {})
        footprints = footprints or {}
        endpoint_layers: Dict[str, int] = {}
        endpoint_layers_per_pad: List[str] = []
        for ref in {str(pad.get("ref") or "") for pad in pads if pad.get("ref")}:
            footprint = footprints.get(ref)
            if footprint is None:
                continue
            try:
                layer_name = board.GetLayerName(footprint.GetLayer())
            except Exception:
                continue
            if layer_name:
                endpoint_layers[layer_name] = endpoint_layers.get(layer_name, 0) + 1
        for pad in pads:
            ref = str(pad.get("ref") or "")
            if not ref:
                continue
            footprint = footprints.get(ref)
            if footprint is None:
                continue
            try:
                layer_name = board.GetLayerName(footprint.GetLayer())
            except Exception:
                continue
            if layer_name:
                endpoint_layers_per_pad.append(layer_name)

        ranked_candidates: List[Dict[str, Any]] = []
        for index, candidate in enumerate(signal_candidates):
            layer = str(candidate.get("layer") or "")
            if not layer:
                continue
            layer_edge_profile = dict(edge_pressure_by_layer.get(layer, {}) or {})
            total_pressure = float(
                track_pressure_by_layer.get(
                    layer,
                    candidate.get("totalPressure", 0.0),
                ) or 0.0
            )
            bucket_pressure = float(
                layer_edge_profile.get(
                    bucket,
                    candidate.get("edgePressure", total_pressure),
                ) or total_pressure
            )
            if bucket == preferred_edge:
                weighted_pressure = bucket_pressure * (1.0 + continuity_score)
            elif bucket == "center":
                weighted_pressure = total_pressure * (1.0 + continuity_score * 0.2)
            else:
                weighted_pressure = bucket_pressure

            via_transition_penalty = 0.0
            estimated_via_count_total = 0
            estimated_via_count_per_net = 0.0
            transition_required = False
            if endpoint_layers_per_pad:
                estimated_via_count_total = sum(
                    1 for endpoint_layer in endpoint_layers_per_pad if endpoint_layer != layer
                )
                transition_required = estimated_via_count_total > 0
                if intent_name == "HS_DIFF" and str(intent.get("diff_partner") or ""):
                    estimated_via_count_per_net = estimated_via_count_total / 2.0
                else:
                    estimated_via_count_per_net = float(estimated_via_count_total)
            if endpoint_layers:
                mismatch_refs = sum(
                    count for endpoint_layer, count in endpoint_layers.items() if endpoint_layer != layer
                )
                if layer.startswith("In"):
                    via_transition_penalty = mismatch_refs * 12.0
                else:
                    via_transition_penalty = mismatch_refs * 6.0

            ranked_candidates.append(
                {
                    "layer": layer,
                    "splitRisk": bool(candidate.get("splitRisk")),
                    "adjacencyRank": int(candidate.get("adjacencyRank", index)),
                    "bucket": bucket,
                    "bucketPressure": round(bucket_pressure, 4),
                    "weightedPressure": round(weighted_pressure, 4),
                    "viaTransitionPenalty": round(via_transition_penalty, 4),
                    "estimatedViaCountTotal": int(estimated_via_count_total),
                    "estimatedViaCountPerNet": round(estimated_via_count_per_net, 4),
                    "transitionRequired": bool(transition_required),
                    "totalPressure": round(total_pressure, 4),
                    "candidateRank": index,
                }
            )

        if not ranked_candidates:
            fallback_layer = default_layer or reference_planning.get("preferredSignalLayer")
            return {
                "layer": fallback_layer,
                "source": "referencePlanning",
                "bucket": bucket,
                "centroidXmm": side_info.get("centroidXmm"),
                "candidates": [],
            }

        ranked_candidates.sort(
            key=lambda item: (
                1 if item["splitRisk"] else 0,
                int(item["adjacencyRank"]),
                float(item["viaTransitionPenalty"]),
                float(item["weightedPressure"]),
                float(item["totalPressure"]),
                int(item["candidateRank"]),
                item["layer"],
            )
        )
        best = ranked_candidates[0]
        return {
            "layer": best["layer"],
            "source": "per_net_reference",
            "bucket": bucket,
            "centroidXmm": side_info.get("centroidXmm"),
            "candidates": ranked_candidates,
        }

    def _select_locked_diff_pair_route_layer(
        self,
        *,
        intent: Dict[str, Any],
        partner_intent: Optional[Dict[str, Any]],
        inventory: Dict[str, Any],
        board: pcbnew.BOARD,
        reference_planning: Dict[str, Any],
        board_summary: Dict[str, Any],
        default_layer: Optional[str],
        forced_layer: Optional[str],
        footprints: Optional[Dict[str, Any]] = None,
        via_limit: Optional[int] = None,
    ) -> Dict[str, Any]:
        partner_name = str(intent.get("diff_partner") or "")
        merged_pads = list(inventory.get(intent["net_name"], {}).get("pads", []) or [])
        if partner_name:
            merged_pads.extend(list(inventory.get(partner_name, {}).get("pads", []) or []))
        merged_intent = {
            "intent": "HS_DIFF",
            "net_name": intent.get("net_name"),
            "diff_partner": partner_name,
        }
        decision = self._select_critical_route_layer(
            intent=merged_intent,
            pads=merged_pads,
            board=board,
            reference_planning=reference_planning,
            board_summary=board_summary,
            default_layer=default_layer,
            forced_layer=forced_layer,
            footprints=footprints,
        )
        candidates = list(decision.get("candidates") or [])
        transition_policy = "unknown_endpoint_layers"
        if candidates:
            zero_transition_candidates = [
                candidate
                for candidate in candidates
                if float(candidate.get("estimatedViaCountPerNet", 0.0)) <= 0.0
            ]
            if zero_transition_candidates:
                selected = zero_transition_candidates[0]
                decision["layer"] = selected["layer"]
                transition_policy = "stay_on_endpoint_layer"
            else:
                budget_safe_candidates = [
                    candidate
                    for candidate in candidates
                    if via_limit is None
                    or float(candidate.get("estimatedViaCountPerNet", 0.0)) <= float(via_limit)
                ]
                selected = budget_safe_candidates[0] if budget_safe_candidates else candidates[0]
                decision["layer"] = selected["layer"]
                estimated_per_net = float(selected.get("estimatedViaCountPerNet", 0.0))
                if via_limit is not None and estimated_per_net > float(via_limit):
                    transition_policy = "transitions_over_budget"
                else:
                    transition_policy = "paired_transitions_required"
            decision["viaBudget"] = via_limit
            decision["estimatedViaCountTotal"] = int(selected.get("estimatedViaCountTotal", 0))
            decision["estimatedViaCountPerNet"] = round(float(selected.get("estimatedViaCountPerNet", 0.0)), 4)
            decision["transitionPolicy"] = transition_policy
        if decision.get("source") == "per_net_reference":
            decision["source"] = "diff_pair_locked"
        return decision

    def _route_multi_pin_net(
        self,
        pads: List[Dict[str, Any]],
        layer: str,
        width_mm: float,
        net_name: str,
        footprints: Dict[str, Any],
        applier: "HybridRouteApplier",
    ) -> Dict[str, Any]:
        """Route a multi-pin net (>2 pads) using MST decomposition.

        Algorithm:
          1. Build MST over pad positions using Prim's algorithm.
          2. Route each MST edge as a 2-pin sub-problem.
          3. Use plan_steiner_tree from orthogonal_router when all pads
             are on the same layer (fast path).
          4. Fall back to sequential pad-to-pad routing otherwise.

        Reference: Kahng & Robins (1992) — iterative Steiner tree heuristics.
        """
        from commands.orthogonal_router import plan_steiner_tree

        # Check if all pads are on the same layer
        pad_layers = set()
        for p in pads:
            ref = p["ref"]
            if ref in footprints:
                fp = footprints[ref]
                pad_layers.add(fp.GetLayer())

        terminals = [(float(p["x"]), float(p["y"])) for p in pads]

        if len(pad_layers) == 1:
            # All on same layer — use Steiner tree planner
            obstacles = self.routing_commands._collect_routing_obstacles(
                layer,
                self.routing_commands._get_clearance_mm() + width_mm / 2,
                ignored_refs=[p["ref"] for p in pads],
                net=net_name,
            )
            tree_paths = plan_steiner_tree(
                terminals, obstacles,
                bend_penalty=max(width_mm * 2, 1.0),
                pad_repulsion=1.0,
                pad_centers=self._collect_all_pad_centers(),
            )
            if tree_paths:
                segment_count = 0
                for path in tree_paths:
                    res = applier.route_path(
                        path, layer=layer, width_mm=width_mm, net_name=net_name,
                    )
                    if res.get("success"):
                        segment_count += 1
                return {
                    "success": segment_count > 0,
                    "message": f"Steiner tree: routed {segment_count}/{len(tree_paths)} edges",
                    "backend": "steiner_tree",
                    "edgesRouted": segment_count,
                    "edgesTotal": len(tree_paths),
                }

        # Fallback: sequential pad-to-pad routing via MST order
        n = len(pads)
        in_tree = [False] * n
        min_edge: List[Tuple[float, int]] = [(float("inf"), -1)] * n
        min_edge[0] = (0.0, -1)
        mst_edges: List[Tuple[int, int]] = []

        for _ in range(n):
            u = -1
            for v in range(n):
                if not in_tree[v] and (u == -1 or min_edge[v][0] < min_edge[u][0]):
                    u = v
            if u == -1:
                break
            in_tree[u] = True
            parent = min_edge[u][1]
            if parent >= 0:
                mst_edges.append((parent, u))
            for v in range(n):
                if not in_tree[v]:
                    dist = _distance_mm(terminals[u], terminals[v])
                    if dist < min_edge[v][0]:
                        min_edge[v] = (dist, u)

        routed_edges = 0
        for u, v in mst_edges:
            result = self.routing_commands.route_pad_to_pad({
                "fromRef": pads[u]["ref"],
                "fromPad": pads[u]["pad"],
                "toRef": pads[v]["ref"],
                "toPad": pads[v]["pad"],
                "layer": layer,
                "width": width_mm,
                "net": net_name,
            })
            if result.get("success"):
                routed_edges += 1

        return {
            "success": routed_edges > 0,
            "message": f"MST decomposition: routed {routed_edges}/{len(mst_edges)} edges",
            "backend": "mst_decomposition",
            "edgesRouted": routed_edges,
            "edgesTotal": len(mst_edges),
        }

    def _collect_all_pad_centers(self) -> List[PointMm]:
        """Collect all pad centers on the board for pad-repulsion heuristic."""
        if not self.board:
            return []
        centers: List[PointMm] = []
        for fp in self.board.GetFootprints():
            for pad in fp.Pads():
                pos = pad.GetPosition()
                centers.append((pos.x / 1_000_000, pos.y / 1_000_000))
        return centers

    @staticmethod
    def _path_is_orthogonal(path_points: Sequence[PointMm]) -> bool:
        if len(path_points) < 2:
            return False
        for start, end in zip(path_points, path_points[1:]):
            if not (math.isclose(start[0], end[0], abs_tol=1e-6) or math.isclose(start[1], end[1], abs_tol=1e-6)):
                return False
        return True

    def _diff_pair_sites(
        self,
        net_a: str,
        net_b: str,
        inventory: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """Group the two nets' pads by shared footprint reference."""
        site_map: Dict[str, Dict[str, Any]] = {}
        for net_name in (net_a, net_b):
            for pad in inventory.get(net_name, {}).get("pads", []):
                site = site_map.setdefault(
                    pad["ref"],
                    {"ref": pad["ref"], "pads": {}, "avgX": 0.0, "avgY": 0.0},
                )
                site["pads"][net_name] = pad

        valid_sites: List[Dict[str, Any]] = []
        for site in site_map.values():
            if net_a not in site["pads"] or net_b not in site["pads"]:
                continue
            pad_a = site["pads"][net_a]
            pad_b = site["pads"][net_b]
            site["avgX"] = (float(pad_a["x"]) + float(pad_b["x"])) / 2.0
            site["avgY"] = (float(pad_a["y"]) + float(pad_b["y"])) / 2.0
            valid_sites.append(site)

        valid_sites.sort(key=lambda item: (item["avgX"], item["avgY"], item["ref"]))
        return valid_sites

    def _diff_pair_is_coupling_eligible(
        self,
        net_a: str,
        net_b: str,
        inventory: Dict[str, Any],
        *,
        target_center_spacing: float,
        tolerance_mm: float,
    ) -> bool:
        """Return True when the endpoint geometry supports coupled diff-pair rules."""
        sites = self._diff_pair_sites(net_a, net_b, inventory)
        if len(sites) != 2:
            return False

        separations: List[float] = []
        for site in sites:
            pad_a = site["pads"][net_a]
            pad_b = site["pads"][net_b]
            separations.append(
                _distance_mm(
                    (float(pad_a["x"]), float(pad_a["y"])),
                    (float(pad_b["x"]), float(pad_b["y"])),
                )
            )

        return all(
            abs(separation - target_center_spacing) <= tolerance_mm
            for separation in separations
        )

    def _route_diff_pair(
        self,
        net_pos: str,
        net_neg: str,
        *,
        inventory: Dict[str, Any],
        constraints: Dict[str, Any],
        width_mm: float,
        layer: str,
        board: Optional[pcbnew.BOARD] = None,
        footprints: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Route a coupled diff pair when both endpoints already match the target pitch."""
        if self.routing_commands is None:
            return {"success": False, "message": "Routing commands unavailable"}

        sites = self._diff_pair_sites(net_pos, net_neg, inventory)
        if len(sites) != 2:
            return {
                "success": False,
                "message": "Diff pair routing requires exactly two shared endpoints",
                "errorDetails": f"Found {len(sites)} shared endpoint sites for {net_pos}/{net_neg}",
            }

        start_site, end_site = sites
        start_pos_pad = start_site["pads"][net_pos]
        start_neg_pad = start_site["pads"][net_neg]
        end_pos_pad = end_site["pads"][net_pos]
        end_neg_pad = end_site["pads"][net_neg]

        start_sep = _distance_mm(
            (float(start_pos_pad["x"]), float(start_pos_pad["y"])),
            (float(start_neg_pad["x"]), float(start_neg_pad["y"])),
        )
        end_sep = _distance_mm(
            (float(end_pos_pad["x"]), float(end_pos_pad["y"])),
            (float(end_neg_pad["x"]), float(end_neg_pad["y"])),
        )
        target_gap = float(constraints.get("defaults", {}).get("hs_diff_gap_mm", {}).get("opt", 0.2))
        target_center_spacing = round(width_mm + target_gap, 4)
        tolerance = max(0.12, width_mm * 0.75)
        if abs(start_sep - target_center_spacing) > tolerance or abs(end_sep - target_center_spacing) > tolerance:
            return {
                "success": False,
                "message": "Endpoint pad pitch does not match coupled diff-pair pitch",
                "errorDetails": {
                    "startSeparationMm": round(start_sep, 4),
                    "endSeparationMm": round(end_sep, 4),
                    "targetCenterSpacingMm": target_center_spacing,
                    "toleranceMm": round(tolerance, 4),
                },
            }

        board = board or self.board
        footprints = footprints or {}
        start_layer = layer
        end_layer = layer
        if board is not None:
            try:
                start_layer = str(board.GetLayerName(footprints[start_site["ref"]].GetLayer()) or layer)
            except Exception:
                start_layer = layer
            try:
                end_layer = str(board.GetLayerName(footprints[end_site["ref"]].GetLayer()) or layer)
            except Exception:
                end_layer = layer

        start_mid = {
            "x": round(start_site["avgX"], 6),
            "y": round(start_site["avgY"], 6),
            "unit": "mm",
        }
        end_mid = {
            "x": round(end_site["avgX"], 6),
            "y": round(end_site["avgY"], 6),
            "unit": "mm",
        }
        max_skew_mm = float(constraints.get("defaults", {}).get("hs_diff_skew_mm", 0.25))
        reference_net = constraints.get("referencePlanning", {}).get("groundNet")
        return self.routing_commands.route_differential_pair(
            {
                "startPos": start_mid,
                "endPos": end_mid,
                "startPosPos": {
                    "x": round(float(start_pos_pad["x"]), 6),
                    "y": round(float(start_pos_pad["y"]), 6),
                    "unit": "mm",
                },
                "startPosNeg": {
                    "x": round(float(start_neg_pad["x"]), 6),
                    "y": round(float(start_neg_pad["y"]), 6),
                    "unit": "mm",
                },
                "endPosPos": {
                    "x": round(float(end_pos_pad["x"]), 6),
                    "y": round(float(end_pos_pad["y"]), 6),
                    "unit": "mm",
                },
                "endPosNeg": {
                    "x": round(float(end_neg_pad["x"]), 6),
                    "y": round(float(end_neg_pad["y"]), 6),
                    "unit": "mm",
                },
                "netPos": net_pos,
                "netNeg": net_neg,
                "layer": layer,
                "startLayer": start_layer,
                "endLayer": end_layer,
                "startRef": start_site["ref"],
                "endRef": end_site["ref"],
                "width": width_mm,
                "gap": target_center_spacing,
                "maxSkewMm": max_skew_mm,
                "allowLayerTransitions": True,
                "referenceNet": reference_net,
                "addReturnPathStitching": bool(reference_net),
            }
        )

    def route_critical_nets(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Route critical nets with multi-pin support and congestion-aware ordering.

        Improvements over basic sequential routing:
          - **Multi-pin net support**: Nets with >2 pads are decomposed via MST
            and routed using Steiner tree heuristics (Kahng & Robins 1992).
          - **Escape-aware ordering**: Nets attached to dense connectors and
            pin arrays route before easy nets so breakout channels are reserved
            while the board is still open (Jiao & Dong 2018).
          - **Congestion-aware ordering**: Within each priority tier, nets in
            congested regions are routed first to secure channels (Rubin 1974).
          - **Rip-up and reroute**: Failed nets get a second attempt after all
            other nets have been routed, as the routing landscape may have
            changed (PathFinder-style, McMurchie & Ebeling 1995).
        """
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
        reference_planning = constraints.get("referencePlanning", {})
        board_summary = dict(constraints.get("boardSummary", {}) or {})
        forced_layer = params.get("criticalLayer")
        critical_layer = (
            forced_layer
            or reference_planning.get("preferredSignalLayer")
            or "F.Cu"
        )
        applier = HybridRouteApplier(self.routing_commands, self.ipc_board_api)
        inventory = self._collect_inventory(board)
        footprints = {fp.GetReference(): fp for fp in board.GetFootprints()}
        routed: List[Dict[str, Any]] = []
        skipped: List[Dict[str, Any]] = []
        failed_for_retry: List[Dict[str, Any]] = []
        handled_diff_pairs: set[Tuple[str, str]] = set()

        # --- Congestion-aware net ordering ---
        # Within each priority level, route congested nets first
        critical_intents = [
            intent for intent in constraints["intents"]
            if intent["intent"] in critical_classes and intent["track_length_mm"] <= 0
        ]
        critical_intents_by_name = {
            str(intent.get("net_name") or ""): intent
            for intent in critical_intents
        }
        pair_layer_decisions: Dict[Tuple[str, str], Dict[str, Any]] = {}
        for intent in critical_intents:
            net_info = inventory.get(intent["net_name"], {})
            pads = net_info.get("pads", [])
            intent["_congestion"] = self._estimate_net_congestion(pads, board)
            intent["_escape_complexity"] = self._estimate_escape_complexity(
                intent["net_name"], pads, footprints
            )
            intent["_breakout_pressure"] = self._estimate_breakout_pressure(
                intent["net_name"], pads, board, footprints
            )
            intent["_reference_alignment"] = self._estimate_reference_alignment_pressure(
                intent["net_name"], pads, board, reference_planning
            )
            layer_decision: Dict[str, Any]
            if intent["intent"] == "HS_DIFF" and intent.get("diff_partner"):
                pair_key = tuple(sorted((intent["net_name"], intent["diff_partner"])))
                layer_decision = pair_layer_decisions.get(pair_key, {})
                if not layer_decision:
                    layer_decision = self._select_locked_diff_pair_route_layer(
                        intent=intent,
                        partner_intent=critical_intents_by_name.get(str(intent["diff_partner"] or "")),
                        inventory=inventory,
                        board=board,
                        reference_planning=reference_planning,
                        board_summary=board_summary,
                        default_layer=critical_layer,
                        forced_layer=forced_layer,
                        footprints=footprints,
                        via_limit=int(constraints.get("defaults", {}).get("hs_via_limit", 2)),
                    )
                    pair_layer_decisions[pair_key] = layer_decision
            else:
                layer_decision = self._select_critical_route_layer(
                    intent=intent,
                    pads=pads,
                    board=board,
                    reference_planning=reference_planning,
                    board_summary=board_summary,
                    default_layer=critical_layer,
                    forced_layer=forced_layer,
                    footprints=footprints,
                )
            intent["_route_layer"] = layer_decision.get("layer") or critical_layer
            intent["_route_layer_source"] = layer_decision.get("source", "referencePlanning")
            intent["_route_layer_bucket"] = layer_decision.get("bucket", "center")
            intent["_route_layer_centroid_x_mm"] = layer_decision.get("centroidXmm")
            intent["_estimated_via_count_total"] = layer_decision.get("estimatedViaCountTotal")
            intent["_estimated_via_count_per_net"] = layer_decision.get("estimatedViaCountPerNet")
            intent["_transition_policy"] = layer_decision.get("transitionPolicy")
            intent["_via_budget"] = layer_decision.get("viaBudget")

        critical_intents.sort(
            key=lambda item: (
                -item["priority"],
                -item.get("_escape_complexity", 0),
                -item.get("_breakout_pressure", 0),
                -item.get("_reference_alignment", 0),
                -item.get("_congestion", 0),
                item["net_name"],
            )
        )
        ordering = [
            {
                "net": intent["net_name"],
                "priority": intent["priority"],
                "escapeComplexity": round(float(intent.get("_escape_complexity", 0.0)), 4),
                "breakoutPressure": round(float(intent.get("_breakout_pressure", 0.0)), 4),
                "referenceAlignment": round(float(intent.get("_reference_alignment", 0.0)), 4),
                "localCongestion": round(float(intent.get("_congestion", 0.0)), 4),
                "selectedLayer": intent.get("_route_layer"),
                "selectedLayerSource": intent.get("_route_layer_source"),
                "selectedLayerBucket": intent.get("_route_layer_bucket"),
                "estimatedViaCountPerNet": intent.get("_estimated_via_count_per_net"),
                "transitionPolicy": intent.get("_transition_policy"),
            }
            for intent in critical_intents
        ]

        # Mark already-routed nets
        for intent in constraints["intents"]:
            if intent["intent"] in critical_classes and intent["track_length_mm"] > 0:
                skipped.append({
                    "net": intent["net_name"],
                    "reason": "already_routed",
                    "intent": intent["intent"],
                })

        # --- Main routing pass ---
        for intent in critical_intents:
            net_info = inventory.get(intent["net_name"], {})
            pads = net_info.get("pads", [])

            if intent["intent"] == "HS_DIFF" and intent.get("diff_partner"):
                pair_key = tuple(sorted((intent["net_name"], intent["diff_partner"])))
                if pair_key in handled_diff_pairs:
                    continue

            if len(pads) < 2:
                skipped.append({
                    "net": intent["net_name"],
                    "reason": "insufficient_pads",
                    "padCount": len(pads),
                    "intent": intent["intent"],
                })
                continue

            width_mm = float(params.get("criticalWidthMm") or 0.25)
            route_layer = str(intent.get("_route_layer") or critical_layer)
            if intent["intent"] in {"POWER_DC", "POWER_SWITCHING"}:
                power_target = float(
                    constraints.get("derived", {}).get(
                        "powerTargetWidthMm", constraints["defaults"]["power_min_width_mm"]
                    )
                )
                width_mm = max(width_mm, power_target)

            if intent["intent"] == "HS_DIFF" and intent.get("diff_partner"):
                pair_result = self._route_diff_pair(
                    intent["net_name"],
                    intent["diff_partner"],
                    inventory=inventory,
                    constraints=constraints,
                    width_mm=width_mm,
                    layer=route_layer,
                    board=board,
                    footprints=footprints,
                )
                if pair_result.get("success"):
                    handled_diff_pairs.add(pair_key)
                    routed.append({
                        "net": intent["net_name"],
                        "intent": intent["intent"],
                        "widthMm": width_mm,
                        "layer": route_layer,
                        "layerSource": intent.get("_route_layer_source"),
                        "backend": "diff_pair",
                        "pairWith": intent["diff_partner"],
                        "estimatedViaCountPerNet": intent.get("_estimated_via_count_per_net"),
                        "transitionPolicy": intent.get("_transition_policy"),
                    })
                    routed.append({
                        "net": intent["diff_partner"],
                        "intent": intent["intent"],
                        "widthMm": width_mm,
                        "layer": route_layer,
                        "layerSource": intent.get("_route_layer_source"),
                        "backend": "diff_pair",
                        "pairWith": intent["net_name"],
                        "estimatedViaCountPerNet": intent.get("_estimated_via_count_per_net"),
                        "transitionPolicy": intent.get("_transition_policy"),
                    })
                    continue
                failed_for_retry.append(intent)
                handled_diff_pairs.add(pair_key)
                continue

            # Multi-pin net routing (>2 pads)
            if len(pads) > 2:
                result = self._route_multi_pin_net(
                    pads, route_layer, width_mm, intent["net_name"], footprints, applier,
                )
                if result.get("success"):
                    routed.append({
                        "net": intent["net_name"],
                        "intent": intent["intent"],
                        "widthMm": width_mm,
                        "layer": route_layer,
                        "layerSource": intent.get("_route_layer_source"),
                        "backend": result.get("backend", "mst"),
                        "multiPin": True,
                        "edgesRouted": result.get("edgesRouted", 0),
                        "edgesTotal": result.get("edgesTotal", 0),
                    })
                else:
                    failed_for_retry.append(intent)
                continue

            # 2-pin net routing (original logic with IPC-first)
            same_layer_ipc = False
            result: Dict[str, Any]
            if self.ipc_board_api and pads[0]["ref"] in footprints and pads[1]["ref"] in footprints:
                start_layer = board.GetLayerName(footprints[pads[0]["ref"]].GetLayer())
                end_layer = board.GetLayerName(footprints[pads[1]["ref"]].GetLayer())
                if start_layer == end_layer and start_layer in {"F.Cu", "B.Cu"} and start_layer == route_layer:
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
                    if planned and self._path_is_orthogonal(planned):
                        result = applier.route_path(
                            planned,
                            layer=start_layer,
                            width_mm=width_mm,
                            net_name=intent["net_name"],
                        )
                        same_layer_ipc = result.get("success", False)
                    else:
                        result = {
                            "success": False,
                            "message": "IPC fast-path skipped for non-orthogonal or unplanned path",
                        }
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
                        "layer": route_layer,
                        "width": width_mm,
                        "net": intent["net_name"],
                    }
                )
            if result.get("success"):
                routed.append({
                    "net": intent["net_name"],
                    "intent": intent["intent"],
                    "widthMm": width_mm,
                    "layer": route_layer,
                    "layerSource": intent.get("_route_layer_source"),
                    "backend": "ipc" if same_layer_ipc else "swig",
                })
            else:
                failed_for_retry.append(intent)

        # --- Rip-up and reroute pass (PathFinder-style) ---
        # Failed nets get a second chance after the routing landscape has changed.
        # Reference: McMurchie & Ebeling (1995) — PathFinder negotiated congestion.
        rerouted: List[Dict[str, Any]] = []
        max_reroute_passes = int(params.get("maxReroutePasses", 1))
        for pass_num in range(max_reroute_passes):
            if not failed_for_retry:
                break
            still_failed: List[Dict[str, Any]] = []
            reroute_handled_diff_pairs: set[Tuple[str, str]] = set()
            for intent in failed_for_retry:
                net_info = inventory.get(intent["net_name"], {})
                pads = net_info.get("pads", [])
                width_mm = float(params.get("criticalWidthMm") or 0.25)
                route_layer = str(intent.get("_route_layer") or critical_layer)
                if intent["intent"] in {"POWER_DC", "POWER_SWITCHING"}:
                    power_target = float(
                        constraints.get("derived", {}).get(
                            "powerTargetWidthMm", constraints["defaults"]["power_min_width_mm"]
                        )
                    )
                    width_mm = max(width_mm, power_target)

                if intent["intent"] == "HS_DIFF" and intent.get("diff_partner"):
                    pair_key = tuple(sorted((intent["net_name"], intent["diff_partner"])))
                    if pair_key in reroute_handled_diff_pairs:
                        continue
                    result = self._route_diff_pair(
                        intent["net_name"],
                        intent["diff_partner"],
                        inventory=inventory,
                        constraints=constraints,
                        width_mm=width_mm,
                        layer=route_layer,
                        board=board,
                        footprints=footprints,
                    )
                    reroute_handled_diff_pairs.add(pair_key)
                    if result.get("success"):
                        rerouted.append({
                            "net": intent["net_name"],
                            "intent": intent["intent"],
                            "widthMm": width_mm,
                            "layer": route_layer,
                            "layerSource": intent.get("_route_layer_source"),
                            "backend": "diff_pair",
                            "pairWith": intent["diff_partner"],
                            "estimatedViaCountPerNet": intent.get("_estimated_via_count_per_net"),
                            "transitionPolicy": intent.get("_transition_policy"),
                            "reroutePass": pass_num + 1,
                        })
                        rerouted.append({
                            "net": intent["diff_partner"],
                            "intent": intent["intent"],
                            "widthMm": width_mm,
                            "layer": route_layer,
                            "layerSource": intent.get("_route_layer_source"),
                            "backend": "diff_pair",
                            "pairWith": intent["net_name"],
                            "estimatedViaCountPerNet": intent.get("_estimated_via_count_per_net"),
                            "transitionPolicy": intent.get("_transition_policy"),
                            "reroutePass": pass_num + 1,
                        })
                    else:
                        still_failed.append(intent)
                    continue

                if len(pads) > 2:
                    result = self._route_multi_pin_net(
                        pads, route_layer, width_mm, intent["net_name"], footprints, applier,
                    )
                elif len(pads) == 2:
                    result = self.routing_commands.route_pad_to_pad({
                        "fromRef": pads[0]["ref"],
                        "fromPad": pads[0]["pad"],
                        "toRef": pads[1]["ref"],
                        "toPad": pads[1]["pad"],
                        "layer": route_layer,
                        "width": width_mm,
                        "net": intent["net_name"],
                    })
                else:
                    result = {"success": False}

                if result.get("success"):
                    rerouted.append({
                        "net": intent["net_name"],
                        "intent": intent["intent"],
                        "widthMm": width_mm,
                        "layer": route_layer,
                        "layerSource": intent.get("_route_layer_source"),
                        "reroutePass": pass_num + 1,
                    })
                else:
                    still_failed.append(intent)
            failed_for_retry = still_failed

        # Record final failures
        for intent in failed_for_retry:
            skipped.append({
                "net": intent["net_name"],
                "intent": intent["intent"],
                "reason": "route_failed_after_retry",
                "padCount": len(inventory.get(intent["net_name"], {}).get("pads", [])),
            })

        routed.extend(rerouted)

        try:
            board.Save(str(board_path))
        except Exception:
            logger.debug("Board save after route_critical_nets failed", exc_info=True)

        return {
            "success": True,
            "message": (
                f"Critical routing completed: {len(routed)} routed "
                f"({len(rerouted)} via reroute), {len(skipped)} skipped"
            ),
            "boardPath": str(board_path),
            "routed": routed,
            "rerouted": rerouted,
            "skipped": skipped,
            "ordering": ordering,
            "backendPreference": "ipc" if self.ipc_board_api else "swig",
            "criticalLayer": critical_layer,
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
        constraints_result = params.get("constraintsResult", {})
        constraints_data = constraints_result.get("constraints", {})
        raw_matched_groups = list(
            constraints_data.get("matchedLengthGroups")
            or params.get("matchedLengthGroups")
            or []
        )
        default_group_skew = float(
            constraints_data.get("defaults", {}).get(
                "hs_diff_skew_mm",
                params.get("autoMatchedLengthMaxSkewMm", 0.25),
            )
        )
        matched_groups: List[Dict[str, Any]] = []
        for group in raw_matched_groups:
            normalized = dict(group)
            if normalized.get("maxSkewMm") is None:
                normalized["maxSkewMm"] = default_group_skew
            matched_groups.append(normalized)
        try:
            if hasattr(board, "BuildConnectivity"):
                board.BuildConnectivity()
                actions.append("build_connectivity")
        except Exception:
            logger.debug("BuildConnectivity failed during post_tune_routes", exc_info=True)

        matched_length_result: Dict[str, Any] = {
            "success": True,
            "message": "Matched-length tuning skipped",
            "tunedNets": [],
            "skipped": [],
        }
        if params.get("autoTuneMatchedLengths", True) and matched_groups:
            matched_length_result = self._tune_matched_length_groups(
                board,
                board_path,
                matched_groups=matched_groups,
                min_extra_mm=float(params.get("matchedLengthMinExtraMm", 0.3)),
                max_nets_per_group=int(params.get("matchedLengthMaxGroupSize", 4)),
            )
            if matched_length_result.get("tunedNets"):
                actions.append("matched_length_tuning")

        reference_zone_result: Dict[str, Any] = {
            "success": True,
            "created": False,
            "message": "Reference-zone synthesis skipped",
        }
        reference_zone_result = self._ensure_reference_ground_zone(
            board,
            board_path,
            constraints_data=constraints_data,
            params=params,
        )
        if reference_zone_result.get("created"):
            actions.append("reference_ground_zone")

        if params.get("refillZones", False):
            refill_result = self._refill_zones(board, board_path)
            if refill_result.get("success"):
                actions.append("refill_zones")

        healing_result: Dict[str, Any] = {
            "success": True,
            "message": "Support-net healing skipped",
            "addedVias": [],
            "passes": 0,
        }
        if params.get("autoHealSupportNets", True):
            healing_result = self._heal_support_net_connectivity(
                board,
                board_path,
                report_path=Path(
                    params.get("healingReportPath") or board_path.with_suffix(".post_tune_heal.drc.rpt")
                ),
                max_passes=int(params.get("healingPasses", 2)),
                max_vias_per_net=int(params.get("maxHealingViasPerNet", 4)),
            )
            if healing_result.get("addedVias") or healing_result.get("addedBridges"):
                actions.append("support_net_healing")
                if params.get("refillZones", False):
                    actions.append("refill_zones_after_healing")

        try:
            board.Save(str(board_path))
        except Exception:
            logger.debug("Board save after post_tune_routes failed", exc_info=True)

        return {
            "success": True,
            "message": "Post-route tuning hooks completed",
            "actions": actions,
            "boardPath": str(board_path),
            "matchedLengthTuning": matched_length_result,
            "referenceZone": reference_zone_result,
            "healing": healing_result,
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

        constraints_result = params.get("constraintsResult", {})
        constraints_data = constraints_result.get("constraints", {})
        matched_groups = list(
            constraints_data.get("matchedLengthGroups")
            or params.get("matchedLengthGroups")
            or []
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

        matched_group_skews: Dict[str, float] = {}
        matched_group_skew_ratios: List[float] = []
        matched_length_risk_flags: List[Dict[str, Any]] = []
        for group in matched_groups:
            nets = list(dict.fromkeys(group.get("nets", []) or []))
            if len(nets) < 2:
                continue

            lengths = {
                net_name: float(inventory.get(net_name, {}).get("track_length_mm", 0.0))
                for net_name in nets
                if net_name in inventory
            }
            if len(lengths) < 2:
                continue

            skew = max(lengths.values()) - min(lengths.values())
            raw_max_skew = group.get("maxSkewMm")
            if raw_max_skew is None:
                max_skew = float(
                    constraints_data.get("defaults", {}).get("hs_diff_skew_mm", 0.25)
                )
            else:
                max_skew = max(0.0, float(raw_max_skew))
            ratio = skew / max(max_skew, 0.01)
            key = "|".join(sorted(lengths))
            matched_group_skews[key] = round(skew, 4)
            matched_group_skew_ratios.append(ratio)
            if ratio > 1.0:
                matched_length_risk_flags.append(
                    {
                        "group": key,
                        "nets": sorted(lengths),
                        "maxSkewMm": round(max_skew, 4),
                        "observedSkewMm": round(skew, 4),
                        "ratio": round(ratio, 4),
                        "type": group.get("type", "bus"),
                    }
                )

        drc_result = self.design_rule_commands.run_drc(
            {"reportPath": params.get("reportPath") or str(board_path.with_suffix(".drc.rpt"))}
        )
        if not drc_result.get("success"):
            return drc_result

        severity = drc_result.get("summary", {}).get("by_severity", {})
        completion_rate = round(completed_nets / routeable_nets, 4) if routeable_nets else 1.0

        flat_metrics = {
            "wirelengthMm": round(wirelength_mm, 3),
            "viaCount": via_count,
            "routeableNetCount": routeable_nets,
            "completedNetCount": completed_nets,
            "completionRate": completion_rate,
            "drcErrors": int(severity.get("error", 0)),
            "drcWarnings": int(severity.get("warning", 0)),
            "maxDiffSkewMm": round(max(diff_lengths.values(), default=0.0), 4),
            "maxMatchedGroupSkewMm": round(max(matched_group_skews.values(), default=0.0), 4),
            "maxMatchedGroupSkewRatio": round(max(matched_group_skew_ratios, default=0.0), 4),
            "matchedGroupCount": len(matched_group_skews),
            "maxUncoupledMm": round(max(uncoupled_estimates, default=0.0), 4),
        }
        flags = {
            "powerNetMisuse": power_misuse_flags,
            "returnPathRisk": return_path_risk_flags,
            "matchedLengthRisk": matched_length_risk_flags,
        }

        # Compute weighted QoR score (uses qorWeights from constraints)
        qor_weights = constraints_data.get("qorWeights", params.get("qorWeights", {}))
        qor = compute_weighted_qor_score(flat_metrics, flags, qor_weights, constraints_data)

        report = {
            "success": severity.get("error", 0) == 0,
            "boardPath": str(board_path),
            "completionRate": completion_rate,
            "qorScore": qor["score"],
            "qorGrade": qor["grade"],
            "qorDetail": qor,
            "drc": {
                "errors": int(severity.get("error", 0)),
                "warnings": int(severity.get("warning", 0)),
                "violationsFile": drc_result.get("violationsFile"),
                "reportPath": drc_result.get("reportPath"),
            },
            "metrics": flat_metrics,
            "flags": flags,
            "pairSkewMm": diff_lengths,
            "matchedGroupSkewMm": matched_group_skews,
        }

        output_path = Path(params.get("qorReportPath", board_path.with_suffix(".autoroute_cfha.json")))
        _safe_mkdir(output_path)
        output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        report["reportPath"] = str(output_path)
        return report

    def _completion_snapshot(
        self,
        board: pcbnew.BOARD,
        intents_result: Dict[str, Any],
    ) -> Dict[str, Any]:
        inventory = self._collect_inventory(board)
        routeable_nets = 0
        completed_nets = 0

        for intent in intents_result.get("intents", []):
            info = inventory.get(intent.get("net_name", ""), {})
            pad_count = len(info.get("pads", []))
            has_copper = bool(info.get("track_length_mm", 0.0) > 0 or info.get("zones"))
            if pad_count >= 2:
                routeable_nets += 1
                if has_copper:
                    completed_nets += 1

        return {
            "inventory": inventory,
            "routeableNetCount": routeable_nets,
            "completedNetCount": completed_nets,
            "completionRate": round(completed_nets / routeable_nets, 4) if routeable_nets else 1.0,
        }

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

        strategy = params.get("strategy", "hybrid")
        effective_params = dict(params)
        reference_planning = constraints.get("constraints", {}).get("referencePlanning", {})
        pre_route_critical_layer = params.get("criticalLayer")
        pre_route_critical_layer_source = "user"
        if not pre_route_critical_layer:
            pre_route_critical_layer = reference_planning.get("preferredSignalLayer")
            pre_route_critical_layer_source = "referencePlanning"
        if not pre_route_critical_layer:
            pre_route_critical_layer = "F.Cu"
            pre_route_critical_layer_source = "default"
        pre_route_reference = {
            "success": True,
            "message": "Pre-route reference planning skipped",
            "skipped": True,
            "referencePlanning": reference_planning,
            "criticalLayer": pre_route_critical_layer,
            "criticalLayerSource": pre_route_critical_layer_source,
            "referenceZone": {
                "success": True,
                "created": False,
                "message": "Pre-route reference planning skipped",
            },
            "actions": [],
        }
        if strategy != "analysis_only":
            pre_route_reference = timed(
                "pre_route_reference",
                lambda payload: self._prepare_pre_route_reference(
                    board,
                    board_path,
                    constraints_data=payload["constraintsResult"]["constraints"],
                    params=payload,
                ),
                {**params, "constraintsResult": constraints},
            )
            if not pre_route_reference.get("success"):
                return pre_route_reference
            if pre_route_reference.get("criticalLayer") and not effective_params.get("criticalLayer"):
                effective_params["criticalLayer"] = pre_route_reference["criticalLayer"]
        else:
            stage_times["pre_route_reference"] = 0.0

        critical = {
            "success": True,
            "message": "Critical router skipped",
            "skipped": True,
        }
        if strategy != "analysis_only":
            critical = timed(
                "route_critical",
                self.route_critical_nets,
                {**effective_params, "constraintsResult": constraints},
            )
            if not critical.get("success"):
                return critical
        else:
            stage_times["route_critical"] = 0.0

        bulk = {
            "success": True,
            "message": "Bulk router skipped",
            "skipped": True,
        }
        if strategy not in {"critical_only", "analysis_only"}:
            completion_before_bulk = self._completion_snapshot(board, intents)
            freerouting_ready = bool(analysis.get("backends", {}).get("freerouting_ready"))
            if (
                completion_before_bulk.get("completionRate", 0) < 1.0
                and not params.get("skipBulkRoute")
                and freerouting_ready
            ):
                bulk = timed(
                    "bulk_route",
                    self.run_freerouting,
                    {**effective_params, "constraintsResult": constraints},
                )
            else:
                stage_times["bulk_route"] = 0.0
                if completion_before_bulk.get("completionRate", 0) >= 1.0:
                    bulk["message"] = "Bulk router not required for this board state"
                elif params.get("skipBulkRoute"):
                    bulk["message"] = "Bulk router skipped by caller"
                elif not freerouting_ready:
                    bulk["message"] = "Bulk router unavailable; Freerouting is not ready"
                bulk["completionRateBeforeBulk"] = completion_before_bulk.get("completionRate")

        post = {
            "success": True,
            "message": "Post-route tuning skipped",
            "skipped": True,
        }
        if strategy != "analysis_only":
            post = timed(
                "post_tune",
                self.post_tune_routes,
                {
                    **effective_params,
                    "constraintsResult": constraints,
                    "refillZones": params.get("refillZones", True),
                    "autoTuneMatchedLengths": params.get("autoTuneMatchedLengths", True),
                    "autoCreateReferenceZones": params.get("autoCreateReferenceZones", True),
                    "matchedLengthMinExtraMm": float(params.get("matchedLengthMinExtraMm", 0.3)),
                    "matchedLengthMaxGroupSize": int(params.get("matchedLengthMaxGroupSize", 4)),
                    "autoHealSupportNets": params.get("autoHealSupportNets", True),
                    "healingPasses": int(params.get("healingPasses", 2)),
                    "maxHealingViasPerNet": int(params.get("maxHealingViasPerNet", 4)),
                },
            )
        else:
            stage_times["post_tune"] = 0.0
        verify = timed(
            "verify",
            self.verify_routing_qor,
            {**effective_params, "intentResult": intents, "constraintsResult": constraints},
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
            "qorScore": verify.get("qorScore"),
            "qorGrade": verify.get("qorGrade"),
            "qorDetail": verify.get("qorDetail"),
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
                "preRouteReference": pre_route_reference,
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
