"""
Tests for DynamicSymbolLoader placement behavior.
"""

import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from commands.dynamic_symbol_loader import DynamicSymbolLoader

TEMPLATE_PATH = Path(__file__).resolve().parent.parent / "templates" / "empty.kicad_sch"


def _make_temp_schematic(name: str = "test.kicad_sch") -> Path:
    tmp = Path(tempfile.mkdtemp()) / name
    shutil.copy(TEMPLATE_PATH, tmp)
    return tmp


def test_create_component_instance_snaps_to_grid_by_default():
    schematic = _make_temp_schematic()
    loader = DynamicSymbolLoader()

    ok = loader.create_component_instance(
        schematic,
        "Device",
        "R",
        reference="R1",
        value="10k",
        x=10.0,
        y=10.0,
    )

    assert ok is True
    content = schematic.read_text(encoding="utf-8")
    assert '(symbol (lib_id "Device:R") (at 10.16 10.16 0)' in content


def test_create_component_instance_can_preserve_explicit_coordinates():
    schematic = _make_temp_schematic()
    loader = DynamicSymbolLoader()

    ok = loader.create_component_instance(
        schematic,
        "Device",
        "R",
        reference="R1",
        value="10k",
        x=10.0,
        y=10.0,
        snap_to_grid=False,
    )

    assert ok is True
    content = schematic.read_text(encoding="utf-8")
    assert '(symbol (lib_id "Device:R") (at 10.0 10.0 0)' in content


def test_create_component_instance_uses_actual_project_name_in_instances():
    schematic = _make_temp_schematic("arduino_pwm_controller.kicad_sch")
    loader = DynamicSymbolLoader(project_path=schematic.parent)

    ok = loader.create_component_instance(
        schematic,
        "Device",
        "R",
        reference="R1",
        value="10k",
        x=10.0,
        y=10.0,
    )

    assert ok is True
    content = schematic.read_text(encoding="utf-8")
    assert '(project "arduino_pwm_controller"' in content


def test_power_symbols_are_marked_as_non_board_items():
    schematic = _make_temp_schematic("arduino_pwm_controller.kicad_sch")
    loader = DynamicSymbolLoader(project_path=schematic.parent)

    ok = loader.create_component_instance(
        schematic,
        "power",
        "PWR_FLAG",
        reference="#FLG0101",
        value="PWR_FLAG",
        x=10.0,
        y=10.0,
    )

    assert ok is True
    content = schematic.read_text(encoding="utf-8")
    assert '(symbol (lib_id "power:PWR_FLAG")' in content
    assert "(in_bom no) (on_board no) (dnp no)" in content
