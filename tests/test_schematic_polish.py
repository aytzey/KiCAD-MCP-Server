from pathlib import Path

import sexpdata
from sexpdata import Symbol

from commands.schematic_polish import polish_schematic_readability


def _form(node, name):
    return (
        isinstance(node, list)
        and len(node) > 0
        and isinstance(node[0], Symbol)
        and node[0] == Symbol(name)
    )


def _child(node, name):
    for item in node:
        if _form(item, name):
            return item
    return None


def _label_size(data, name):
    for item in data:
        if _form(item, "label") and item[1] == name:
            effects = _child(item, "effects")
            font = _child(effects, "font")
            size = _child(font, "size")
            return float(size[1]), float(size[2])
    raise AssertionError(f"label not found: {name}")


def _junction_diameter(data):
    for item in data:
        if _form(item, "junction"):
            return float(_child(item, "diameter")[1])
    raise AssertionError("junction not found")


def test_polish_schematic_readability_hides_internal_labels_and_adds_frame(tmp_path):
    schematic = tmp_path / "demo.kicad_sch"
    schematic.write_text(
        """
(kicad_sch (version 20250114) (generator "test")
  (uuid "00000000-0000-0000-0000-000000000001")
  (paper "A4")
  (lib_symbols)
  (label "STAGE1_OUT" (at 10 10 0)
    (effects (font (size 1.27 1.27)) (justify left bottom))
    (uuid "00000000-0000-0000-0000-000000000002"))
  (label "VREF" (at 20 10 0)
    (effects (font (size 1.27 1.27)) (justify left bottom))
    (uuid "00000000-0000-0000-0000-000000000003"))
  (junction (at 10 10) (diameter 0) (color 0 0 0 0)
    (uuid "00000000-0000-0000-0000-000000000004"))
)
""".strip(),
        encoding="utf-8",
    )

    result = polish_schematic_readability(
        schematic,
        block_frames=[
            {
                "title": "GAIN STAGE",
                "x1": 5,
                "y1": 5,
                "x2": 40,
                "y2": 30,
            }
        ],
    )

    assert result["success"] is True
    assert result["hiddenLabels"] == ["STAGE1_OUT"]
    assert result["junctionsUpdated"] == 1
    assert result["framesAdded"] == 1

    data = sexpdata.loads(schematic.read_text(encoding="utf-8"))
    assert _label_size(data, "STAGE1_OUT") == (0.2, 0.2)
    assert _label_size(data, "VREF") == (1.27, 1.27)
    assert _junction_diameter(data) == 1.27
    assert any(_form(item, "rectangle") for item in data)
    assert any(_form(item, "text") and item[1] == "GAIN STAGE" for item in data)
