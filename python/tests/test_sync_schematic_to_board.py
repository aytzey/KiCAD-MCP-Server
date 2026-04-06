from types import SimpleNamespace
from unittest.mock import MagicMock


def _symbol(reference: str, footprint=None, value: str = ""):
    properties = SimpleNamespace(
        Reference=SimpleNamespace(value=reference),
        Value=SimpleNamespace(value=value),
    )
    if footprint is not None:
        properties.Footprint = SimpleNamespace(value=footprint)
    return SimpleNamespace(property=properties)


def test_should_auto_place_missing_footprints_defaults_to_blank_boards():
    from kicad_interface import KiCADInterface

    interface = KiCADInterface()

    assert interface._should_auto_place_missing_footprints({}, 0) is True
    assert interface._should_auto_place_missing_footprints({}, 3) is False
    assert interface._should_auto_place_missing_footprints(
        {"autoPlaceMissingFootprints": True}, 3
    ) is True
    assert interface._should_auto_place_missing_footprints(
        {"autoPlaceMissingFootprints": False}, 0
    ) is False


def test_auto_place_missing_footprints_uses_deterministic_grid_and_skips_missing_props(monkeypatch):
    from kicad_interface import KiCADInterface

    interface = KiCADInterface()
    schematic = SimpleNamespace(
        symbol=[
            _symbol("R1", "Resistor_SMD:R_0603_1608Metric", "10k"),
            _symbol("C1", "Capacitor_SMD:C_0603_1608Metric", "100n"),
            _symbol("U1", None, "MCU"),
        ]
    )
    existing = MagicMock()
    existing.GetReference.return_value = "R1"
    board = MagicMock()
    board.GetFootprints.return_value = [existing]

    placed_calls = []

    def _fake_place(params):
        placed_calls.append(params)
        return {"success": True}

    monkeypatch.setattr(interface, "_handle_place_component", _fake_place)

    result = interface._auto_place_missing_footprints(
        schematic,
        "/tmp/demo.kicad_pcb",
        board,
        {
            "placementStartXmm": 10,
            "placementStartYmm": 20,
            "placementPitchXmm": 5,
            "placementPitchYmm": 7,
            "placementColumns": 2,
        },
    )

    assert [call["reference"] for call in placed_calls] == ["C1"]
    assert placed_calls[0]["position"] == {"x": 10.0, "y": 20.0, "unit": "mm"}
    assert result["placed"][0]["reference"] == "C1"
    assert result["placed"][0]["footprint"] == "Capacitor_SMD:C_0603_1608Metric"
    assert result["skipped"] == [
        {"reference": "U1", "reason": "missing Footprint property in schematic"}
    ]
    assert result["errors"] == []
