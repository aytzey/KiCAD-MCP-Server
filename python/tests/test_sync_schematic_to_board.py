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


def _bbox(left_mm: float, top_mm: float, right_mm: float, bottom_mm: float):
    scale = 1_000_000
    return SimpleNamespace(
        GetLeft=lambda: int(left_mm * scale),
        GetTop=lambda: int(top_mm * scale),
        GetRight=lambda: int(right_mm * scale),
        GetBottom=lambda: int(bottom_mm * scale),
    )


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
    assert result["strategy"] == "grid"
    assert result["rules"][0]["name"] == "deterministic_grid"
    assert result["skipped"] == [
        {"reference": "U1", "reason": "missing Footprint property in schematic"}
    ]
    assert result["errors"] == []


def test_build_auto_place_plan_routing_aware_clusters_components_by_connectivity():
    from kicad_interface import KiCADInterface

    interface = KiCADInterface()
    board = MagicMock()
    board.GetBoardEdgesBoundingBox.return_value = _bbox(0, 0, 100, 80)

    schematic_components = [
        {"reference": "J1", "footprint": "Connector_USB:USB_C", "value": ""},
        {"reference": "U1", "footprint": "Package_QFP:LQFP-48", "value": "MCU"},
        {"reference": "C1", "footprint": "Capacitor_SMD:C_0603_1608Metric", "value": "100n"},
        {"reference": "R1", "footprint": "Resistor_SMD:R_0603_1608Metric", "value": "22"},
    ]
    netlist = {
        "nets": [
            {
                "name": "USB_DP",
                "connections": [
                    {"component": "J1", "pin": "A6"},
                    {"component": "U1", "pin": "24"},
                ],
            },
            {
                "name": "USB_DN",
                "connections": [
                    {"component": "J1", "pin": "A7"},
                    {"component": "U1", "pin": "25"},
                ],
            },
            {
                "name": "VDD_3V3",
                "connections": [
                    {"component": "U1", "pin": "12"},
                    {"component": "C1", "pin": "1"},
                ],
            },
            {
                "name": "GND",
                "connections": [
                    {"component": "U1", "pin": "13"},
                    {"component": "C1", "pin": "2"},
                    {"component": "J1", "pin": "A1"},
                    {"component": "R1", "pin": "2"},
                ],
            },
            {
                "name": "USB_SENSE",
                "connections": [
                    {"component": "U1", "pin": "2"},
                    {"component": "R1", "pin": "1"},
                ],
            },
        ]
    }

    plan = interface._build_auto_place_plan(
        schematic_components,
        existing_refs=set(),
        params={
            "placementStrategy": "routing_aware",
            "placementPitchXmm": 10,
            "placementPitchYmm": 8,
            "placementEdgeMarginMm": 3,
        },
        netlist=netlist,
        board=board,
    )

    by_ref = {item["reference"]: item for item in plan["placements"]}
    assert plan["strategy"] == "routing_aware"
    assert by_ref["J1"]["position"]["x"] <= 5.0
    assert 30.0 <= by_ref["U1"]["position"]["x"] <= 70.0
    assert any(rule["name"] == "connectivity_clustering" for rule in plan["rules"])

    c1 = by_ref["C1"]["position"]
    r1 = by_ref["R1"]["position"]
    u1 = by_ref["U1"]["position"]
    j1 = by_ref["J1"]["position"]

    def _manhattan(a, b):
        return abs(a["x"] - b["x"]) + abs(a["y"] - b["y"])

    assert _manhattan(c1, u1) < _manhattan(c1, j1)
    assert _manhattan(r1, u1) < _manhattan(r1, j1)
    assert any(cluster["anchor"] == "U1" for cluster in plan["clusters"])
    assert any(
        cluster["anchor"] == "J1"
        and cluster["signalProfile"] == "high_speed"
        and "connectors_on_edge" in cluster["rulesApplied"]
        for cluster in plan["clusters"]
    )


def test_build_auto_place_plan_profiles_connectors_to_top_bottom_and_sides():
    from kicad_interface import KiCADInterface

    interface = KiCADInterface()
    board = MagicMock()
    board.GetBoardEdgesBoundingBox.return_value = _bbox(0, 0, 120, 90)

    schematic_components = [
        {"reference": "J1", "footprint": "Connector_USB:USB_C", "value": ""},
        {"reference": "J2", "footprint": "Connector_Generic:Conn_01x04", "value": ""},
        {"reference": "J3", "footprint": "Connector_Generic:Conn_01x02", "value": ""},
        {"reference": "U1", "footprint": "Package_QFP:LQFP-48", "value": "MCU"},
        {"reference": "U2", "footprint": "Package_SO:SOIC-8", "value": "ADC"},
        {"reference": "U3", "footprint": "Package_SO:SOIC-8", "value": "BUCK"},
    ]
    netlist = {
        "nets": [
            {
                "name": "USB_DP",
                "connections": [
                    {"component": "J1", "pin": "1"},
                    {"component": "U1", "pin": "1"},
                ],
            },
            {
                "name": "USB_DN",
                "connections": [
                    {"component": "J1", "pin": "2"},
                    {"component": "U1", "pin": "2"},
                ],
            },
            {
                "name": "ADC_IN",
                "connections": [
                    {"component": "J2", "pin": "1"},
                    {"component": "U2", "pin": "3"},
                ],
            },
            {
                "name": "VIN",
                "connections": [
                    {"component": "J3", "pin": "1"},
                    {"component": "U3", "pin": "1"},
                ],
            },
            {
                "name": "SW",
                "connections": [
                    {"component": "J3", "pin": "2"},
                    {"component": "U3", "pin": "2"},
                ],
            },
        ]
    }

    plan = interface._build_auto_place_plan(
        schematic_components,
        existing_refs=set(),
        params={
            "placementStrategy": "routing_aware",
            "placementPitchXmm": 10,
            "placementPitchYmm": 8,
            "placementEdgeMarginMm": 4,
        },
        netlist=netlist,
        board=board,
    )

    by_ref = {item["reference"]: item for item in plan["placements"]}
    assert by_ref["J1"]["position"]["x"] <= 6.0 or by_ref["J1"]["position"]["x"] >= 114.0
    assert by_ref["J2"]["position"]["y"] <= 6.0
    assert by_ref["J3"]["position"]["y"] >= 84.0
    assert any(
        cluster["anchor"] == "J2" and cluster["edge"] == "top" and cluster["signalProfile"] == "analog"
        for cluster in plan["clusters"]
    )
    assert any(
        cluster["anchor"] == "J3" and cluster["edge"] == "bottom" and cluster["signalProfile"] == "power_switching"
        for cluster in plan["clusters"]
    )


def test_build_auto_place_plan_legalizes_sensitive_cluster_separation():
    from kicad_interface import KiCADInterface

    interface = KiCADInterface()
    board = MagicMock()
    board.GetBoardEdgesBoundingBox.return_value = _bbox(0, 0, 40, 20)

    schematic_components = [
        {"reference": "U1", "footprint": "Package_SO:SOIC-8", "value": "ADC"},
        {"reference": "U2", "footprint": "Package_SO:SOIC-8", "value": "BUCK"},
    ]
    netlist = {
        "nets": [
            {"name": "ADC_IN", "connections": [{"component": "U1", "pin": "1"}]},
            {"name": "AGND", "connections": [{"component": "U1", "pin": "2"}]},
            {"name": "VIN", "connections": [{"component": "U2", "pin": "1"}]},
            {"name": "SW", "connections": [{"component": "U2", "pin": "2"}]},
        ]
    }

    plan = interface._build_auto_place_plan(
        schematic_components,
        existing_refs=set(),
        params={
            "placementStrategy": "routing_aware",
            "placementPitchXmm": 6,
            "placementPitchYmm": 6,
            "placementEdgeMarginMm": 3,
        },
        netlist=netlist,
        board=board,
    )

    by_ref = {item["reference"]: item for item in plan["placements"]}
    u1 = by_ref["U1"]["position"]
    u2 = by_ref["U2"]["position"]
    distance = ((u1["x"] - u2["x"]) ** 2 + (u1["y"] - u2["y"]) ** 2) ** 0.5

    assert distance >= 18.0
    assert any(rule["name"] == "net_separation_legalization" for rule in plan["rules"])
    assert any(
        cluster["anchor"] in {"U1", "U2"} and "maximize_net_separation" in cluster["rulesApplied"]
        for cluster in plan["clusters"]
    )


def test_build_auto_place_plan_prioritizes_reference_sensitive_connectors_for_center_side_slots():
    from kicad_interface import KiCADInterface

    interface = KiCADInterface()
    board = MagicMock()
    board.GetBoardEdgesBoundingBox.return_value = _bbox(0, 0, 120, 90)

    schematic_components = [
        {"reference": "J1", "footprint": "Connector_USB:USB_C", "value": ""},
        {"reference": "J2", "footprint": "Connector_Generic:Conn_01x02", "value": ""},
        {"reference": "J3", "footprint": "Connector_Generic:Conn_01x02", "value": ""},
        {"reference": "U1", "footprint": "Package_QFP:LQFP-48", "value": "MCU"},
        {"reference": "U2", "footprint": "Package_SO:SOIC-8", "value": "GPIO"},
        {"reference": "U3", "footprint": "Package_SO:SOIC-8", "value": "GPIO"},
    ]
    netlist = {
        "nets": [
            {
                "name": "USB_DP",
                "connections": [
                    {"component": "J1", "pin": "1"},
                    {"component": "U1", "pin": "1"},
                ],
            },
            {
                "name": "USB_DN",
                "connections": [
                    {"component": "J1", "pin": "2"},
                    {"component": "U1", "pin": "2"},
                ],
            },
            {
                "name": "GND",
                "connections": [
                    {"component": "J1", "pin": "A1"},
                    {"component": "U1", "pin": "3"},
                ],
            },
            {
                "name": "GPIO_A",
                "connections": [
                    {"component": "J2", "pin": "1"},
                    {"component": "U2", "pin": "1"},
                ],
            },
            {
                "name": "GPIO_B",
                "connections": [
                    {"component": "J3", "pin": "1"},
                    {"component": "U3", "pin": "1"},
                ],
            },
        ]
    }

    plan = interface._build_auto_place_plan(
        schematic_components,
        existing_refs=set(),
        params={
            "placementStrategy": "routing_aware",
            "placementPitchXmm": 10,
            "placementPitchYmm": 8,
            "placementEdgeMarginMm": 4,
        },
        netlist=netlist,
        board=board,
    )

    by_ref = {item["reference"]: item for item in plan["placements"]}
    center_y = 45.0
    assert any(rule["name"] == "reference_continuity_corridors" for rule in plan["rules"])

    j1_cluster = next(cluster for cluster in plan["clusters"] if cluster["anchor"] == "J1")
    assert j1_cluster["referenceProfile"] == "ground_continuity"
    assert "prefer_reference_continuity" in j1_cluster["rulesApplied"]
    assert abs(by_ref["J1"]["position"]["y"] - center_y) <= abs(by_ref["J2"]["position"]["y"] - center_y)
    assert abs(by_ref["J1"]["position"]["y"] - center_y) <= abs(by_ref["J3"]["position"]["y"] - center_y)


def test_build_auto_place_plan_partitions_quiet_and_noisy_reference_domains_on_side_edges():
    from kicad_interface import KiCADInterface

    interface = KiCADInterface()
    board = MagicMock()
    board.GetBoardEdgesBoundingBox.return_value = _bbox(0, 0, 120, 90)

    schematic_components = [
        {"reference": "J1", "footprint": "Connector_USB:USB_C", "value": ""},
        {"reference": "J2", "footprint": "Connector_USB:USB_C", "value": ""},
        {"reference": "J3", "footprint": "Connector_USB:USB_C", "value": ""},
        {"reference": "J4", "footprint": "Connector_USB:USB_C", "value": ""},
        {"reference": "J5", "footprint": "Connector_USB:USB_C", "value": ""},
        {"reference": "U1", "footprint": "Package_SO:SOIC-8", "value": "PHY"},
        {"reference": "U2", "footprint": "Package_SO:SOIC-8", "value": "PHY"},
        {"reference": "U3", "footprint": "Package_SO:SOIC-8", "value": "PHY"},
        {"reference": "U4", "footprint": "Package_SO:SOIC-8", "value": "PHY"},
        {"reference": "U5", "footprint": "Package_SO:SOIC-8", "value": "PHY"},
    ]
    netlist = {
        "nets": [
            {"name": "USB1_DP", "connections": [{"component": "J1", "pin": "1"}, {"component": "U1", "pin": "1"}]},
            {"name": "AGND", "connections": [{"component": "J1", "pin": "A1"}, {"component": "U1", "pin": "2"}]},
            {"name": "USB2_DP", "connections": [{"component": "J2", "pin": "1"}, {"component": "U2", "pin": "1"}]},
            {"name": "GND", "connections": [{"component": "J2", "pin": "A1"}, {"component": "U2", "pin": "2"}]},
            {"name": "USB3_DP", "connections": [{"component": "J3", "pin": "1"}, {"component": "U3", "pin": "1"}]},
            {"name": "PGND", "connections": [{"component": "J3", "pin": "A1"}, {"component": "U3", "pin": "2"}]},
            {"name": "USB4_DP", "connections": [{"component": "J4", "pin": "1"}, {"component": "U4", "pin": "1"}]},
            {"name": "USB5_DP", "connections": [{"component": "J5", "pin": "1"}, {"component": "U5", "pin": "1"}]},
        ]
    }

    plan = interface._build_auto_place_plan(
        schematic_components,
        existing_refs=set(),
        params={
            "placementStrategy": "routing_aware",
            "placementPitchXmm": 10,
            "placementPitchYmm": 8,
            "placementEdgeMarginMm": 4,
        },
        netlist=netlist,
        board=board,
    )

    by_ref = {item["reference"]: item for item in plan["placements"]}
    center_y = 45.0
    assert any(rule["name"] == "reference_domain_partitioning" for rule in plan["rules"])

    j1_cluster = next(cluster for cluster in plan["clusters"] if cluster["anchor"] == "J1")
    j2_cluster = next(cluster for cluster in plan["clusters"] if cluster["anchor"] == "J2")
    j3_cluster = next(cluster for cluster in plan["clusters"] if cluster["anchor"] == "J3")

    assert j1_cluster["referenceDomain"] == "AGND"
    assert j1_cluster["referenceDomainClass"] == "quiet"
    assert "prefer_quiet_reference_domain" in j1_cluster["rulesApplied"]

    assert j2_cluster["referenceDomain"] == "GND"
    assert j2_cluster["referenceDomainClass"] == "common"

    assert j3_cluster["referenceDomain"] == "PGND"
    assert j3_cluster["referenceDomainClass"] == "noisy"
    assert "demote_noisy_reference_domain" in j3_cluster["rulesApplied"]

    assert abs(by_ref["J1"]["position"]["y"] - center_y) < abs(by_ref["J2"]["position"]["y"] - center_y)
    assert abs(by_ref["J2"]["position"]["y"] - center_y) < abs(by_ref["J3"]["position"]["y"] - center_y)


def test_build_auto_place_plan_aligns_connector_edge_with_existing_reference_zone():
    from kicad_interface import KiCADInterface

    class _Zone:
        def __init__(self, net, bbox_mm):
            self._net = net
            self._bbox = _bbox(*bbox_mm)

        def GetNetname(self):
            return self._net

        def GetBoundingBox(self):
            return self._bbox

    interface = KiCADInterface()
    board = MagicMock()
    board.GetBoardEdgesBoundingBox.return_value = _bbox(0, 0, 120, 90)
    board.Zones.return_value = [
        _Zone("AGND", (0, 0, 40, 90)),
        _Zone("PGND", (80, 0, 120, 90)),
    ]

    schematic_components = [
        {"reference": "J1", "footprint": "Connector_USB:USB_C", "value": ""},
        {"reference": "J2", "footprint": "Connector_USB:USB_C", "value": ""},
        {"reference": "J3", "footprint": "Connector_USB:USB_C", "value": ""},
        {"reference": "U1", "footprint": "Package_SO:SOIC-8", "value": "PHY"},
        {"reference": "U2", "footprint": "Package_SO:SOIC-8", "value": "PHY"},
        {"reference": "U3", "footprint": "Package_SO:SOIC-8", "value": "PHY"},
    ]
    netlist = {
        "nets": [
            {"name": "USB1_DP", "connections": [{"component": "J1", "pin": "1"}, {"component": "U1", "pin": "1"}]},
            {"name": "AGND", "connections": [{"component": "J1", "pin": "A1"}, {"component": "U1", "pin": "2"}]},
            {"name": "USB2_DP", "connections": [{"component": "J2", "pin": "1"}, {"component": "U2", "pin": "1"}]},
            {"name": "PGND", "connections": [{"component": "J2", "pin": "A1"}, {"component": "U2", "pin": "2"}]},
            {"name": "USB3_DP", "connections": [{"component": "J3", "pin": "1"}, {"component": "U3", "pin": "1"}]},
        ]
    }

    plan = interface._build_auto_place_plan(
        schematic_components,
        existing_refs=set(),
        params={
            "placementStrategy": "routing_aware",
            "placementPitchXmm": 10,
            "placementPitchYmm": 8,
            "placementEdgeMarginMm": 4,
        },
        netlist=netlist,
        board=board,
    )

    by_ref = {item["reference"]: item for item in plan["placements"]}
    j1_cluster = next(cluster for cluster in plan["clusters"] if cluster["anchor"] == "J1")
    j2_cluster = next(cluster for cluster in plan["clusters"] if cluster["anchor"] == "J2")

    assert any(rule["name"] == "reference_zone_alignment" for rule in plan["rules"])
    assert j1_cluster["referenceEdgePreference"] == "left"
    assert j1_cluster["edge"] == "left"
    assert "align_with_reference_zone_edge" in j1_cluster["rulesApplied"]
    assert by_ref["J1"]["position"]["x"] <= 6.0

    assert j2_cluster["referenceEdgePreference"] == "right"
    assert j2_cluster["edge"] == "right"
    assert "align_with_reference_zone_edge" in j2_cluster["rulesApplied"]
    assert by_ref["J2"]["position"]["x"] >= 114.0
