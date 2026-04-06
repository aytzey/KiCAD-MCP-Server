import math
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from commands.connection_schematic import ConnectionManager
from commands.dynamic_symbol_loader import DynamicSymbolLoader
from commands.pin_locator import PinLocator
from commands.schematic_analysis import (
    _load_sexp,
    _parse_labels,
    _parse_wires,
    find_overlapping_elements,
    find_wires_crossing_symbols,
)

TEMPLATE_PATH = Path(__file__).resolve().parent.parent / "templates" / "empty.kicad_sch"


def _make_temp_schematic() -> Path:
    schematic = Path(tempfile.mkdtemp()) / "test.kicad_sch"
    shutil.copy(TEMPLATE_PATH, schematic)
    return schematic


def _wire_touches_pin(wire: dict, pin_xy: tuple[float, float]) -> bool:
    return any(
        math.isclose(endpoint[0], pin_xy[0], abs_tol=1e-6)
        and math.isclose(endpoint[1], pin_xy[1], abs_tol=1e-6)
        for endpoint in (wire["start"], wire["end"])
    )


def test_connect_to_net_attaches_wire_to_actual_pin_location():
    schematic = _make_temp_schematic()
    loader = DynamicSymbolLoader()
    ConnectionManager._pin_locator = None

    assert loader.add_component(
        schematic,
        "Device",
        "R",
        "R1",
        value="10k",
        x=25.4,
        y=25.4,
        schematic_grid=2.54,
    )

    assert ConnectionManager.connect_to_net(schematic, "R1", "1", "SIG")

    locator = PinLocator()
    pin_xy = tuple(locator.get_pin_location(schematic, "R1", "1"))
    sexp_data = _load_sexp(schematic)
    wires = _parse_wires(sexp_data)
    labels = _parse_labels(sexp_data)

    assert any(_wire_touches_pin(wire, pin_xy) for wire in wires)
    assert any(label["name"] == "SIG" for label in labels)
    assert find_wires_crossing_symbols(schematic) == []
    assert find_overlapping_elements(schematic)["totalOverlaps"] == 0


def test_connect_to_net_respects_rotated_pin_coordinates():
    schematic = _make_temp_schematic()
    loader = DynamicSymbolLoader()
    ConnectionManager._pin_locator = None

    assert loader.add_component(
        schematic,
        "Device",
        "D_Schottky",
        "D1",
        value="1N5819",
        x=50.8,
        y=50.8,
        schematic_grid=2.54,
    )

    content = schematic.read_text(encoding="utf-8")
    content = content.replace(
        '(symbol (lib_id "Device:D_Schottky") (at 50.8 50.8 0) (unit 1)',
        '(symbol (lib_id "Device:D_Schottky") (at 50.8 50.8 90) (unit 1)',
        1,
    )
    schematic.write_text(content, encoding="utf-8")

    assert ConnectionManager.connect_to_net(schematic, "D1", "1", "VIN")

    locator = PinLocator()
    pin_xy = tuple(locator.get_pin_location(schematic, "D1", "1"))
    sexp_data = _load_sexp(schematic)
    wires = _parse_wires(sexp_data)

    assert any(_wire_touches_pin(wire, pin_xy) for wire in wires)
    assert find_wires_crossing_symbols(schematic) == []
    assert find_overlapping_elements(schematic)["totalOverlaps"] == 0
