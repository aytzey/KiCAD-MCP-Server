from unittest.mock import MagicMock

from commands.routing import RoutingCommands


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
