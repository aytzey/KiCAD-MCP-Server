from unittest.mock import MagicMock

import pytest

from commands.routing import RoutingCommands, _offset_polyline_miter


def test_route_differential_pair_adds_synchronized_transitions(monkeypatch):
    net_pos_obj = object()
    net_neg_obj = object()
    nets_map = MagicMock()
    nets_map.has_key.side_effect = lambda name: name in {"USB_D_P", "USB_D_N"}
    nets_map.__getitem__.side_effect = lambda name: {
        "USB_D_P": net_pos_obj,
        "USB_D_N": net_neg_obj,
    }[name]

    board = MagicMock()
    board.GetLayerID.side_effect = lambda layer: {"F.Cu": 0, "B.Cu": 31}.get(layer, -1)
    board.GetNetInfo.return_value.NetsByName.return_value = nets_map
    board.SetModified = MagicMock()
    board.BuildConnectivity = MagicMock()

    commands = RoutingCommands(board=board)
    monkeypatch.setattr(commands, "_get_track_width_mm", lambda width: 0.25)
    monkeypatch.setattr(
        commands,
        "_get_point",
        lambda point_spec: type(
            "Point",
            (),
            {
                "x": int(float(point_spec["x"]) * 1_000_000),
                "y": int(float(point_spec["y"]) * 1_000_000),
            },
        )(),
    )
    monkeypatch.setattr(
        commands,
        "_plan_trace_points",
        lambda start, end, layer, width_mm, **kwargs: [start, end],
    )
    monkeypatch.setattr(
        commands,
        "_select_paired_via_positions",
        lambda **kwargs: {
            "center": (4.0, 10.2) if kwargs["anchor_mid"][0] < 10.0 else (16.0, 10.2),
            "posVia": (4.0, 10.0) if kwargs["anchor_mid"][0] < 10.0 else (16.0, 10.0),
            "negVia": (4.0, 10.4) if kwargs["anchor_mid"][0] < 10.0 else (16.0, 10.4),
            "blockedCount": 0,
            "candidates": [],
        },
    )

    route_trace_calls = []
    add_via_calls = []
    main_segments = []

    monkeypatch.setattr(
        commands,
        "route_trace",
        lambda params: route_trace_calls.append(params) or {"success": True},
    )
    monkeypatch.setattr(
        commands,
        "add_via",
        lambda params: add_via_calls.append(params) or {"success": True},
    )
    monkeypatch.setattr(
        commands,
        "_add_track_segment",
        lambda start, end, layer_id, width_mm, net: main_segments.append(
            {
                "start": (start.x, start.y),
                "end": (end.x, end.y),
                "layerId": layer_id,
                "widthMm": width_mm,
                "net": net,
            }
        )
        or MagicMock(),
    )

    result = commands.route_differential_pair(
        {
            "startPos": {"x": 2.0, "y": 10.2, "unit": "mm"},
            "endPos": {"x": 18.0, "y": 10.2, "unit": "mm"},
            "startPosPos": {"x": 2.0, "y": 10.0, "unit": "mm"},
            "startPosNeg": {"x": 2.0, "y": 10.4, "unit": "mm"},
            "endPosPos": {"x": 18.0, "y": 10.0, "unit": "mm"},
            "endPosNeg": {"x": 18.0, "y": 10.4, "unit": "mm"},
            "netPos": "USB_D_P",
            "netNeg": "USB_D_N",
            "layer": "B.Cu",
            "startLayer": "F.Cu",
            "endLayer": "F.Cu",
            "startRef": "J1",
            "endRef": "U1",
            "width": 0.25,
            "gap": 0.4,
            "maxSkewMm": 0.25,
            "allowLayerTransitions": True,
        }
    )

    assert result["success"] is True
    assert result["diffPair"]["pairedTransitions"] is True
    assert result["diffPair"]["viaCount"] == 4
    assert result["diffPair"]["startTransition"]["viaCount"] == 2
    assert result["diffPair"]["endTransition"]["viaCount"] == 2
    assert len(route_trace_calls) == 4
    assert len(add_via_calls) == 4
    assert len(main_segments) == 2
    assert [call["layer"] for call in route_trace_calls] == ["F.Cu", "F.Cu", "F.Cu", "F.Cu"]
    assert all(call["to_layer"] == "B.Cu" for call in add_via_calls)
    assert {segment["net"] for segment in main_segments} == {"USB_D_P", "USB_D_N"}
    board.SetModified.assert_called_once()
    board.BuildConnectivity.assert_called()


def test_route_differential_pair_adds_return_path_stitching_vias(monkeypatch):
    nets_map = MagicMock()
    nets_map.has_key.side_effect = lambda name: name in {"USB_D_P", "USB_D_N", "GND"}
    nets_map.__getitem__.side_effect = lambda name: {
        "USB_D_P": object(),
        "USB_D_N": object(),
        "GND": object(),
    }[name]

    board = MagicMock()
    board.GetLayerID.side_effect = lambda layer: {"F.Cu": 0, "B.Cu": 31}.get(layer, -1)
    board.GetNetInfo.return_value.NetsByName.return_value = nets_map
    board.SetModified = MagicMock()
    board.BuildConnectivity = MagicMock()

    commands = RoutingCommands(board=board)
    monkeypatch.setattr(commands, "_get_track_width_mm", lambda width: 0.25)
    monkeypatch.setattr(
        commands,
        "_get_point",
        lambda point_spec: type(
            "Point",
            (),
            {
                "x": int(float(point_spec["x"]) * 1_000_000),
                "y": int(float(point_spec["y"]) * 1_000_000),
            },
        )(),
    )
    monkeypatch.setattr(
        commands,
        "_plan_trace_points",
        lambda start, end, layer, width_mm, **kwargs: [start, end],
    )
    monkeypatch.setattr(
        commands,
        "_select_paired_via_positions",
        lambda **kwargs: {
            "center": (4.0, 10.2) if kwargs["anchor_mid"][0] < 10.0 else (16.0, 10.2),
            "posVia": (4.0, 10.0) if kwargs["anchor_mid"][0] < 10.0 else (16.0, 10.0),
            "negVia": (4.0, 10.4) if kwargs["anchor_mid"][0] < 10.0 else (16.0, 10.4),
            "referenceVias": (
                [(4.0, 9.35), (4.0, 11.05)]
                if kwargs["anchor_mid"][0] < 10.0
                else [(16.0, 9.35), (16.0, 11.05)]
            ),
            "referenceBlockedCount": 0,
            "blockedCount": 0,
            "candidates": [],
        },
    )

    add_via_calls = []
    monkeypatch.setattr(commands, "route_trace", lambda params: {"success": True})
    monkeypatch.setattr(
        commands,
        "add_via",
        lambda params: add_via_calls.append(params) or {"success": True},
    )
    monkeypatch.setattr(commands, "_add_track_segment", lambda *args, **kwargs: MagicMock())

    result = commands.route_differential_pair(
        {
            "startPos": {"x": 2.0, "y": 10.2, "unit": "mm"},
            "endPos": {"x": 18.0, "y": 10.2, "unit": "mm"},
            "startPosPos": {"x": 2.0, "y": 10.0, "unit": "mm"},
            "startPosNeg": {"x": 2.0, "y": 10.4, "unit": "mm"},
            "endPosPos": {"x": 18.0, "y": 10.0, "unit": "mm"},
            "endPosNeg": {"x": 18.0, "y": 10.4, "unit": "mm"},
            "netPos": "USB_D_P",
            "netNeg": "USB_D_N",
            "layer": "B.Cu",
            "startLayer": "F.Cu",
            "endLayer": "F.Cu",
            "width": 0.25,
            "gap": 0.4,
            "referenceNet": "GND",
        }
    )

    diff_pair = result["diffPair"]
    ground_vias = [call for call in add_via_calls if call["net"] == "GND"]
    assert result["success"] is True
    assert diff_pair["viaCount"] == 4
    assert diff_pair["stitchViaCount"] == 4
    assert diff_pair["returnPathStitching"] is True
    assert diff_pair["referenceNet"] == "GND"
    assert diff_pair["startTransition"]["stitchViaCount"] == 2
    assert diff_pair["endTransition"]["stitchViaCount"] == 2
    assert len(add_via_calls) == 8
    assert len(ground_vias) == 4
    assert all(call["from_layer"] == "F.Cu" and call["to_layer"] == "B.Cu" for call in ground_vias)


def test_route_trace_fails_closed_when_obstacle_planner_has_no_path(monkeypatch):
    board = MagicMock()
    board.GetLayerID.return_value = 0
    commands = RoutingCommands(board=board)
    monkeypatch.setattr(commands, "_get_track_width_mm", lambda width: 0.25)
    monkeypatch.setattr(
        commands,
        "_get_point",
        lambda point: type(
            "Point",
            (),
            {"x": int(point["x"] * 1_000_000), "y": int(point["y"] * 1_000_000)},
        )(),
    )
    monkeypatch.setattr(commands, "_plan_trace_points", lambda *args, **kwargs: None)
    add_segment = MagicMock()
    monkeypatch.setattr(commands, "_add_track_segment", add_segment)

    result = commands.route_trace(
        {
            "start": {"x": 0.0, "y": 0.0, "unit": "mm"},
            "end": {"x": 10.0, "y": 0.0, "unit": "mm"},
            "layer": "F.Cu",
        }
    )

    assert result["success"] is False
    assert "clearance-safe" in result["errorDetails"]
    add_segment.assert_not_called()
    board.SetModified.assert_not_called()


def _pad_route_commands(monkeypatch, *, end_layer="F.Cu"):
    def make_pad(number, x):
        pad = MagicMock()
        pad.GetNumber.return_value = number
        pad.GetPosition.return_value = type("Point", (), {"x": int(x * 1_000_000), "y": 0})()
        pad.GetNetname.return_value = "N1"
        return pad

    start_fp = MagicMock()
    start_fp.GetReference.return_value = "J1"
    start_fp.Pads.return_value = [make_pad("1", 0.0)]
    start_fp.GetLayer.return_value = 0
    end_fp = MagicMock()
    end_fp.GetReference.return_value = "U1"
    end_fp.Pads.return_value = [make_pad("1", 10.0)]
    end_fp.GetLayer.return_value = 0 if end_layer == "F.Cu" else 31
    board = MagicMock()
    board.GetFootprints.return_value = [start_fp, end_fp]
    board.GetLayerName.side_effect = lambda layer_id: "F.Cu" if layer_id == 0 else "B.Cu"
    commands = RoutingCommands(board=board)
    monkeypatch.setattr(commands, "_get_track_width_mm", lambda width: 0.25)
    monkeypatch.setattr(commands, "_get_clearance_mm", lambda: 0.2)
    monkeypatch.setattr(
        commands,
        "_get_pad_escape_point",
        lambda pad, footprint, target, margin: (
            0.5 if footprint is start_fp else 9.5,
            0.0,
        ),
    )
    return commands


def test_same_layer_pad_route_fails_before_trace_when_planner_has_no_path(monkeypatch):
    commands = _pad_route_commands(monkeypatch)
    monkeypatch.setattr(commands, "_plan_trace_points", lambda *args, **kwargs: None)
    route_trace = MagicMock()
    monkeypatch.setattr(commands, "route_trace", route_trace)

    result = commands.route_pad_to_pad(
        {"fromRef": "J1", "fromPad": "1", "toRef": "U1", "toPad": "1"}
    )

    assert result["success"] is False
    assert "clearance-safe" in result["errorDetails"]
    route_trace.assert_not_called()


def test_cross_layer_pad_route_requires_both_safe_via_legs(monkeypatch):
    commands = _pad_route_commands(monkeypatch, end_layer="B.Cu")
    monkeypatch.setattr(commands, "_find_best_via_position", lambda *args, **kwargs: (5.0, 0.0))
    planner = MagicMock(side_effect=[[(0.5, 0.0), (5.0, 0.0)], None])
    monkeypatch.setattr(commands, "_plan_trace_points", planner)
    route_trace = MagicMock()
    add_via = MagicMock()
    monkeypatch.setattr(commands, "route_trace", route_trace)
    monkeypatch.setattr(commands, "add_via", add_via)

    result = commands.route_pad_to_pad(
        {"fromRef": "J1", "fromPad": "1", "toRef": "U1", "toPad": "1"}
    )

    assert result["success"] is False
    assert "via leg" in result["errorDetails"]
    route_trace.assert_not_called()
    add_via.assert_not_called()


def test_mitered_polyline_offset_preserves_spacing_around_right_angle():
    center = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0)]

    assert _offset_polyline_miter(center, 0.2) == [
        (0.0, 0.2),
        (9.8, 0.2),
        (9.8, 10.0),
    ]
    assert _offset_polyline_miter(center, -0.2) == [
        (0.0, -0.2),
        (10.2, -0.2),
        (10.2, 10.0),
    ]


def test_mitered_polyline_offset_rejects_reversal():
    with pytest.raises(ValueError, match="180-degree reversal"):
        _offset_polyline_miter([(0.0, 0.0), (5.0, 0.0), (0.0, 0.0)], 0.2)


def test_differential_pair_uses_mitered_offsets_for_bent_route(monkeypatch):
    nets_map = MagicMock()
    nets_map.has_key.side_effect = lambda name: name in {"DP", "DN"}
    nets_map.__getitem__.side_effect = lambda name: object()
    board = MagicMock()
    board.GetLayerID.return_value = 0
    board.GetNetInfo.return_value.NetsByName.return_value = nets_map
    commands = RoutingCommands(board=board)
    monkeypatch.setattr(commands, "_get_track_width_mm", lambda width: 0.2)
    monkeypatch.setattr(
        commands,
        "_get_point",
        lambda point: type(
            "Point",
            (),
            {"x": int(point["x"] * 1_000_000), "y": int(point["y"] * 1_000_000)},
        )(),
    )
    planned_widths = []

    def plan(start, end, layer, width_mm, **kwargs):
        planned_widths.append(width_mm)
        return [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0)]

    monkeypatch.setattr(commands, "_plan_trace_points", plan)
    monkeypatch.setattr(
        "commands.routing.pcbnew.VECTOR2I",
        lambda x, y: type("Vector", (), {"x": x, "y": y})(),
    )
    segments = []

    def add_segment(start, end, layer_id, width_mm, net):
        segments.append(
            (
                (start.x / 1_000_000, start.y / 1_000_000),
                (end.x / 1_000_000, end.y / 1_000_000),
                net,
            )
        )
        return MagicMock()

    monkeypatch.setattr(commands, "_add_track_segment", add_segment)
    result = commands.route_differential_pair(
        {
            "startPos": {"x": 0.0, "y": 0.0},
            "endPos": {"x": 10.0, "y": 10.0},
            "startPosPos": {"x": 0.0, "y": 0.2},
            "startPosNeg": {"x": 0.0, "y": -0.2},
            "endPosPos": {"x": 9.8, "y": 10.0},
            "endPosNeg": {"x": 10.2, "y": 10.0},
            "netPos": "DP",
            "netNeg": "DN",
            "width": 0.2,
            "gap": 0.4,
        }
    )

    assert result["success"] is True
    assert planned_widths == [pytest.approx(0.6)]
    assert segments == [
        ((0.0, 0.2), (9.8, 0.2), "DP"),
        ((0.0, -0.2), (10.2, -0.2), "DN"),
        ((9.8, 0.2), (9.8, 10.0), "DP"),
        ((10.2, -0.2), (10.2, 10.0), "DN"),
    ]
