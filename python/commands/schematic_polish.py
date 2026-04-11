"""Non-electrical schematic readability polish helpers.

These helpers intentionally avoid moving symbols or rewiring nets.  They only
adjust annotation-scale visual elements such as local label font sizes,
junction-dot diameters, and optional block frames.
"""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set

import sexpdata
from sexpdata import Symbol


DEFAULT_KEEP_LABELS: Set[str] = {
    "+3V3",
    "+5V",
    "+9V",
    "-5V",
    "-9V",
    "3V3",
    "5V",
    "9V",
    "GND",
    "VCC",
    "VDD",
    "VIN",
    "VREF",
    "VSS",
}

DEFAULT_INTERNAL_PREFIXES = (
    "CLIP",
    "FB",
    "IN_",
    "OUT_",
    "STAGE",
    "TONE_",
    "U1",
)


def _is_form(node: Any, name: str) -> bool:
    return (
        isinstance(node, list)
        and len(node) > 0
        and isinstance(node[0], Symbol)
        and node[0] == Symbol(name)
    )


def _form_value(node: Sequence[Any], name: str) -> Optional[List[Any]]:
    for child in node:
        if _is_form(child, name):
            return child
    return None


def _label_name(item: Sequence[Any]) -> str:
    return str(item[1]).strip('"') if len(item) > 1 else ""


def _set_font_size(item: Sequence[Any], size: float) -> bool:
    effects = _form_value(item, "effects")
    if not effects:
        return False
    font = _form_value(effects, "font")
    if not font:
        return False
    size_form = _form_value(font, "size")
    if not size_form or len(size_form) < 3:
        return False
    changed = float(size_form[1]) != size or float(size_form[2]) != size
    size_form[1] = size
    size_form[2] = size
    return changed


def _set_junction_diameter(item: Sequence[Any], diameter: float) -> bool:
    dia = _form_value(item, "diameter")
    if not dia or len(dia) < 2:
        return False
    changed = float(dia[1]) != diameter
    dia[1] = diameter
    return changed


def _is_internal_label(name: str, explicit: Optional[Set[str]], keep: Set[str]) -> bool:
    if name in keep:
        return False
    if explicit is not None:
        return name in explicit
    upper = name.upper()
    return "_" in name or any(upper.startswith(prefix) for prefix in DEFAULT_INTERNAL_PREFIXES)


def _rect_coords(item: Sequence[Any]) -> Optional[tuple[float, float, float, float]]:
    start = _form_value(item, "start")
    end = _form_value(item, "end")
    if not start or not end or len(start) < 3 or len(end) < 3:
        return None
    return (float(start[1]), float(start[2]), float(end[1]), float(end[2]))


def _has_rectangle(data: Sequence[Any], coords: Sequence[float]) -> bool:
    target = tuple(float(v) for v in coords)
    for item in data:
        if not _is_form(item, "rectangle"):
            continue
        existing = _rect_coords(item)
        if existing and all(abs(a - b) < 1e-6 for a, b in zip(existing, target)):
            return True
    return False


def _text_value(item: Sequence[Any]) -> str:
    return str(item[1]).strip('"') if len(item) > 1 else ""


def _has_text(data: Sequence[Any], value: str) -> bool:
    for item in data:
        if _is_form(item, "text") and _text_value(item) == value:
            return True
    return False


def _make_rectangle(frame: Dict[str, Any]) -> List[Any]:
    stroke_width = float(frame.get("strokeWidth", 0.15))
    return [
        Symbol("rectangle"),
        [Symbol("start"), float(frame["x1"]), float(frame["y1"])],
        [Symbol("end"), float(frame["x2"]), float(frame["y2"])],
        [Symbol("stroke"), [Symbol("width"), stroke_width], [Symbol("type"), Symbol("default")]],
        [Symbol("fill"), [Symbol("type"), Symbol("none")]],
        [Symbol("uuid"), str(uuid.uuid4())],
    ]


def _make_text(title: str, x: float, y: float, size: float = 2.2) -> List[Any]:
    return [
        Symbol("text"),
        title,
        [Symbol("exclude_from_sim"), Symbol("no")],
        [Symbol("at"), x, y, 0],
        [
            Symbol("effects"),
            [Symbol("font"), [Symbol("size"), size, size]],
            [Symbol("justify"), Symbol("left"), Symbol("bottom")],
        ],
        [Symbol("uuid"), str(uuid.uuid4())],
    ]


def _backup_path(path: Path, suffix: str) -> Path:
    suffix = suffix if suffix.startswith(".") else f".{suffix}"
    candidate = path.with_name(path.name + suffix)
    if not candidate.exists():
        return candidate
    index = 2
    while True:
        numbered = path.with_name(path.name + f"{suffix}.{index}")
        if not numbered.exists():
            return numbered
        index += 1


def polish_schematic_readability(
    schematic_path: str | Path,
    *,
    hide_internal_labels: bool = True,
    internal_label_names: Optional[Iterable[str]] = None,
    keep_label_names: Optional[Iterable[str]] = None,
    internal_label_font_size: float = 0.2,
    visible_label_font_size: Optional[float] = None,
    junction_diameter: Optional[float] = 1.27,
    block_frames: Optional[Sequence[Dict[str, Any]]] = None,
    create_backup: bool = False,
    backup_suffix: str = ".bak_pre_polish",
) -> Dict[str, Any]:
    """Apply a readability-only polish pass to a KiCad schematic file."""

    path = Path(schematic_path)
    if not path.exists():
        return {"success": False, "message": f"Schematic not found: {path}"}

    explicit_internal = set(internal_label_names) if internal_label_names is not None else None
    keep = set(DEFAULT_KEEP_LABELS)
    if keep_label_names:
        keep.update(str(name) for name in keep_label_names)

    original = path.read_text(encoding="utf-8")
    data = sexpdata.loads(original)

    backup = None
    if create_backup:
        backup = _backup_path(path, backup_suffix)
        shutil.copy2(path, backup)

    hidden_labels: List[str] = []
    resized_visible_labels: List[str] = []
    junctions_updated = 0
    frames_added = 0
    frame_titles_added = 0

    for item in data:
        if _is_form(item, "label"):
            name = _label_name(item)
            if hide_internal_labels and _is_internal_label(name, explicit_internal, keep):
                if _set_font_size(item, internal_label_font_size):
                    hidden_labels.append(name)
            elif visible_label_font_size is not None:
                if _set_font_size(item, visible_label_font_size):
                    resized_visible_labels.append(name)
        elif junction_diameter is not None and _is_form(item, "junction"):
            if _set_junction_diameter(item, float(junction_diameter)):
                junctions_updated += 1

    for frame in block_frames or []:
        coords = (frame["x1"], frame["y1"], frame["x2"], frame["y2"])
        if not _has_rectangle(data, coords):
            data.append(_make_rectangle(frame))
            frames_added += 1
        title = frame.get("title")
        if title:
            title_x = float(frame.get("titleX", frame["x1"] + 4.0))
            title_y = float(frame.get("titleY", frame["y1"] + 5.0))
            title_size = float(frame.get("titleSize", 2.2))
            if not _has_text(data, str(title)):
                data.append(_make_text(str(title), title_x, title_y, title_size))
                frame_titles_added += 1

    path.write_text(sexpdata.dumps(data), encoding="utf-8")

    return {
        "success": True,
        "schematic": str(path),
        "backup": str(backup) if backup else None,
        "hiddenLabels": sorted(set(hidden_labels)),
        "hiddenLabelCount": len(hidden_labels),
        "resizedVisibleLabels": sorted(set(resized_visible_labels)),
        "junctionsUpdated": junctions_updated,
        "framesAdded": frames_added,
        "frameTitlesAdded": frame_titles_added,
        "message": (
            f"Polished schematic readability: {len(hidden_labels)} internal label(s), "
            f"{junctions_updated} junction(s), {frames_added} frame(s)."
        ),
    }
