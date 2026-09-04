"""Regression coverage for TypeScript tools that previously had no Python route."""

from pathlib import Path
from unittest.mock import MagicMock

import pcbnew

from kicad_interface import KiCADInterface


def _interface(board=None):
    interface = KiCADInterface.__new__(KiCADInterface)
    interface.board = board
    return interface


def test_add_zone_normalizes_top_level_mil_units():
    interface = _interface(MagicMock())
    interface.routing_commands = MagicMock()
    interface.routing_commands.add_copper_pour.return_value = {"success": True}

    result = interface._handle_add_zone(
        {
            "layer": "B.Cu",
            "net": "GND",
            "unit": "mil",
            "clearance": 10,
            "minWidth": 20,
            "points": [{"x": 100, "y": 200}, {"x": 300, "y": 200}, {"x": 300, "y": 400}],
        }
    )

    assert result["success"] is True
    forwarded = interface.routing_commands.add_copper_pour.call_args.args[0]
    assert forwarded["clearance"] == 0.254
    assert forwarded["minWidth"] == 0.508
    assert forwarded["points"][0] == {"x": 2.54, "y": 5.08, "unit": "mm"}


def test_component_annotation_adds_persistent_footprint_field(monkeypatch):
    board = MagicMock()
    footprint = MagicMock()
    footprint.GetNextFieldId.return_value = 7
    board.FindFootprintByReference.return_value = footprint
    field = MagicMock()
    monkeypatch.setattr(pcbnew, "PCB_FIELD", MagicMock(return_value=field))
    interface = _interface(board)

    result = interface._handle_add_component_annotation(
        {"reference": "U1", "annotation": "Pin 1 toward connector", "visible": False}
    )

    assert result["success"] is True
    field.SetText.assert_called_once_with("Pin 1 toward connector")
    field.SetVisible.assert_called_once_with(False)
    footprint.AddField.assert_called_once_with(field)


def test_group_components_reports_missing_members(monkeypatch):
    board = MagicMock()
    u1 = MagicMock()
    board.FindFootprintByReference.side_effect = lambda ref: u1 if ref == "U1" else None
    group = MagicMock()
    monkeypatch.setattr(pcbnew, "PCB_GROUP", MagicMock(return_value=group))
    interface = _interface(board)

    result = interface._handle_group_components(
        {"references": ["U1", "MISSING"], "groupName": "Power"}
    )

    assert result["success"] is True
    group.AddItem.assert_called_once_with(u1)
    board.Add.assert_called_once_with(group)
    assert "MISSING" in result["warnings"][0]


def _pad(number, net_code=0, net=None):
    pad = MagicMock()
    pad.GetNumber.return_value = number
    pad.GetNetCode.return_value = net_code
    pad.GetNet.return_value = net
    return pad


def test_replace_component_refuses_connected_pad_mismatch(monkeypatch):
    board = MagicMock()
    old = MagicMock()
    old.Pads.return_value = [_pad("1", 1, MagicMock()), _pad("2", 2, MagicMock())]
    board.FindFootprintByReference.return_value = old
    new = MagicMock()
    new.Pads.return_value = [_pad("1")]
    monkeypatch.setattr(pcbnew, "FootprintLoad", MagicMock(return_value=new))
    interface = _interface(board)
    interface.footprint_library = MagicMock()
    interface.footprint_library.find_footprint.return_value = ("/lib.pretty", "New")

    result = interface._handle_replace_component({"reference": "U1", "newFootprint": "Package:New"})

    assert result["success"] is False
    assert result["missingPads"] == ["2"]
    board.Add.assert_not_called()
    board.Delete.assert_not_called()


def test_replace_component_preserves_matching_pad_nets(monkeypatch):
    board = MagicMock()
    net = MagicMock()
    old = MagicMock()
    old.Pads.return_value = [_pad("1", 1, net)]
    old.IsFlipped.return_value = False
    old.GetParentGroup.return_value = None
    old.GetValue.return_value = "10k"
    board.FindFootprintByReference.return_value = old
    new_pad = _pad("1")
    new = MagicMock()
    new.Pads.return_value = [new_pad]
    new.GetValue.return_value = "10k"
    monkeypatch.setattr(pcbnew, "FootprintLoad", MagicMock(return_value=new))
    interface = _interface(board)
    interface.footprint_library = MagicMock()
    interface.footprint_library.find_footprint.return_value = ("/lib.pretty", "R_0805")

    result = interface._handle_replace_component(
        {"reference": "R1", "newFootprint": "Resistor_SMD:R_0805"}
    )

    assert result["success"] is True
    new_pad.SetNet.assert_called_once_with(net)
    board.Add.assert_called_once_with(new)
    board.Delete.assert_called_once_with(old)


def test_legacy_export_wrappers_delegate_with_supported_values(tmp_path):
    interface = _interface(MagicMock())
    interface._handle_export_pos = MagicMock(return_value={"success": True})
    interface._handle_export_3d_cli = MagicMock(return_value={"success": True})

    pos_result = interface._handle_export_position_file(
        {"outputPath": str(tmp_path / "parts.csv"), "format": "CSV", "units": "inch", "side": "top"}
    )
    vrml_result = interface._handle_export_vrml(
        {"outputPath": str(tmp_path / "board.wrl"), "useRelativePaths": True}
    )

    assert pos_result["success"] is True
    pos = interface._handle_export_pos.call_args.args[0]
    assert (pos["format"], pos["units"], pos["side"]) == ("csv", "in", "front")
    assert vrml_result["success"] is True
    vrml = interface._handle_export_3d_cli.call_args.args[0]
    assert vrml["format"] == "vrml"
    assert vrml["modelsRelative"] is True
    assert Path(vrml["modelsDir"]).name == "models"
