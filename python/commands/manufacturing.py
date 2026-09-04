"""Manufacturing-readiness gates and deterministic fabrication packages."""

from __future__ import annotations

import csv
import hashlib
import json
import logging
import shutil
import tempfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import pcbnew

logger = logging.getLogger("kicad_interface")

Command = Callable[[Dict[str, Any]], Dict[str, Any]]


DEFAULT_FAB_LIMITS = {
    "minTrackWidthMm": 0.20,
    "minClearanceMm": 0.20,
    "minDrillMm": 0.30,
    "minAnnularRingMm": 0.15,
    "minCopperEdgeMm": 0.25,
}

PART_NUMBER_FIELDS = (
    "lcsc",
    "lcsc part",
    "jlcpcb part",
    "mpn",
    "manufacturer part number",
    "manufacturer_pn",
    "mfr part",
)

MANUFACTURER_FIELDS = ("manufacturer", "mfr")
MPN_FIELDS = ("mpn", "manufacturer part number", "manufacturer_pn", "mfr part")
SUPPLIER_FIELDS = ("supplier", "vendor")
SUPPLIER_PART_FIELDS = (
    "supplier part number",
    "supplier_pn",
    "vendor part number",
    "lcsc",
    "lcsc part",
    "jlcpcb part",
)


def _call_or_none(value: Any, name: str, *args: Any) -> Any:
    method = getattr(value, name, None)
    if not callable(method):
        return None
    try:
        return method(*args)
    except Exception:
        return None


def _iu_to_mm(value: Any) -> Optional[float]:
    try:
        return float(value) / 1_000_000.0
    except (TypeError, ValueError):
        return None


def _xy_mm(value: Any) -> Tuple[Optional[float], Optional[float]]:
    if value is None:
        return None, None
    return _iu_to_mm(getattr(value, "x", None)), _iu_to_mm(getattr(value, "y", None))


def _bool_method(value: Any, name: str, default: bool = False) -> bool:
    result = _call_or_none(value, name)
    return bool(result) if result is not None else default


class ManufacturingCommands:
    """Analyze a board and export a gated, checksummed fab/assembly package."""

    def __init__(
        self,
        board: Any = None,
        *,
        run_drc: Optional[Command] = None,
        check_placement: Optional[Command] = None,
        export_gerbers: Optional[Command] = None,
        export_drill: Optional[Command] = None,
        export_position: Optional[Command] = None,
        export_bom: Optional[Command] = None,
        export_schematic_bom: Optional[Command] = None,
    ) -> None:
        self.board = board
        self.run_drc = run_drc
        self.check_placement = check_placement
        self.export_gerbers = export_gerbers
        self.export_drill = export_drill
        self.export_position = export_position
        self.export_bom = export_bom
        self.export_schematic_bom = export_schematic_bom

    def set_board(self, board: Any) -> None:
        self.board = board

    @staticmethod
    def _issue(
        issues: List[Dict[str, Any]],
        code: str,
        severity: str,
        message: str,
        **details: Any,
    ) -> None:
        issue: Dict[str, Any] = {
            "code": code,
            "severity": severity,
            "message": message,
        }
        if details:
            issue["details"] = details
        issues.append(issue)

    def _board_path(self, params: Dict[str, Any]) -> Optional[Path]:
        raw = params.get("boardPath") or _call_or_none(self.board, "GetFileName")
        if not raw:
            return None
        return Path(str(raw)).expanduser().resolve()

    def _copper_layers(self) -> List[str]:
        count = _call_or_none(self.board, "GetCopperLayerCount")
        try:
            numeric_count = int(count)
        except (TypeError, ValueError):
            numeric_count = 0
        if numeric_count > 0:
            if numeric_count == 1:
                return ["F.Cu"]
            if numeric_count == 2:
                return ["F.Cu", "B.Cu"]
            return ["F.Cu"] + [f"In{i}.Cu" for i in range(1, numeric_count - 1)] + ["B.Cu"]

        layers: List[str] = []
        layer_count = int(getattr(pcbnew, "PCB_LAYER_ID_COUNT", 64))
        for layer_id in range(layer_count):
            enabled = _call_or_none(self.board, "IsLayerEnabled", layer_id)
            name = _call_or_none(self.board, "GetLayerName", layer_id)
            if enabled and isinstance(name, str) and name.endswith(".Cu"):
                layers.append(name)
        return layers

    def _board_bounds(self) -> Optional[Dict[str, float]]:
        bbox = _call_or_none(self.board, "GetBoardEdgesBoundingBox")
        if bbox is None:
            return None
        width = _iu_to_mm(_call_or_none(bbox, "GetWidth"))
        height = _iu_to_mm(_call_or_none(bbox, "GetHeight"))
        left = _iu_to_mm(_call_or_none(bbox, "GetLeft"))
        top = _iu_to_mm(_call_or_none(bbox, "GetTop"))
        right = _iu_to_mm(_call_or_none(bbox, "GetRight"))
        bottom = _iu_to_mm(_call_or_none(bbox, "GetBottom"))
        if width is None and left is not None and right is not None:
            width = right - left
        if height is None and top is not None and bottom is not None:
            height = bottom - top
        if width is None or height is None:
            return None
        return {
            "widthMm": round(width, 4),
            "heightMm": round(height, 4),
            "leftMm": round(left or 0.0, 4),
            "topMm": round(top or 0.0, 4),
            "rightMm": round(right if right is not None else width, 4),
            "bottomMm": round(bottom if bottom is not None else height, 4),
        }

    def _edge_cut_count(self) -> Optional[int]:
        drawings = _call_or_none(self.board, "GetDrawings")
        if drawings is None:
            return None
        edge_id = _call_or_none(self.board, "GetLayerID", "Edge.Cuts")
        try:
            return sum(
                1
                for drawing in drawings
                if edge_id is not None and _call_or_none(drawing, "GetLayer") == edge_id
            )
        except TypeError:
            return None

    @staticmethod
    def _footprint_properties(footprint: Any) -> Dict[str, str]:
        result: Dict[str, str] = {}
        raw = _call_or_none(footprint, "GetProperties")
        if raw is not None:
            try:
                for key, value in dict(raw).items():
                    result[str(key).strip().casefold()] = str(value).strip()
            except Exception:
                pass
        fields = _call_or_none(footprint, "GetFields")
        if fields is not None:
            try:
                for field in fields:
                    name = _call_or_none(field, "GetName")
                    text = _call_or_none(field, "GetText")
                    if name and text:
                        result[str(name).strip().casefold()] = str(text).strip()
            except TypeError:
                pass
        return result

    @staticmethod
    def _pad_metrics(footprint: Any) -> Dict[str, Any]:
        pads = list(_call_or_none(footprint, "Pads") or [])
        minimum_feature: Optional[float] = None
        minimum_pitch: Optional[float] = None
        drilled = 0
        smd = 0
        positions: List[Tuple[float, float]] = []

        for pad in pads:
            size = _call_or_none(pad, "GetSize")
            sx, sy = _xy_mm(size)
            candidates = [value for value in (sx, sy) if value is not None and value > 0]
            if candidates:
                feature = min(candidates)
                minimum_feature = (
                    feature if minimum_feature is None else min(minimum_feature, feature)
                )

            drill = _call_or_none(pad, "GetDrillSize")
            dx, dy = _xy_mm(drill)
            if max(dx or 0.0, dy or 0.0) > 0:
                drilled += 1
            else:
                smd += 1

            position = _call_or_none(pad, "GetPosition")
            px, py = _xy_mm(position)
            if px is not None and py is not None:
                positions.append((px, py))

        for index, (x1, y1) in enumerate(positions):
            for x2, y2 in positions[index + 1 :]:
                pitch = ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5
                if pitch <= 0:
                    continue
                minimum_pitch = pitch if minimum_pitch is None else min(minimum_pitch, pitch)

        return {
            "padCount": len(pads),
            "smdPadCount": smd,
            "drilledPadCount": drilled,
            "minPadFeatureMm": round(minimum_feature, 4) if minimum_feature is not None else None,
            "minPadPitchMm": round(minimum_pitch, 4) if minimum_pitch is not None else None,
        }

    @staticmethod
    def _footprint_name(footprint: Any) -> str:
        fpid = _call_or_none(footprint, "GetFPID")
        for method in ("GetUniStringLibId", "Format"):
            value = _call_or_none(fpid, method) if fpid is not None else None
            if value:
                return str(value)
        return str(fpid) if fpid not in (None, "") else ""

    def _footprint_inventory(
        self,
        assembly_mode: str,
        issues: List[Dict[str, Any]],
        params: Dict[str, Any],
    ) -> Dict[str, Any]:
        footprints = list(_call_or_none(self.board, "GetFootprints") or [])
        references: Dict[str, int] = {}
        fine_pitch: List[str] = []
        smd_count = 0
        through_hole_count = 0
        missing_part_numbers: List[str] = []
        hand_pitch = float(params.get("handSolderMinPitchMm", 0.65))
        hand_feature = float(params.get("handSolderMinPadFeatureMm", 0.35))

        for footprint in footprints:
            reference = str(_call_or_none(footprint, "GetReference") or "").strip()
            value = str(_call_or_none(footprint, "GetValue") or "").strip()
            footprint_name = self._footprint_name(footprint)
            references[reference] = references.get(reference, 0) + 1

            if not reference or "?" in reference:
                self._issue(
                    issues,
                    "invalid_reference",
                    "blocker",
                    "Every physical footprint needs a unique annotated reference.",
                    reference=reference,
                )
            if not value:
                self._issue(
                    issues,
                    "missing_value",
                    "warning",
                    f"{reference or '<unknown>'} has no value.",
                )
            if not footprint_name:
                self._issue(
                    issues,
                    "missing_footprint_id",
                    "blocker",
                    f"{reference or '<unknown>'} has no library footprint identifier.",
                )

            metrics = self._pad_metrics(footprint)
            if metrics["smdPadCount"]:
                smd_count += 1
            if metrics["drilledPadCount"]:
                through_hole_count += 1
            if metrics["smdPadCount"] and (
                (metrics["minPadPitchMm"] is not None and metrics["minPadPitchMm"] < hand_pitch)
                or (
                    metrics["minPadFeatureMm"] is not None
                    and metrics["minPadFeatureMm"] < hand_feature
                )
            ):
                fine_pitch.append(reference)

            if assembly_mode == "smt" and not _bool_method(footprint, "IsExcludedFromBOM"):
                properties = self._footprint_properties(footprint)
                if not any(properties.get(field) for field in PART_NUMBER_FIELDS):
                    missing_part_numbers.append(reference)

        duplicates = sorted(ref for ref, count in references.items() if ref and count > 1)
        if duplicates:
            self._issue(
                issues,
                "duplicate_references",
                "blocker",
                "Duplicate footprint references make BOM and placement files ambiguous.",
                references=duplicates,
            )
        if fine_pitch and assembly_mode == "hand":
            self._issue(
                issues,
                "hand_solder_fine_pitch",
                "warning",
                "Some SMD footprints are below the configured comfortable hand-solder limits.",
                references=sorted(fine_pitch),
                minPitchMm=hand_pitch,
                minPadFeatureMm=hand_feature,
            )
        if missing_part_numbers:
            severity = "blocker" if params.get("requirePartNumbers", True) else "warning"
            self._issue(
                issues,
                "assembly_part_numbers_missing",
                severity,
                "SMT assembly mode requires a supplier or manufacturer part number for each BOM item.",
                references=sorted(missing_part_numbers),
                acceptedFields=list(PART_NUMBER_FIELDS),
            )

        return {
            "total": len(footprints),
            "smd": smd_count,
            "throughHole": through_hole_count,
            "finePitchForHandSolder": sorted(fine_pitch),
        }

    @staticmethod
    def _first_property(properties: Dict[str, str], aliases: Tuple[str, ...]) -> str:
        return next((properties[name] for name in aliases if properties.get(name)), "")

    def _write_board_bom(self, output_path: Path) -> Dict[str, Any]:
        """Write a procurement-aware BOM from the same board data preflight validates."""
        footprints = list(_call_or_none(self.board, "GetFootprints") or [])
        alias_fields = set(
            MANUFACTURER_FIELDS + MPN_FIELDS + SUPPLIER_FIELDS + SUPPLIER_PART_FIELDS
        )
        builtin_fields = {"reference", "value", "footprint", "datasheet", "description"}
        entries: List[Dict[str, Any]] = []
        extra_fields: set[str] = set()

        for footprint in footprints:
            if _bool_method(footprint, "IsExcludedFromBOM") or _bool_method(footprint, "IsDNP"):
                continue
            properties = self._footprint_properties(footprint)
            extras = {
                key: value
                for key, value in properties.items()
                if key not in alias_fields and key not in builtin_fields and value
            }
            extra_fields.update(extras)
            entries.append(
                {
                    "reference": str(_call_or_none(footprint, "GetReference") or "").strip(),
                    "value": str(_call_or_none(footprint, "GetValue") or "").strip(),
                    "footprint": self._footprint_name(footprint),
                    "manufacturer": self._first_property(properties, MANUFACTURER_FIELDS),
                    "mpn": self._first_property(properties, MPN_FIELDS),
                    "supplier": self._first_property(properties, SUPPLIER_FIELDS),
                    "supplierPartNumber": self._first_property(properties, SUPPLIER_PART_FIELDS),
                    "properties": properties,
                    "extras": extras,
                }
            )

        grouped: Dict[Tuple[Any, ...], List[Dict[str, Any]]] = {}
        for entry in entries:
            key = (
                entry["value"],
                entry["footprint"],
                entry["manufacturer"],
                entry["mpn"],
                entry["supplier"],
                entry["supplierPartNumber"],
                tuple(sorted(entry["properties"].items())),
            )
            grouped.setdefault(key, []).append(entry)

        extra_headers = [f"Property:{name}" for name in sorted(extra_fields)]
        fieldnames = [
            "References",
            "Qty",
            "Value",
            "Footprint",
            "Manufacturer",
            "MPN",
            "Supplier",
            "Supplier Part Number",
            *extra_headers,
        ]
        output_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with output_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
                writer.writeheader()
                for group in sorted(
                    grouped.values(),
                    key=lambda items: sorted(item["reference"] for item in items)[0],
                ):
                    first = group[0]
                    row = {
                        "References": ",".join(
                            sorted(item["reference"] for item in group if item["reference"])
                        ),
                        "Qty": len(group),
                        "Value": first["value"],
                        "Footprint": first["footprint"],
                        "Manufacturer": first["manufacturer"],
                        "MPN": first["mpn"],
                        "Supplier": first["supplier"],
                        "Supplier Part Number": first["supplierPartNumber"],
                    }
                    row.update(
                        {
                            f"Property:{name}": first["extras"].get(name, "")
                            for name in sorted(extra_fields)
                        }
                    )
                    writer.writerow(row)
        except Exception as exc:
            return {
                "success": False,
                "message": "Could not write procurement-aware board BOM",
                "errorDetails": str(exc),
            }
        return {
            "success": True,
            "message": f"Exported {len(grouped)} BOM line(s)",
            "outputPath": str(output_path),
            "source": "board_footprint_properties",
            "lineCount": len(grouped),
            "componentCount": len(entries),
            "fields": fieldnames,
        }

    def _check_fab_limits(
        self,
        limits: Dict[str, float],
        issues: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        tracks = list(_call_or_none(self.board, "GetTracks") or [])
        observed_track_widths: List[float] = []
        observed_drills: List[float] = []
        observed_rings: List[float] = []
        via_count = 0
        drilled_pad_count = 0
        plated_pad_count = 0
        npth_pad_count = 0

        for item in tracks:
            width = _iu_to_mm(_call_or_none(item, "GetWidth"))
            drill = _iu_to_mm(_call_or_none(item, "GetDrillValue"))
            if drill is not None and drill > 0:
                via_count += 1
                observed_drills.append(drill)
                if width is not None:
                    observed_rings.append((width - drill) / 2.0)
            elif width is not None and width > 0:
                observed_track_widths.append(width)

        npth_attribute = getattr(pcbnew, "PAD_ATTRIB_NPTH", None)
        for footprint in list(_call_or_none(self.board, "GetFootprints") or []):
            for pad in list(_call_or_none(footprint, "Pads") or []):
                drill_x, drill_y = _xy_mm(_call_or_none(pad, "GetDrillSize"))
                drill_dimensions = [
                    value for value in (drill_x, drill_y) if value is not None and value > 0
                ]
                if not drill_dimensions:
                    continue

                drilled_pad_count += 1
                observed_drills.append(min(drill_dimensions))
                is_npth = (
                    npth_attribute is not None
                    and _call_or_none(pad, "GetAttribute") == npth_attribute
                )
                if is_npth:
                    npth_pad_count += 1
                    continue

                plated_pad_count += 1
                size_x, size_y = _xy_mm(_call_or_none(pad, "GetSize"))
                drill_by_axis = (drill_x, drill_y)
                size_by_axis = (size_x, size_y)
                ring_dimensions = [
                    (size - drill) / 2.0
                    for size, drill in zip(size_by_axis, drill_by_axis)
                    if size is not None and drill is not None and drill > 0
                ]
                if len(drill_dimensions) == 1 and not ring_dimensions:
                    drill = drill_dimensions[0]
                    ring_dimensions = [
                        (size - drill) / 2.0 for size in size_by_axis if size is not None
                    ]
                if ring_dimensions:
                    observed_rings.append(min(ring_dimensions))

        violations: Dict[str, List[float]] = {}
        narrow = [value for value in observed_track_widths if value < limits["minTrackWidthMm"]]
        small_drills = [value for value in observed_drills if value < limits["minDrillMm"]]
        small_rings = [value for value in observed_rings if value < limits["minAnnularRingMm"]]
        if narrow:
            violations["trackWidthMm"] = narrow
        if small_drills:
            violations["drillMm"] = small_drills
        if small_rings:
            violations["annularRingMm"] = small_rings

        for feature, values in violations.items():
            self._issue(
                issues,
                f"fab_limit_{feature}",
                "blocker",
                f"Copper geometry is below the configured fabrication limit for {feature}.",
                observedMin=round(min(values), 4),
                count=len(values),
                limits=limits,
            )

        settings = _call_or_none(self.board, "GetDesignSettings")
        configured = {
            "minTrackWidthMm": _iu_to_mm(getattr(settings, "m_TrackMinWidth", None)),
            "minClearanceMm": _iu_to_mm(getattr(settings, "m_MinClearance", None)),
            "minDrillMm": _iu_to_mm(getattr(settings, "m_MinThroughDrill", None)),
            "minAnnularRingMm": _iu_to_mm(getattr(settings, "m_ViasMinAnnularWidth", None)),
            "minCopperEdgeMm": _iu_to_mm(getattr(settings, "m_CopperEdgeClearance", None)),
        }
        for key, value in configured.items():
            if value is not None and value + 1e-9 < limits[key]:
                self._issue(
                    issues,
                    f"design_rule_below_fab_{key}",
                    "blocker",
                    f"Board rule {key} is looser than the selected fabrication profile.",
                    configured=round(value, 4),
                    required=limits[key],
                )

        return {
            "limits": limits,
            "configuredRules": configured,
            "observed": {
                "minTrackWidthMm": (
                    round(min(observed_track_widths), 4) if observed_track_widths else None
                ),
                "minDrillMm": round(min(observed_drills), 4) if observed_drills else None,
                "minAnnularRingMm": round(min(observed_rings), 4) if observed_rings else None,
                "trackCount": len(observed_track_widths),
                "viaCount": via_count,
                "drilledPadCount": drilled_pad_count,
                "platedPadCount": plated_pad_count,
                "npthPadCount": npth_pad_count,
            },
        }

    def analyze_manufacturing_readiness(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Run non-destructive two-layer fabrication and assembly checks."""
        if self.board is None:
            return {"success": False, "message": "No board is loaded"}

        assembly_mode = str(params.get("assemblyMode", "hand")).lower()
        if assembly_mode not in {"hand", "smt"}:
            return {
                "success": False,
                "message": "assemblyMode must be 'hand' or 'smt'",
            }

        board_path = self._board_path(params)
        issues: List[Dict[str, Any]] = []
        if board_path is None or not board_path.is_file():
            self._issue(
                issues,
                "board_not_saved",
                "blocker",
                "Manufacturing checks require a saved .kicad_pcb file.",
            )

        copper_layers = self._copper_layers()
        if len(copper_layers) != 2 or set(copper_layers) != {"F.Cu", "B.Cu"}:
            self._issue(
                issues,
                "not_two_layer",
                "blocker",
                "This production profile requires exactly F.Cu and B.Cu.",
                copperLayers=copper_layers,
            )

        bounds = self._board_bounds()
        if not bounds or bounds["widthMm"] <= 0 or bounds["heightMm"] <= 0:
            self._issue(
                issues,
                "invalid_board_outline",
                "blocker",
                "Edge.Cuts does not produce a non-zero board outline.",
            )
        edge_cut_count = self._edge_cut_count()
        if edge_cut_count == 0:
            self._issue(
                issues,
                "missing_edge_cuts",
                "blocker",
                "No drawing primitives were found on Edge.Cuts.",
            )
        elif edge_cut_count is None:
            self._issue(
                issues,
                "outline_closure_unverified",
                "warning",
                "The API could not enumerate Edge.Cuts; DRC remains the authoritative closure check.",
            )

        inventory = self._footprint_inventory(assembly_mode, issues, params)
        if inventory["total"] == 0:
            self._issue(
                issues,
                "no_footprints",
                "blocker",
                "The board has no physical footprints to manufacture.",
            )

        limits = dict(DEFAULT_FAB_LIMITS)
        for key, value in (params.get("fabLimits") or {}).items():
            if key in limits:
                numeric = float(value)
                if numeric <= 0:
                    return {"success": False, "message": f"fabLimits.{key} must be positive"}
                limits[key] = numeric
        fab = self._check_fab_limits(limits, issues)

        placement_result: Dict[str, Any] = {"success": False, "skipped": True}
        if params.get("checkPlacement", True) and self.check_placement:
            placement_result = self.check_placement(
                {
                    "margin": float(params.get("courtyardMarginMm", 0.0)),
                    "include_boundary": True,
                }
            )
            if placement_result.get("success"):
                overlaps = placement_result.get("overlaps", [])
                boundary = placement_result.get("boundary_violations", [])
                if overlaps:
                    self._issue(
                        issues,
                        "courtyard_overlaps",
                        "blocker",
                        "Courtyard overlaps must be resolved before fabrication.",
                        count=len(overlaps),
                        sample=overlaps[:20],
                    )
                if boundary:
                    self._issue(
                        issues,
                        "footprints_outside_outline",
                        "blocker",
                        "One or more footprints extend outside the board outline.",
                        count=len(boundary),
                        sample=boundary[:20],
                    )
            else:
                self._issue(
                    issues,
                    "placement_check_failed",
                    "blocker",
                    "Placement clearance could not be verified.",
                    result=placement_result,
                )

        drc_result: Dict[str, Any] = {"success": False, "skipped": True}
        if params.get("runDrc", True):
            if self.run_drc:
                drc_result = self.run_drc(
                    {
                        "reportPath": params.get("reportPath"),
                        "timeoutSec": params.get("timeoutSec", 600),
                    }
                )
                if not drc_result.get("success"):
                    self._issue(
                        issues,
                        "drc_failed",
                        "blocker",
                        "DRC did not complete successfully.",
                        result=drc_result,
                    )
                else:
                    summary = drc_result.get("summary", {})
                    severities = summary.get("by_severity", {})
                    errors = int(severities.get("error", 0) or 0)
                    drc_warning_count = int(severities.get("warning", 0) or 0)
                    if errors:
                        self._issue(
                            issues,
                            "drc_errors",
                            "blocker",
                            f"DRC reports {errors} error(s).",
                            summary=summary,
                            violationsFile=drc_result.get("violationsFile"),
                        )
                    if drc_warning_count:
                        self._issue(
                            issues,
                            "drc_warnings",
                            "warning",
                            f"DRC reports {drc_warning_count} warning(s) for review.",
                            summary=summary,
                        )
            else:
                self._issue(
                    issues,
                    "drc_unavailable",
                    "blocker",
                    "No DRC runner is configured.",
                )

        blockers = [issue for issue in issues if issue["severity"] == "blocker"]
        warnings = [issue for issue in issues if issue["severity"] == "warning"]
        if params.get("blockOnWarnings") and warnings:
            blockers = blockers + warnings

        return {
            "success": True,
            "ready": not blockers,
            "readyForFabrication": not blockers,
            "readyForAssembly": not blockers,
            "boardPath": str(board_path) if board_path else None,
            "profile": "conservative_2layer",
            "assemblyMode": assembly_mode,
            "summary": {
                "blockers": len(blockers),
                "warnings": len(warnings),
                "copperLayers": copper_layers,
                "boardBounds": bounds,
                "edgeCutPrimitiveCount": edge_cut_count,
                "footprints": inventory,
            },
            "fabrication": fab,
            "placement": placement_result,
            "drc": drc_result,
            "issues": issues,
        }

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _collect_files(root: Path) -> List[Path]:
        return sorted(path for path in root.rglob("*") if path.is_file())

    @staticmethod
    def _export_failure(stage: str, result: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "success": False,
            "message": f"Manufacturing export failed during {stage}",
            "stage": stage,
            "errorDetails": result,
        }

    def prepare_manufacturing_package(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Export Gerbers, drill, BOM, positions, reports, manifest, and ZIP.

        The command refuses to create a package when a readiness blocker is
        present unless ``allowUnsafe`` is explicitly true. Files are produced
        in a staging directory and published only after every export succeeds.
        """
        readiness_params = {**params, "runDrc": True, "checkPlacement": True}
        readiness = self.analyze_manufacturing_readiness(readiness_params)
        if not readiness.get("success"):
            return readiness
        allow_unsafe = bool(params.get("allowUnsafe", False))
        if not readiness.get("ready") and not allow_unsafe:
            return {
                "success": False,
                "message": "Manufacturing package blocked by readiness checks",
                "stage": "preflight",
                "readiness": readiness,
                "hint": "Resolve blockers; use allowUnsafe only for a reviewed exception.",
            }

        board_path = self._board_path(params)
        if board_path is None:
            return {"success": False, "message": "No saved board path is available"}

        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        default_output = board_path.parent / "manufacturing" / f"{board_path.stem}-{timestamp}"
        output_dir = Path(params.get("outputDir") or default_output).expanduser().resolve()
        # Append instead of replacing the suffix so ``release.v1`` publishes as
        # ``release.v1.zip`` rather than unexpectedly colliding with ``release.zip``.
        archive_path = Path(f"{output_dir}.zip")
        if output_dir.exists():
            return {
                "success": False,
                "message": f"Output directory already exists: {output_dir}",
                "hint": "Choose a new outputDir; existing manufacturing data is never overwritten.",
            }
        if archive_path.exists():
            return {
                "success": False,
                "message": f"Archive already exists: {archive_path}",
                "hint": "Choose a new outputDir; existing manufacturing data is never overwritten.",
            }
        output_dir.parent.mkdir(parents=True, exist_ok=True)

        stage_root = Path(
            tempfile.mkdtemp(prefix=f".{board_path.stem}-manufacturing-", dir=output_dir.parent)
        ).resolve()
        if stage_root.parent != output_dir.parent:
            return {"success": False, "message": "Unsafe staging path resolution"}

        fabrication_dir = stage_root / "fabrication"
        assembly_dir = stage_root / "assembly"
        reports_dir = stage_root / "reports"
        fabrication_dir.mkdir()
        assembly_dir.mkdir()
        reports_dir.mkdir()
        exports: Dict[str, Any] = {}
        temporary_archive: Optional[Path] = None
        published_output = False
        published_archive = False

        try:
            if not all((self.export_gerbers, self.export_drill, self.export_position)):
                return {
                    "success": False,
                    "message": "Manufacturing exporters are not configured",
                }
            assert self.export_gerbers is not None
            assert self.export_drill is not None
            assert self.export_position is not None

            gerber_dir = fabrication_dir / "gerbers"
            drill_dir = fabrication_dir / "drill"
            gerber_result = self.export_gerbers(
                {
                    "boardPath": str(board_path),
                    "outputDir": str(gerber_dir),
                    "layers": params.get("gerberLayers")
                    or ["F.Cu", "B.Cu", "F.Mask", "B.Mask", "F.SilkS", "B.SilkS", "Edge.Cuts"],
                    "precision": int(params.get("gerberPrecision", 6)),
                }
            )
            if not gerber_result.get("success"):
                return self._export_failure("gerbers", gerber_result)
            exports["gerbers"] = gerber_result

            drill_result = self.export_drill(
                {
                    "boardPath": str(board_path),
                    "outputDir": str(drill_dir),
                    "format": "excellon",
                    "excellonUnits": "mm",
                    "generateMap": True,
                    "mapFormat": "pdf",
                }
            )
            if not drill_result.get("success"):
                return self._export_failure("drill", drill_result)
            exports["drill"] = drill_result

            position_path = assembly_dir / f"{board_path.stem}-positions.csv"
            position_result = self.export_position(
                {
                    "boardPath": str(board_path),
                    "outputPath": str(position_path),
                    "format": "csv",
                    "units": "mm",
                    "side": "both",
                    "excludeDnp": True,
                }
            )
            if not position_result.get("success"):
                return self._export_failure("positions", position_result)
            exports["positions"] = position_result

            bom_path = assembly_dir / f"{board_path.stem}-bom.csv"
            # Use the board properties that readiness just validated.  This
            # prevents schematic/PCB source drift and keeps MPN/supplier fields
            # that KiCad's default BOM column set silently drops.
            bom_result = self._write_board_bom(bom_path)
            if not bom_result.get("success"):
                return self._export_failure("bom", bom_result)
            exports["bom"] = bom_result

            violations_file = readiness.get("drc", {}).get("violationsFile")
            if violations_file and Path(violations_file).is_file():
                shutil.copy2(violations_file, reports_dir / Path(violations_file).name)

            readiness_path = reports_dir / "manufacturing-readiness.json"
            readiness_path.write_text(json.dumps(readiness, indent=2), encoding="utf-8")
            notes_path = stage_root / "ASSEMBLY_NOTES.txt"
            notes_path.write_text(
                "\n".join(
                    [
                        f"Board: {board_path.name}",
                        f"Assembly mode: {readiness['assemblyMode']}",
                        "Copper stack: F.Cu / B.Cu",
                        "Gerbers and Excellon drill files are in fabrication/.",
                        "BOM and placement CSV are in assembly/.",
                        "Review polarity, pin 1, connector orientation, and DNP choices before ordering.",
                        (
                            "WARNING: Package was generated with allowUnsafe=true; review readiness blockers."
                            if allow_unsafe and not readiness.get("ready")
                            else "Readiness gates passed at package generation time."
                        ),
                        "",
                    ]
                ),
                encoding="utf-8",
            )

            staged_files = self._collect_files(stage_root)
            manifest_entries = [
                {
                    "path": path.relative_to(stage_root).as_posix(),
                    "size": path.stat().st_size,
                    "sha256": self._sha256(path),
                }
                for path in staged_files
            ]
            manifest = {
                "schemaVersion": 1,
                "generatedAt": datetime.now(UTC).isoformat(),
                "board": str(board_path),
                "assemblyMode": readiness["assemblyMode"],
                "profile": readiness["profile"],
                "unsafeOverride": allow_unsafe and not readiness.get("ready"),
                "readiness": {
                    "ready": readiness.get("ready"),
                    "blockers": readiness.get("summary", {}).get("blockers"),
                    "warnings": readiness.get("summary", {}).get("warnings"),
                },
                "files": manifest_entries,
            }
            manifest_path = stage_root / "manifest.json"
            manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

            package_files = sorted([*staged_files, manifest_path])
            file_count = len(package_files)
            with tempfile.NamedTemporaryFile(
                prefix=f".{archive_path.name}.",
                suffix=".tmp",
                dir=archive_path.parent,
                delete=False,
            ) as archive_handle:
                temporary_archive = Path(archive_handle.name)
            with zipfile.ZipFile(temporary_archive, "w", zipfile.ZIP_DEFLATED) as archive:
                for path in package_files:
                    archive.write(path, path.relative_to(stage_root).as_posix())

            # Both deliverables are fully built before either public path is
            # exposed. If the second rename fails, the exception path removes
            # the newly-published first path so callers never receive a partial
            # manufacturing package.
            stage_root.replace(output_dir)
            published_output = True
            temporary_archive.replace(archive_path)
            temporary_archive = None
            published_archive = True

            return {
                "success": True,
                "message": "Manufacturing package generated",
                "outputDir": str(output_dir),
                "archivePath": str(archive_path),
                "manifestPath": str(output_dir / "manifest.json"),
                "fileCount": file_count,
                "readiness": readiness,
                "exports": exports,
            }
        except Exception as exc:
            logger.exception("Manufacturing package generation failed")
            if published_archive and archive_path.exists():
                archive_path.unlink(missing_ok=True)
            if published_output and output_dir.exists():
                shutil.rmtree(output_dir, ignore_errors=True)
            return {
                "success": False,
                "message": "Manufacturing package generation failed",
                "errorDetails": str(exc),
            }
        finally:
            if temporary_archive is not None:
                temporary_archive.unlink(missing_ok=True)
            # Only the uniquely-created staging directory is ever removed.
            if stage_root.exists() and stage_root != output_dir:
                shutil.rmtree(stage_root, ignore_errors=True)
