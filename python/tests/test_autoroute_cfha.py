from pathlib import Path
from unittest.mock import MagicMock

from commands.autoroute_cfha import AutorouteCFHACommands, compile_kicad_dru, compute_weighted_qor_score


def test_compile_kicad_dru_emits_core_rules():
    text = compile_kicad_dru(
        {
            "compiledRules": [
                {
                    "name": "cfha_hs_diff_gap",
                    "condition": "A.NetName == 'USB_DP' || A.NetName == 'USB_DN'",
                    "constraint": "diff_pair_gap",
                    "values": {"min": 0.12, "opt": 0.15, "max": 0.18},
                },
                {
                    "name": "cfha_power_min_width",
                    "condition": "A.NetName == 'VIN'",
                    "constraint": "track_width",
                    "min": 1.0,
                },
                {
                    "name": "cfha_hs_via_limit",
                    "condition": "A.NetName == 'USB_DP'",
                    "constraint": "via_count",
                    "max": 2,
                },
            ]
        }
    )

    assert '(rule "cfha_hs_diff_gap"' in text
    assert "(constraint diff_pair_gap (min 0.12mm) (opt 0.15mm) (max 0.18mm))" in text
    assert '(rule "cfha_power_min_width"' in text
    assert "(constraint track_width (min 1.0mm))" in text
    assert "(constraint via_count (max 2))" in text


def test_compute_weighted_qor_score_treats_limit_boundary_as_passing():
    qor = compute_weighted_qor_score(
        {
            "completionRate": 1.0,
            "drcErrors": 0,
            "wirelengthMm": 50.0,
            "viaCount": 0,
            "maxDiffSkewMm": 0.0,
            "maxMatchedGroupSkewRatio": 1.0,
            "maxUncoupledMm": 3.0,
        },
        {"returnPathRisk": []},
        {},
        {"defaults": {"hs_diff_skew_mm": 0.25, "hs_diff_uncoupled_mm": 3.0}},
    )

    assert qor["subScores"]["skew"] == 1.0
    assert qor["subScores"]["uncoupled"] == 1.0


def test_extract_routing_intents_uses_overrides_and_diff_partner():
    commands = AutorouteCFHACommands()
    commands.analyze_board_routing_context = MagicMock(
        return_value={
            "success": True,
            "boardPath": "/tmp/demo.kicad_pcb",
            "profiles": ["generic_2layer"],
            "interfaces": ["USB2"],
            "backends": {"critical_router_default": "orthoroute-internal"},
            "summary": {"copperLayers": ["F.Cu", "B.Cu"]},
            "netInventory": {
                "USB_DP": {
                    "class": "Default",
                    "pads": [{}, {}],
                    "pad_refs": ["J1", "U1"],
                    "track_length_mm": 0.0,
                    "track_count": 0,
                    "via_count": 0,
                    "zones": [],
                },
                "USB_DN": {
                    "class": "Default",
                    "pads": [{}, {}],
                    "pad_refs": ["J1", "U1"],
                    "track_length_mm": 0.0,
                    "track_count": 0,
                    "via_count": 0,
                    "zones": [],
                },
                "VIN": {
                    "class": "Default",
                    "pads": [{}, {}],
                    "pad_refs": ["J1", "U2"],
                    "track_length_mm": 5.5,
                    "track_count": 2,
                    "via_count": 0,
                    "zones": [],
                },
                "GND": {
                    "class": "Default",
                    "pads": [{}, {}, {}],
                    "pad_refs": ["J1", "U1", "U2"],
                    "track_length_mm": 0.0,
                    "track_count": 0,
                    "via_count": 0,
                    "zones": [{"net": "GND", "layer": "B.Cu"}],
                },
            },
        }
    )

    result = commands.extract_routing_intents({})

    assert result["success"] is True
    assert result["byIntent"]["HS_DIFF"] == ["USB_DN", "USB_DP"]
    assert "POWER_DC" in result["byIntent"]
    diff_items = {item["net_name"]: item for item in result["intents"]}
    assert diff_items["USB_DP"]["diff_partner"] == "USB_DN"
    assert diff_items["VIN"]["intent"] == "POWER_DC"
    assert diff_items["GND"]["intent"] == "GROUND"


def test_extract_routing_intents_promotes_ddr_bus_nets_to_hs_single():
    commands = AutorouteCFHACommands()
    commands.analyze_board_routing_context = MagicMock(
        return_value={
            "success": True,
            "boardPath": "/tmp/ddr_demo.kicad_pcb",
            "profiles": ["generic_4layer"],
            "interfaces": ["DDR4"],
            "backends": {"critical_router_default": "orthoroute-internal"},
            "summary": {"copperLayers": ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"]},
            "netInventory": {
                "DQ0": {
                    "class": "Default",
                    "pads": [{}, {}],
                    "pad_refs": ["U1", "U2"],
                    "track_length_mm": 0.0,
                    "track_count": 0,
                    "via_count": 0,
                    "zones": [],
                },
                "DQ1": {
                    "class": "Default",
                    "pads": [{}, {}],
                    "pad_refs": ["U1", "U2"],
                    "track_length_mm": 0.0,
                    "track_count": 0,
                    "via_count": 0,
                    "zones": [],
                },
                "DQ2": {
                    "class": "Default",
                    "pads": [{}, {}],
                    "pad_refs": ["U1", "U2"],
                    "track_length_mm": 0.0,
                    "track_count": 0,
                    "via_count": 0,
                    "zones": [],
                },
            },
        }
    )

    result = commands.extract_routing_intents({})

    assert result["success"] is True
    assert result["byIntent"]["HS_SINGLE"] == ["DQ0", "DQ1", "DQ2"]
    assert result["inferredMatchedLengthGroups"][0]["nets"] == ["DQ0", "DQ1", "DQ2"]
    assert result["inferredMatchedLengthGroups"][0]["maxSkewMm"] == 0.08


def test_detect_backends_prefers_external_orthoroute_with_gpu(monkeypatch):
    freerouting = MagicMock()
    freerouting.check_freerouting.return_value = {
        "ready": True,
        "execution_mode": "direct",
    }
    commands = AutorouteCFHACommands(freerouting_commands=freerouting, ipc_board_api=MagicMock())

    monkeypatch.setenv("ORTHOROUTE_BIN", "/usr/local/bin/orthoroute")
    monkeypatch.setattr("shutil.which", lambda name: name if name in {"nvidia-smi", "/usr/local/bin/orthoroute"} else None)

    class _Proc:
        returncode = 0
        stdout = "NVIDIA GeForce RTX 3060\n"
        stderr = ""

    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: _Proc())

    backends = commands._detect_backends({})

    assert backends.ipc_available is True
    assert backends.gpu_available is True
    assert backends.external_orthoroute == "/usr/local/bin/orthoroute"
    assert backends.critical_router_default == "orthoroute-external"


def test_generate_constraints_clamps_power_rule_to_existing_board_width(tmp_path):
    commands = AutorouteCFHACommands()
    result = commands.generate_routing_constraints(
        {
            "intentResult": {
                "success": True,
                "boardPath": str(tmp_path / "demo.kicad_pcb"),
                "profiles": ["generic_2layer", "power"],
                "interfaces": [],
                "analysisSummary": {"copperLayers": ["F.Cu", "B.Cu"]},
                "byIntent": {"POWER_DC": ["+5V"], "GROUND": ["GND"]},
                "intents": [
                    {"net_name": "+5V", "intent": "POWER_DC", "track_length_mm": 10.0},
                    {"net_name": "GND", "intent": "GROUND", "track_length_mm": 0.0},
                ],
                "netInventory": {
                    "+5V": {"min_track_width_mm": 0.5},
                    "GND": {"min_track_width_mm": None},
                },
            }
        }
    )

    assert result["success"] is True
    assert result["constraints"]["derived"]["powerTargetWidthMm"] == 1.0
    assert result["constraints"]["derived"]["powerRuleMinWidthMm"] == 0.5
    power_rule = next(
        rule for rule in result["constraints"]["compiledRules"] if rule["name"] == "cfha_power_min_width"
    )
    assert power_rule["min"] == 0.5


def test_generate_constraints_respects_explicit_empty_exclusion_list(tmp_path):
    commands = AutorouteCFHACommands()
    result = commands.generate_routing_constraints(
        {
            "excludeFromFreeRouting": [],
            "intentResult": {
                "success": True,
                "boardPath": str(tmp_path / "demo.kicad_pcb"),
                "profiles": ["generic_2layer"],
                "interfaces": [],
                "analysisSummary": {"copperLayers": ["F.Cu", "B.Cu"]},
                "byIntent": {"POWER_DC": ["VIN"], "GROUND": ["GND"]},
                "intents": [
                    {"net_name": "VIN", "intent": "POWER_DC", "track_length_mm": 2.0},
                    {"net_name": "GND", "intent": "GROUND", "track_length_mm": 0.0},
                ],
                "netInventory": {},
            },
        }
    )

    assert result["success"] is True
    assert result["constraints"]["excludeFromFreeRouting"] == []


def test_generate_constraints_adds_rf_rules_and_policy(tmp_path):
    commands = AutorouteCFHACommands()
    result = commands.generate_routing_constraints(
        {
            "intentResult": {
                "success": True,
                "boardPath": str(tmp_path / "rf_demo.kicad_pcb"),
                "profiles": ["rf_mixed_signal"],
                "interfaces": [],
                "analysisSummary": {"copperLayers": ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"]},
                "byIntent": {
                    "RF": ["RF_IN"],
                    "ANALOG_SENSITIVE": ["ADC_IN"],
                    "POWER_SWITCHING": ["SW"],
                },
                "intents": [
                    {"net_name": "RF_IN", "intent": "RF", "track_length_mm": 0.0},
                    {"net_name": "ADC_IN", "intent": "ANALOG_SENSITIVE", "track_length_mm": 0.0},
                    {"net_name": "SW", "intent": "POWER_SWITCHING", "track_length_mm": 0.0},
                ],
                "netInventory": {},
            }
        }
    )

    assert result["success"] is True
    rules = {rule["name"]: rule for rule in result["constraints"]["compiledRules"]}
    assert rules["cfha_rf_via_limit"]["max"] == 1
    assert rules["cfha_rf_clearance"]["min"] == 2.0
    assert rules["cfha_switching_isolation"]["min"] == 2.0
    assert result["constraints"]["policy"]["criticalOrdering"] == [
        "intent_priority",
        "escape_complexity",
        "breakout_pressure",
        "reference_alignment",
        "local_congestion",
    ]
    assert "cfha_rf_clearance" in result["constraints"]["policy"]["compiledRuleFamilies"]


def test_generate_constraints_excludes_peer_nets_from_clearance_rules(tmp_path):
    commands = AutorouteCFHACommands()
    result = commands.generate_routing_constraints(
        {
            "intentResult": {
                "success": True,
                "boardPath": str(tmp_path / "guard_demo.kicad_pcb"),
                "profiles": ["high_speed_digital", "rf_mixed_signal"],
                "interfaces": [],
                "analysisSummary": {"copperLayers": ["F.Cu", "B.Cu"]},
                "byIntent": {
                    "HS_DIFF": ["USB_D_N", "USB_D_P"],
                    "RF": ["RF_IN"],
                    "ANALOG_SENSITIVE": ["ADC_IN"],
                    "POWER_SWITCHING": ["SW"],
                    "GROUND": ["AGND", "GND", "PGND"],
                },
                "intents": [
                    {"net_name": "USB_D_P", "intent": "HS_DIFF", "track_length_mm": 0.0, "diff_partner": "USB_D_N"},
                    {"net_name": "USB_D_N", "intent": "HS_DIFF", "track_length_mm": 0.0, "diff_partner": "USB_D_P"},
                    {"net_name": "RF_IN", "intent": "RF", "track_length_mm": 0.0},
                    {"net_name": "ADC_IN", "intent": "ANALOG_SENSITIVE", "track_length_mm": 0.0},
                    {"net_name": "SW", "intent": "POWER_SWITCHING", "track_length_mm": 0.0},
                    {"net_name": "AGND", "intent": "GROUND", "track_length_mm": 0.0},
                    {"net_name": "GND", "intent": "GROUND", "track_length_mm": 0.0},
                    {"net_name": "PGND", "intent": "GROUND", "track_length_mm": 0.0},
                ],
                "netInventory": {},
            }
        }
    )

    assert result["success"] is True
    rules = {rule["name"]: rule for rule in result["constraints"]["compiledRules"]}
    assert "B.NetName != 'USB_D_P'" in rules["cfha_crosstalk_guard"]["condition"]
    assert "B.NetName != 'USB_D_N'" in rules["cfha_crosstalk_guard"]["condition"]
    assert "B.NetName != 'GND'" in rules["cfha_crosstalk_guard"]["condition"]


def test_generate_constraints_auto_infers_bus_groups_and_allows_user_override(tmp_path):
    commands = AutorouteCFHACommands()
    result = commands.generate_routing_constraints(
        {
            "matchedLengthGroups": [
                {"nets": ["DQ0", "DQ1", "DQ2"], "maxSkewMm": 0.05, "type": "bus_manual"}
            ],
            "intentResult": {
                "success": True,
                "boardPath": str(tmp_path / "ddr_demo.kicad_pcb"),
                "profiles": ["generic_4layer"],
                "interfaces": ["DDR4"],
                "analysisSummary": {"copperLayers": ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"]},
                "byIntent": {
                    "HS_SINGLE": ["DQ0", "DQ1", "DQ2"],
                    "HS_DIFF": ["DQS_P", "DQS_N"],
                },
                "intents": [
                    {"net_name": "DQ0", "intent": "HS_SINGLE", "track_length_mm": 0.0},
                    {"net_name": "DQ1", "intent": "HS_SINGLE", "track_length_mm": 0.0},
                    {"net_name": "DQ2", "intent": "HS_SINGLE", "track_length_mm": 0.0},
                    {"net_name": "DQS_P", "intent": "HS_DIFF", "track_length_mm": 0.0, "diff_partner": "DQS_N"},
                    {"net_name": "DQS_N", "intent": "HS_DIFF", "track_length_mm": 0.0, "diff_partner": "DQS_P"},
                ],
                "inferredMatchedLengthGroups": [
                    {"nets": ["DQ0", "DQ1", "DQ2"], "maxSkewMm": 0.08, "type": "bus_auto"}
                ],
                "netInventory": {},
            },
        }
    )

    assert result["success"] is True
    groups = {
        tuple(group["nets"]): group
        for group in result["constraints"]["matchedLengthGroups"]
    }
    assert groups[("DQS_N", "DQS_P")]["type"] == "diff_pair"
    assert groups[("DQ0", "DQ1", "DQ2")]["type"] == "bus_manual"
    assert groups[("DQ0", "DQ1", "DQ2")]["maxSkewMm"] == 0.05


def test_generate_constraints_emits_reference_planning(tmp_path):
    commands = AutorouteCFHACommands()
    result = commands.generate_routing_constraints(
        {
            "intentResult": {
                "success": True,
                "boardPath": str(tmp_path / "reference_plan_demo.kicad_pcb"),
                "profiles": ["generic_4layer", "high_speed_digital"],
                "interfaces": ["USB2"],
                "analysisSummary": {
                    "copperLayers": ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"],
                    "splitRiskLayers": ["In2.Cu"],
                },
                "byIntent": {
                    "HS_DIFF": ["USB_D_N", "USB_D_P"],
                    "GROUND": ["GND"],
                },
                "intents": [
                    {"net_name": "USB_D_P", "intent": "HS_DIFF", "track_length_mm": 0.0, "diff_partner": "USB_D_N"},
                    {"net_name": "USB_D_N", "intent": "HS_DIFF", "track_length_mm": 0.0, "diff_partner": "USB_D_P"},
                    {"net_name": "GND", "intent": "GROUND", "track_length_mm": 0.0},
                ],
                "netInventory": {
                    "USB_D_P": {
                        "pads": [
                            {"ref": "J1", "x": 0.0, "y": 0.0},
                            {"ref": "U1", "x": 20.0, "y": 0.0},
                        ],
                        "zones": [],
                    },
                    "USB_D_N": {
                        "pads": [
                            {"ref": "J1", "x": 0.0, "y": 0.45},
                            {"ref": "U1", "x": 20.0, "y": 0.45},
                        ],
                        "zones": [],
                    },
                    "GND": {"pads": [{}], "zones": []},
                },
            }
        }
    )

    assert result["success"] is True
    planning = result["constraints"]["referencePlanning"]
    assert planning["groundNet"] == "GND"
    assert planning["preferredZoneLayer"] == "In1.Cu"
    assert planning["preferredSignalLayer"] == "F.Cu"
    assert planning["shouldAutoCreate"] is True
    assert planning["reason"] == "high_speed_nets_need_reference_plane"
    assert result["constraints"]["policy"]["placementCoupling"]["preferReferenceContinuity"] is True
    assert result["constraints"]["policy"]["placementCoupling"]["avoidSplitReferenceLayers"] is True


def test_generate_constraints_prefers_local_ground_domain_for_reference_planning(tmp_path):
    commands = AutorouteCFHACommands()
    result = commands.generate_routing_constraints(
        {
            "intentResult": {
                "success": True,
                "boardPath": str(tmp_path / "reference_domain_demo.kicad_pcb"),
                "profiles": ["generic_4layer", "high_speed_digital"],
                "interfaces": ["USB2"],
                "analysisSummary": {
                    "copperLayers": ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"],
                    "splitRiskLayers": ["In2.Cu"],
                },
                "byIntent": {
                    "HS_DIFF": ["USB_D_N", "USB_D_P"],
                    "GROUND": ["AGND", "GND", "PGND"],
                },
                "intents": [
                    {
                        "net_name": "USB_D_P",
                        "intent": "HS_DIFF",
                        "track_length_mm": 0.0,
                        "diff_partner": "USB_D_N",
                        "component_refs": ["J1", "U1"],
                    },
                    {
                        "net_name": "USB_D_N",
                        "intent": "HS_DIFF",
                        "track_length_mm": 0.0,
                        "diff_partner": "USB_D_P",
                        "component_refs": ["J1", "U1"],
                    },
                    {"net_name": "AGND", "intent": "GROUND", "track_length_mm": 0.0},
                    {"net_name": "GND", "intent": "GROUND", "track_length_mm": 0.0},
                    {"net_name": "PGND", "intent": "GROUND", "track_length_mm": 0.0},
                ],
                "netInventory": {
                    "USB_D_P": {
                        "pad_refs": ["J1", "U1"],
                        "pads": [
                            {"ref": "J1", "x": 0.0, "y": 0.0},
                            {"ref": "U1", "x": 20.0, "y": 0.0},
                        ],
                        "zones": [],
                    },
                    "USB_D_N": {
                        "pad_refs": ["J1", "U1"],
                        "pads": [
                            {"ref": "J1", "x": 0.0, "y": 0.45},
                            {"ref": "U1", "x": 20.0, "y": 0.45},
                        ],
                        "zones": [],
                    },
                    "AGND": {
                        "pad_refs": ["J1", "U1"],
                        "pads": [
                            {"ref": "J1", "x": 0.0, "y": 1.0},
                            {"ref": "U1", "x": 20.0, "y": 1.0},
                        ],
                        "zones": [],
                    },
                    "GND": {
                        "pad_refs": ["U2", "U3"],
                        "pads": [
                            {"ref": "U2", "x": 60.0, "y": 40.0},
                            {"ref": "U3", "x": 65.0, "y": 45.0},
                        ],
                        "zones": [{"net": "GND", "layer": "In1.Cu"}],
                    },
                    "PGND": {
                        "pad_refs": ["U4"],
                        "pads": [{"ref": "U4", "x": 75.0, "y": 60.0}],
                        "zones": [],
                    },
                },
            }
        }
    )

    assert result["success"] is True
    planning = result["constraints"]["referencePlanning"]
    assert planning["groundNet"] == "AGND"
    assert planning["groundNetSelection"]["basis"] == "local_overlap"
    assert planning["groundNetSelection"]["sensitiveRefs"] == ["J1", "U1"]
    assert planning["existingGroundZoneLayers"] == []
    assert planning["otherGroundZoneLayers"] == ["In1.Cu"]
    assert planning["preferredZoneLayer"] == "In1.Cu"
    assert planning["shouldAutoCreate"] is True
    assert planning["reason"] == "selected_ground_net_needs_local_reference_plane"
    assert planning["preferredEntryEdge"] == "left"
    assert planning["topologyCueSource"] == "pad_centroid"
    assert planning["referenceContinuityScore"] > 0.0


def test_generate_constraints_emits_reference_entry_edge_from_selected_zone_affinity(tmp_path):
    commands = AutorouteCFHACommands()
    result = commands.generate_routing_constraints(
        {
            "intentResult": {
                "success": True,
                "boardPath": str(tmp_path / "reference_entry_edge_demo.kicad_pcb"),
                "profiles": ["generic_4layer", "high_speed_digital"],
                "interfaces": ["USB2"],
                "analysisSummary": {
                    "copperLayers": ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"],
                    "splitRiskLayers": ["In2.Cu"],
                },
                "byIntent": {
                    "HS_SINGLE": ["USB_CLK"],
                    "GROUND": ["GND"],
                },
                "intents": [
                    {
                        "net_name": "USB_CLK",
                        "intent": "HS_SINGLE",
                        "track_length_mm": 0.0,
                        "component_refs": ["J1", "U1"],
                    },
                    {"net_name": "GND", "intent": "GROUND", "track_length_mm": 0.0},
                ],
                "netInventory": {
                    "USB_CLK": {
                        "pad_refs": ["J1", "U1"],
                        "pads": [
                            {"ref": "J1", "x": 1.0, "y": 4.0},
                            {"ref": "U1", "x": 12.0, "y": 4.0},
                        ],
                        "zones": [],
                    },
                    "GND": {
                        "pad_refs": ["J1", "U1"],
                        "pads": [
                            {"ref": "J1", "x": 0.0, "y": 1.0},
                            {"ref": "U1", "x": 15.0, "y": 1.0},
                        ],
                        "zones": [
                            {
                                "net": "GND",
                                "layer": "In1.Cu",
                                "edgeBias": -0.85,
                                "preferredEdge": "left",
                                "leftArea": 42.0,
                                "rightArea": 0.0,
                                "centroidXmm": 6.0,
                            }
                        ],
                    },
                },
            }
        }
    )

    assert result["success"] is True
    planning = result["constraints"]["referencePlanning"]
    assert planning["groundNet"] == "GND"
    assert planning["preferredEntryEdge"] == "left"
    assert planning["entryEdgeBias"] == -0.85
    assert planning["referenceContinuityScore"] == 0.85
    assert planning["topologyCueSource"] == "zone_affinity"
    assert planning["groundCentroidXmm"] == 6.0


def test_generate_constraints_prefers_edge_low_pressure_signal_layer_for_reference(tmp_path):
    commands = AutorouteCFHACommands()
    result = commands.generate_routing_constraints(
        {
            "intentResult": {
                "success": True,
                "boardPath": str(tmp_path / "signal_layer_demo.kicad_pcb"),
                "profiles": ["generic_4layer", "high_speed_digital"],
                "interfaces": ["USB2"],
                "analysisSummary": {
                    "copperLayers": ["F.Cu", "In1.Cu", "B.Cu"],
                    "splitRiskLayers": [],
                    "trackPressureByLayer": {"F.Cu": 24.0, "B.Cu": 8.0},
                    "edgePressureByLayer": {
                        "F.Cu": {"total": 24.0, "left": 18.0, "right": 3.0, "center": 3.0},
                        "B.Cu": {"total": 8.0, "left": 1.5, "right": 4.0, "center": 2.5},
                    },
                },
                "byIntent": {
                    "HS_SINGLE": ["USB_CLK"],
                    "GROUND": ["AGND"],
                },
                "intents": [
                    {
                        "net_name": "USB_CLK",
                        "intent": "HS_SINGLE",
                        "track_length_mm": 0.0,
                        "component_refs": ["J1", "U1"],
                    },
                    {"net_name": "AGND", "intent": "GROUND", "track_length_mm": 0.0},
                ],
                "netInventory": {
                    "USB_CLK": {
                        "pad_refs": ["J1", "U1"],
                        "pads": [
                            {"ref": "J1", "x": 1.0, "y": 4.0},
                            {"ref": "U1", "x": 12.0, "y": 4.0},
                        ],
                        "zones": [],
                    },
                    "AGND": {
                        "pad_refs": ["J1", "U1"],
                        "pads": [
                            {"ref": "J1", "x": 0.5, "y": 1.0},
                            {"ref": "U1", "x": 13.0, "y": 1.0},
                        ],
                        "zones": [
                            {
                                "net": "AGND",
                                "layer": "In1.Cu",
                                "edgeBias": -0.9,
                                "preferredEdge": "left",
                                "leftArea": 40.0,
                                "rightArea": 0.0,
                                "centroidXmm": 6.0,
                            }
                        ],
                    },
                },
            }
        }
    )

    assert result["success"] is True
    planning = result["constraints"]["referencePlanning"]
    assert planning["preferredZoneLayer"] == "In1.Cu"
    assert planning["preferredEntryEdge"] == "left"
    assert planning["preferredSignalLayer"] == "B.Cu"
    assert planning["signalLayerCandidates"][0]["layer"] == "B.Cu"
    assert planning["signalLayerCandidates"][0]["weightedEdgePressure"] < planning["signalLayerCandidates"][1]["weightedEdgePressure"]


def test_generate_constraints_skips_coupled_diff_rules_for_ineligible_endpoint_pitch(tmp_path):
    commands = AutorouteCFHACommands()
    result = commands.generate_routing_constraints(
        {
            "criticalWidthMm": 0.25,
            "intentResult": {
                "success": True,
                "boardPath": str(tmp_path / "diff_demo.kicad_pcb"),
                "profiles": ["high_speed_digital"],
                "interfaces": ["USB2"],
                "analysisSummary": {"copperLayers": ["F.Cu", "B.Cu"]},
                "byIntent": {"HS_DIFF": ["USB_D_N", "USB_D_P"]},
                "intents": [
                    {
                        "net_name": "USB_D_P",
                        "intent": "HS_DIFF",
                        "track_length_mm": 12.0,
                        "diff_partner": "USB_D_N",
                    },
                    {
                        "net_name": "USB_D_N",
                        "intent": "HS_DIFF",
                        "track_length_mm": 12.2,
                        "diff_partner": "USB_D_P",
                    },
                ],
                "netInventory": {
                    "USB_D_P": {
                        "pads": [
                            {"ref": "J1", "pad": "1", "x": 0.0, "y": 0.0},
                            {"ref": "U1", "pad": "1", "x": 20.0, "y": 0.0},
                        ]
                    },
                    "USB_D_N": {
                        "pads": [
                            {"ref": "J1", "pad": "2", "x": 0.0, "y": 2.0},
                            {"ref": "U1", "pad": "2", "x": 20.0, "y": 2.0},
                        ]
                    },
                },
            },
        }
    )

    assert result["success"] is True
    rules = {rule["name"]: rule for rule in result["constraints"]["compiledRules"]}
    assert "cfha_hs_diff_gap" not in rules
    assert "cfha_hs_diff_uncoupled" not in rules
    assert rules["cfha_hs_diff_skew"]["max"] == 0.2


def test_parse_unconnected_item_blocks_extracts_track_candidates():
    report = """
** Drc report **
[unconnected_items]: Missing connection between items
    Local override; Severity: error
    @(36.0000 mm, 14.1750 mm): Track [GND] on F.Cu, length 7.0250 mm
    @(56.8875 mm, 20.5375 mm): Track [GND] on F.Cu, length 27.9125 mm
"""

    issues = AutorouteCFHACommands._parse_unconnected_item_blocks(report)

    assert len(issues) == 1
    assert issues[0]["type"] == "unconnected_items"
    assert [item["net"] for item in issues[0]["items"]] == ["GND", "GND"]
    assert issues[0]["items"][0]["layer"] == "F.Cu"


def test_autoroute_default_pipeline_returns_artifacts(monkeypatch, tmp_path):
    board = MagicMock()
    board.GetFileName.return_value = str(tmp_path / "demo.kicad_pcb")
    commands = AutorouteCFHACommands(board=board)

    monkeypatch.setattr(
        commands,
        "_ensure_board",
        lambda params: (board, Path(board.GetFileName()), None),
    )
    monkeypatch.setattr(
        commands,
        "analyze_board_routing_context",
        lambda params: {
            "success": True,
            "boardPath": str(tmp_path / "demo.kicad_pcb"),
            "summary": {"copperLayers": ["F.Cu", "B.Cu"]},
            "backends": {"critical_router_default": "orthoroute-internal"},
        },
    )
    monkeypatch.setattr(
        commands,
        "extract_routing_intents",
        lambda params: {
            "success": True,
            "boardPath": str(tmp_path / "demo.kicad_pcb"),
            "analysisSummary": {"copperLayers": ["F.Cu", "B.Cu"]},
            "byIntent": {"POWER_DC": ["VIN"], "GROUND": ["GND"]},
            "intents": [
                {
                    "net_name": "VIN",
                    "intent": "POWER_DC",
                    "track_length_mm": 2.0,
                }
            ],
        },
    )
    monkeypatch.setattr(
        commands,
        "generate_routing_constraints",
        lambda params: {
            "success": True,
            "constraintsPath": str(tmp_path / "demo.routing_constraints.json"),
            "constraints": {
                "boardPath": str(tmp_path / "demo.kicad_pcb"),
                "criticalClasses": ["POWER_DC"],
                "excludeFromFreeRouting": ["GND"],
            },
        },
    )
    monkeypatch.setattr(
        commands,
        "generate_kicad_dru",
        lambda params: {
            "success": True,
            "rulesPath": str(tmp_path / "demo.kicad_dru"),
        },
    )
    monkeypatch.setattr(
        commands,
        "route_critical_nets",
        lambda params: {"success": True, "routed": [], "skipped": []},
    )
    monkeypatch.setattr(
        commands,
        "verify_routing_qor",
        lambda params: {
            "success": True,
            "completionRate": 1.0,
            "drc": {"errors": 0, "warnings": 0},
            "metrics": {"wirelengthMm": 12.3, "viaCount": 0},
            "flags": {},
            "reportPath": str(tmp_path / "demo.autoroute_cfha.json"),
        },
    )
    monkeypatch.setattr(
        commands,
        "post_tune_routes",
        lambda params: {"success": True, "actions": ["build_connectivity"]},
    )

    result = commands.autoroute_default({"boardPath": str(tmp_path / "demo.kicad_pcb")})

    assert result["success"] is True
    assert result["completionRate"] == 1.0
    assert result["artifacts"]["rulesPath"].endswith(".kicad_dru")
    assert result["metrics"]["runtimeSec"] >= 0


def test_autoroute_default_enables_post_tune_healing_defaults(monkeypatch, tmp_path):
    board = MagicMock()
    board.GetFileName.return_value = str(tmp_path / "demo.kicad_pcb")
    commands = AutorouteCFHACommands(board=board)

    monkeypatch.setattr(
        commands,
        "_ensure_board",
        lambda params: (board, Path(board.GetFileName()), None),
    )
    monkeypatch.setattr(
        commands,
        "analyze_board_routing_context",
        lambda params: {
            "success": True,
            "boardPath": str(tmp_path / "demo.kicad_pcb"),
            "summary": {"copperLayers": ["F.Cu", "B.Cu"]},
            "backends": {"critical_router_default": "orthoroute-internal"},
        },
    )
    monkeypatch.setattr(
        commands,
        "extract_routing_intents",
        lambda params: {
            "success": True,
            "boardPath": str(tmp_path / "demo.kicad_pcb"),
            "analysisSummary": {"copperLayers": ["F.Cu", "B.Cu"]},
            "byIntent": {"GROUND": ["GND"]},
            "intents": [],
        },
    )
    monkeypatch.setattr(
        commands,
        "generate_routing_constraints",
        lambda params: {
            "success": True,
            "constraintsPath": str(tmp_path / "demo.routing_constraints.json"),
            "constraints": {"boardPath": str(tmp_path / "demo.kicad_pcb"), "criticalClasses": []},
        },
    )
    monkeypatch.setattr(
        commands,
        "generate_kicad_dru",
        lambda params: {"success": True, "rulesPath": str(tmp_path / "demo.kicad_dru")},
    )
    monkeypatch.setattr(
        commands,
        "route_critical_nets",
        lambda params: {"success": True, "routed": [], "skipped": []},
    )

    captured_post_params = {}

    def _post(params):
        captured_post_params.update(params)
        return {"success": True, "actions": ["build_connectivity"]}

    monkeypatch.setattr(commands, "post_tune_routes", _post)
    monkeypatch.setattr(
        commands,
        "verify_routing_qor",
        lambda params: {
            "success": True,
            "completionRate": 1.0,
            "drc": {"errors": 0, "warnings": 0},
            "metrics": {"wirelengthMm": 1.0, "viaCount": 0},
            "flags": {},
            "reportPath": str(tmp_path / "demo.autoroute_cfha.json"),
        },
    )

    result = commands.autoroute_default({"boardPath": str(tmp_path / "demo.kicad_pcb")})

    assert result["success"] is True
    assert captured_post_params["refillZones"] is True
    assert captured_post_params["autoTuneMatchedLengths"] is True
    assert captured_post_params["autoCreateReferenceZones"] is True
    assert captured_post_params["matchedLengthMinExtraMm"] == 0.3
    assert captured_post_params["matchedLengthMaxGroupSize"] == 4
    assert captured_post_params["autoHealSupportNets"] is True
    assert captured_post_params["healingPasses"] == 2
    assert captured_post_params["maxHealingViasPerNet"] == 4
    assert "constraintsResult" in captured_post_params


def test_route_critical_nets_prioritizes_escape_complexity_before_congestion(monkeypatch, tmp_path):
    def _footprint(ref: str, pad_count: int):
        footprint = MagicMock()
        footprint.GetReference.return_value = ref
        footprint.Pads.return_value = [object()] * pad_count
        return footprint

    board = MagicMock()
    board.GetFileName.return_value = str(tmp_path / "demo.kicad_pcb")
    board.GetFootprints.return_value = [
        _footprint("J1", 24),
        _footprint("U1", 64),
        _footprint("U2", 8),
        _footprint("U3", 8),
    ]

    routed_order = []
    routing_commands = MagicMock()

    def _route(params):
        routed_order.append(params["net"])
        return {"success": True}

    routing_commands.route_pad_to_pad.side_effect = _route
    commands = AutorouteCFHACommands(board=board, routing_commands=routing_commands)

    monkeypatch.setattr(
        commands,
        "_ensure_board",
        lambda params: (board, Path(board.GetFileName()), None),
    )
    monkeypatch.setattr(
        commands,
        "_collect_inventory",
        lambda _board: {
            "USB_CLK": {
                "pads": [
                    {"ref": "J1", "pad": "1", "x": 0.0, "y": 0.0},
                    {"ref": "U1", "pad": "1", "x": 10.0, "y": 0.0},
                ]
            },
            "CTRL": {
                "pads": [
                    {"ref": "U2", "pad": "1", "x": 30.0, "y": 20.0},
                    {"ref": "U3", "pad": "1", "x": 45.0, "y": 20.0},
                ]
            },
        },
    )
    monkeypatch.setattr(commands, "_estimate_net_congestion", lambda pads, _board: 0.0)
    monkeypatch.setattr(commands, "_estimate_breakout_pressure", lambda net, pads, board, fps: 0.0)

    result = commands.route_critical_nets(
        {
            "constraintsResult": {
                "success": True,
                "constraints": {
                    "criticalClasses": ["HS_SINGLE"],
                    "defaults": {"power_min_width_mm": 0.8},
                    "derived": {},
                    "intents": [
                        {
                            "net_name": "CTRL",
                            "intent": "HS_SINGLE",
                            "track_length_mm": 0.0,
                            "priority": 85,
                        },
                        {
                            "net_name": "USB_CLK",
                            "intent": "HS_SINGLE",
                            "track_length_mm": 0.0,
                            "priority": 85,
                        },
                    ],
                },
            }
        }
    )

    assert result["success"] is True
    assert routed_order == ["USB_CLK", "CTRL"]


def test_route_critical_nets_prioritizes_breakout_pressure_after_escape(monkeypatch, tmp_path):
    def _footprint(ref: str, pad_count: int):
        footprint = MagicMock()
        footprint.GetReference.return_value = ref
        footprint.Pads.return_value = [object()] * pad_count
        return footprint

    bbox = MagicMock()
    bbox.GetLeft.return_value = 0
    bbox.GetTop.return_value = 0
    bbox.GetRight.return_value = int(60 * 1_000_000)
    bbox.GetBottom.return_value = int(40 * 1_000_000)

    board = MagicMock()
    board.GetFileName.return_value = str(tmp_path / "demo.kicad_pcb")
    board.GetBoardEdgesBoundingBox.return_value = bbox
    board.GetFootprints.return_value = [
        _footprint("J1", 24),
        _footprint("J2", 24),
        _footprint("U1", 8),
        _footprint("U2", 8),
    ]

    routed_order = []
    routing_commands = MagicMock()

    def _route(params):
        routed_order.append(params["net"])
        return {"success": True}

    routing_commands.route_pad_to_pad.side_effect = _route
    commands = AutorouteCFHACommands(board=board, routing_commands=routing_commands)

    monkeypatch.setattr(
        commands,
        "_ensure_board",
        lambda params: (board, Path(board.GetFileName()), None),
    )
    monkeypatch.setattr(
        commands,
        "_collect_inventory",
        lambda _board: {
            "EDGE_NET": {
                "pads": [
                    {"ref": "J1", "pad": "1", "x": 1.0, "y": 10.0},
                    {"ref": "U1", "pad": "1", "x": 12.0, "y": 10.0},
                ]
            },
            "CORE_NET": {
                "pads": [
                    {"ref": "J2", "pad": "1", "x": 28.0, "y": 20.0},
                    {"ref": "U2", "pad": "1", "x": 36.0, "y": 20.0},
                ]
            },
        },
    )
    monkeypatch.setattr(commands, "_estimate_net_congestion", lambda pads, _board: 0.0)
    monkeypatch.setattr(commands, "_estimate_escape_complexity", lambda net, pads, fps: 5.0)

    result = commands.route_critical_nets(
        {
            "constraintsResult": {
                "success": True,
                "constraints": {
                    "criticalClasses": ["HS_SINGLE"],
                    "defaults": {"power_min_width_mm": 0.8},
                    "derived": {},
                    "intents": [
                        {
                            "net_name": "CORE_NET",
                            "intent": "HS_SINGLE",
                            "track_length_mm": 0.0,
                            "priority": 85,
                        },
                        {
                            "net_name": "EDGE_NET",
                            "intent": "HS_SINGLE",
                            "track_length_mm": 0.0,
                            "priority": 85,
                        },
                    ],
                },
            }
        }
    )

    assert result["success"] is True
    assert routed_order == ["EDGE_NET", "CORE_NET"]


def test_route_critical_nets_prioritizes_reference_alignment_after_breakout(monkeypatch, tmp_path):
    def _footprint(ref: str, pad_count: int):
        footprint = MagicMock()
        footprint.GetReference.return_value = ref
        footprint.Pads.return_value = [object()] * pad_count
        return footprint

    bbox = MagicMock()
    bbox.GetLeft.return_value = 0
    bbox.GetTop.return_value = 0
    bbox.GetRight.return_value = int(60 * 1_000_000)
    bbox.GetBottom.return_value = int(40 * 1_000_000)

    board = MagicMock()
    board.GetFileName.return_value = str(tmp_path / "demo.kicad_pcb")
    board.GetBoardEdgesBoundingBox.return_value = bbox
    board.GetFootprints.return_value = [
        _footprint("J1", 16),
        _footprint("J2", 16),
        _footprint("U1", 8),
        _footprint("U2", 8),
    ]

    routed_order = []
    routing_commands = MagicMock()

    def _route(params):
        routed_order.append(params["net"])
        return {"success": True}

    routing_commands.route_pad_to_pad.side_effect = _route
    commands = AutorouteCFHACommands(board=board, routing_commands=routing_commands)

    monkeypatch.setattr(
        commands,
        "_ensure_board",
        lambda params: (board, Path(board.GetFileName()), None),
    )
    monkeypatch.setattr(
        commands,
        "_collect_inventory",
        lambda _board: {
            "LEFT_NET": {
                "pads": [
                    {"ref": "J1", "pad": "1", "x": 1.0, "y": 10.0},
                    {"ref": "U1", "pad": "1", "x": 8.0, "y": 10.0},
                ]
            },
            "RIGHT_NET": {
                "pads": [
                    {"ref": "J2", "pad": "1", "x": 46.0, "y": 20.0},
                    {"ref": "U2", "pad": "1", "x": 52.0, "y": 20.0},
                ]
            },
        },
    )
    monkeypatch.setattr(commands, "_estimate_net_congestion", lambda pads, _board: 0.0)
    monkeypatch.setattr(commands, "_estimate_escape_complexity", lambda net, pads, fps: 5.0)
    monkeypatch.setattr(commands, "_estimate_breakout_pressure", lambda net, pads, board, fps: 2.0)

    result = commands.route_critical_nets(
        {
            "constraintsResult": {
                "success": True,
                "constraints": {
                    "criticalClasses": ["HS_SINGLE"],
                    "referencePlanning": {
                        "preferredEntryEdge": "left",
                        "referenceContinuityScore": 0.8,
                        "topologyCueSource": "zone_affinity",
                        "highSpeedNets": ["LEFT_NET", "RIGHT_NET"],
                        "preferredSignalLayer": "F.Cu",
                    },
                    "defaults": {"power_min_width_mm": 0.8},
                    "derived": {},
                    "intents": [
                        {
                            "net_name": "RIGHT_NET",
                            "intent": "HS_SINGLE",
                            "track_length_mm": 0.0,
                            "priority": 85,
                        },
                        {
                            "net_name": "LEFT_NET",
                            "intent": "HS_SINGLE",
                            "track_length_mm": 0.0,
                            "priority": 85,
                        },
                    ],
                },
            }
        }
    )

    assert result["success"] is True
    assert routed_order == ["LEFT_NET", "RIGHT_NET"]
    assert result["ordering"][0]["net"] == "LEFT_NET"
    assert result["ordering"][0]["referenceAlignment"] > result["ordering"][1]["referenceAlignment"]


def test_route_critical_nets_selects_per_net_layer_from_signal_candidates(monkeypatch, tmp_path):
    def _footprint(ref: str, pad_count: int):
        footprint = MagicMock()
        footprint.GetReference.return_value = ref
        footprint.Pads.return_value = [object()] * pad_count
        return footprint

    bbox = MagicMock()
    bbox.GetLeft.return_value = 0
    bbox.GetTop.return_value = 0
    bbox.GetRight.return_value = int(80 * 1_000_000)
    bbox.GetBottom.return_value = int(40 * 1_000_000)

    board = MagicMock()
    board.GetFileName.return_value = str(tmp_path / "demo.kicad_pcb")
    board.GetBoardEdgesBoundingBox.return_value = bbox
    board.GetFootprints.return_value = [
        _footprint("J1", 16),
        _footprint("J2", 16),
        _footprint("U1", 8),
        _footprint("U2", 8),
    ]

    routed_layers = {}
    routing_commands = MagicMock()

    def _route(params):
        routed_layers[params["net"]] = params["layer"]
        return {"success": True}

    routing_commands.route_pad_to_pad.side_effect = _route
    commands = AutorouteCFHACommands(board=board, routing_commands=routing_commands)

    monkeypatch.setattr(
        commands,
        "_ensure_board",
        lambda params: (board, Path(board.GetFileName()), None),
    )
    monkeypatch.setattr(
        commands,
        "_collect_inventory",
        lambda _board: {
            "LEFT_NET": {
                "pads": [
                    {"ref": "J1", "pad": "1", "x": 2.0, "y": 10.0},
                    {"ref": "U1", "pad": "1", "x": 16.0, "y": 10.0},
                ]
            },
            "RIGHT_NET": {
                "pads": [
                    {"ref": "J2", "pad": "1", "x": 64.0, "y": 20.0},
                    {"ref": "U2", "pad": "1", "x": 74.0, "y": 20.0},
                ]
            },
        },
    )
    monkeypatch.setattr(commands, "_estimate_net_congestion", lambda pads, _board: 0.0)
    monkeypatch.setattr(commands, "_estimate_escape_complexity", lambda net, pads, fps: 0.0)
    monkeypatch.setattr(commands, "_estimate_breakout_pressure", lambda net, pads, board, fps: 0.0)

    result = commands.route_critical_nets(
        {
            "constraintsResult": {
                "success": True,
                "constraints": {
                    "criticalClasses": ["HS_SINGLE"],
                    "boardSummary": {
                        "trackPressureByLayer": {"F.Cu": 40.0, "B.Cu": 22.0},
                        "edgePressureByLayer": {
                            "F.Cu": {"left": 30.0, "right": 2.0, "center": 8.0},
                            "B.Cu": {"left": 3.0, "right": 18.0, "center": 4.0},
                        },
                    },
                    "referencePlanning": {
                        "preferredSignalLayer": "B.Cu",
                        "preferredEntryEdge": "left",
                        "referenceContinuityScore": 1.0,
                        "topologyCueSource": "zone_affinity",
                        "signalLayerCandidates": [
                            {
                                "layer": "B.Cu",
                                "splitRisk": False,
                                "adjacencyRank": 0,
                                "totalPressure": 22.0,
                                "edgePressure": 3.0,
                                "weightedEdgePressure": 6.0,
                                "edgeBucket": "left",
                                "outerBiasRank": 1,
                            },
                            {
                                "layer": "F.Cu",
                                "splitRisk": False,
                                "adjacencyRank": 0,
                                "totalPressure": 40.0,
                                "edgePressure": 30.0,
                                "weightedEdgePressure": 60.0,
                                "edgeBucket": "left",
                                "outerBiasRank": 0,
                            },
                        ],
                    },
                    "defaults": {"power_min_width_mm": 0.8},
                    "derived": {},
                    "intents": [
                        {"net_name": "LEFT_NET", "intent": "HS_SINGLE", "track_length_mm": 0.0, "priority": 85},
                        {"net_name": "RIGHT_NET", "intent": "HS_SINGLE", "track_length_mm": 0.0, "priority": 85},
                    ],
                },
            }
        }
    )

    assert result["success"] is True
    assert routed_layers["LEFT_NET"] == "B.Cu"
    assert routed_layers["RIGHT_NET"] == "F.Cu"
    layers = {row["net"]: row["selectedLayer"] for row in result["ordering"]}
    assert layers["LEFT_NET"] == "B.Cu"
    assert layers["RIGHT_NET"] == "F.Cu"


def test_route_critical_nets_locks_diff_pair_to_shared_layer(monkeypatch, tmp_path):
    def _footprint(ref: str, layer_id: int = 0):
        footprint = MagicMock()
        footprint.GetReference.return_value = ref
        footprint.GetLayer.return_value = layer_id
        return footprint

    bbox = MagicMock()
    bbox.GetLeft.return_value = 0
    bbox.GetTop.return_value = 0
    bbox.GetRight.return_value = int(80 * 1_000_000)
    bbox.GetBottom.return_value = int(40 * 1_000_000)

    board = MagicMock()
    board.GetFileName.return_value = str(tmp_path / "diff_pair_layer_lock_demo.kicad_pcb")
    board.GetBoardEdgesBoundingBox.return_value = bbox
    board.GetFootprints.return_value = [_footprint("J1"), _footprint("U1")]
    board.GetLayerName.return_value = ""

    commands = AutorouteCFHACommands(board=board, routing_commands=MagicMock())
    diff_pair_calls = []

    def _route_diff_pair(net_pos, net_neg, *, inventory, constraints, width_mm, layer, board, footprints):
        diff_pair_calls.append(
            {
                "netPos": net_pos,
                "netNeg": net_neg,
                "layer": layer,
                "widthMm": width_mm,
            }
        )
        return {"success": True}

    monkeypatch.setattr(
        commands,
        "_ensure_board",
        lambda params: (board, Path(board.GetFileName()), None),
    )
    monkeypatch.setattr(
        commands,
        "_collect_inventory",
        lambda _board: {
            "USB_D_P": {
                "pads": [
                    {"ref": "J1", "pad": "1", "x": 2.0, "y": 10.0},
                    {"ref": "U1", "pad": "1", "x": 18.0, "y": 10.0},
                ]
            },
            "USB_D_N": {
                "pads": [
                    {"ref": "J1", "pad": "2", "x": 62.0, "y": 10.2},
                    {"ref": "U1", "pad": "2", "x": 78.0, "y": 10.2},
                ]
            },
        },
    )
    monkeypatch.setattr(commands, "_estimate_net_congestion", lambda pads, _board: 0.0)
    monkeypatch.setattr(commands, "_estimate_escape_complexity", lambda net, pads, fps: 0.0)
    monkeypatch.setattr(commands, "_estimate_breakout_pressure", lambda net, pads, board, fps: 0.0)
    monkeypatch.setattr(commands, "_estimate_reference_alignment_pressure", lambda net, pads, board, planning: 0.0)
    monkeypatch.setattr(commands, "_route_diff_pair", _route_diff_pair)

    result = commands.route_critical_nets(
        {
            "constraintsResult": {
                "success": True,
                "constraints": {
                    "criticalClasses": ["HS_DIFF"],
                    "boardSummary": {
                        "trackPressureByLayer": {"F.Cu": 20.0, "B.Cu": 18.0},
                        "edgePressureByLayer": {
                            "F.Cu": {"left": 30.0, "right": 2.0, "center": 12.0},
                            "B.Cu": {"left": 3.0, "right": 25.0, "center": 8.0},
                        },
                    },
                    "referencePlanning": {
                        "preferredSignalLayer": "B.Cu",
                        "preferredEntryEdge": "left",
                        "referenceContinuityScore": 1.0,
                        "signalLayerCandidates": [
                            {
                                "layer": "B.Cu",
                                "splitRisk": False,
                                "adjacencyRank": 0,
                                "totalPressure": 18.0,
                            },
                            {
                                "layer": "F.Cu",
                                "splitRisk": False,
                                "adjacencyRank": 0,
                                "totalPressure": 20.0,
                            },
                        ],
                    },
                    "defaults": {"power_min_width_mm": 0.8},
                    "derived": {},
                    "intents": [
                        {
                            "net_name": "USB_D_P",
                            "intent": "HS_DIFF",
                            "track_length_mm": 0.0,
                            "priority": 90,
                            "diff_partner": "USB_D_N",
                        },
                        {
                            "net_name": "USB_D_N",
                            "intent": "HS_DIFF",
                            "track_length_mm": 0.0,
                            "priority": 90,
                            "diff_partner": "USB_D_P",
                        },
                    ],
                },
            }
        }
    )

    assert result["success"] is True
    assert diff_pair_calls[0]["layer"] == "B.Cu"
    ordering_layers = {row["net"]: row["selectedLayer"] for row in result["ordering"]}
    ordering_sources = {row["net"]: row["selectedLayerSource"] for row in result["ordering"]}
    assert ordering_layers["USB_D_P"] == "B.Cu"
    assert ordering_layers["USB_D_N"] == "B.Cu"
    assert ordering_sources["USB_D_P"] == "diff_pair_locked"
    assert ordering_sources["USB_D_N"] == "diff_pair_locked"
    routed_layers = {row["net"]: row["layer"] for row in result["routed"]}
    routed_sources = {row["net"]: row["layerSource"] for row in result["routed"]}
    assert routed_layers["USB_D_P"] == "B.Cu"
    assert routed_layers["USB_D_N"] == "B.Cu"
    assert routed_sources["USB_D_P"] == "diff_pair_locked"
    assert routed_sources["USB_D_N"] == "diff_pair_locked"


def test_route_critical_nets_prefers_backend_safe_diff_pair_layer(monkeypatch, tmp_path):
    def _footprint(ref: str, layer_id: int = 0):
        footprint = MagicMock()
        footprint.GetReference.return_value = ref
        footprint.GetLayer.return_value = layer_id
        return footprint

    bbox = MagicMock()
    bbox.GetLeft.return_value = 0
    bbox.GetTop.return_value = 0
    bbox.GetRight.return_value = int(80 * 1_000_000)
    bbox.GetBottom.return_value = int(40 * 1_000_000)

    board = MagicMock()
    board.GetFileName.return_value = str(tmp_path / "diff_pair_backend_safe_demo.kicad_pcb")
    board.GetBoardEdgesBoundingBox.return_value = bbox
    board.GetFootprints.return_value = [_footprint("J1", 0), _footprint("U1", 0)]
    board.GetLayerName.side_effect = lambda layer_id: {0: "F.Cu", 31: "B.Cu"}.get(layer_id, "F.Cu")

    commands = AutorouteCFHACommands(board=board, routing_commands=MagicMock())
    diff_pair_calls = []

    def _route_diff_pair(net_pos, net_neg, *, inventory, constraints, width_mm, layer, board, footprints):
        diff_pair_calls.append(
            {
                "netPos": net_pos,
                "netNeg": net_neg,
                "layer": layer,
                "widthMm": width_mm,
            }
        )
        return {"success": True}

    monkeypatch.setattr(
        commands,
        "_ensure_board",
        lambda params: (board, Path(board.GetFileName()), None),
    )
    monkeypatch.setattr(
        commands,
        "_collect_inventory",
        lambda _board: {
            "USB_D_P": {
                "pads": [
                    {"ref": "J1", "pad": "1", "x": 2.0, "y": 10.0},
                    {"ref": "U1", "pad": "1", "x": 18.0, "y": 10.0},
                ]
            },
            "USB_D_N": {
                "pads": [
                    {"ref": "J1", "pad": "2", "x": 2.0, "y": 10.4},
                    {"ref": "U1", "pad": "2", "x": 18.0, "y": 10.4},
                ]
            },
        },
    )
    monkeypatch.setattr(commands, "_estimate_net_congestion", lambda pads, _board: 0.0)
    monkeypatch.setattr(commands, "_estimate_escape_complexity", lambda net, pads, fps: 0.0)
    monkeypatch.setattr(commands, "_estimate_breakout_pressure", lambda net, pads, board, fps: 0.0)
    monkeypatch.setattr(commands, "_estimate_reference_alignment_pressure", lambda net, pads, board, planning: 0.0)
    monkeypatch.setattr(commands, "_route_diff_pair", _route_diff_pair)

    result = commands.route_critical_nets(
        {
            "constraintsResult": {
                "success": True,
                "constraints": {
                    "criticalClasses": ["HS_DIFF"],
                    "boardSummary": {
                        "trackPressureByLayer": {"F.Cu": 40.0, "B.Cu": 8.0},
                        "edgePressureByLayer": {
                            "F.Cu": {"left": 24.0, "right": 8.0, "center": 12.0},
                            "B.Cu": {"left": 2.0, "right": 2.0, "center": 3.0},
                        },
                    },
                    "referencePlanning": {
                        "preferredSignalLayer": "B.Cu",
                        "preferredEntryEdge": "left",
                        "referenceContinuityScore": 1.0,
                        "signalLayerCandidates": [
                            {
                                "layer": "B.Cu",
                                "splitRisk": False,
                                "adjacencyRank": 0,
                                "totalPressure": 8.0,
                            },
                            {
                                "layer": "F.Cu",
                                "splitRisk": False,
                                "adjacencyRank": 0,
                                "totalPressure": 40.0,
                            },
                        ],
                    },
                    "defaults": {"power_min_width_mm": 0.8, "hs_via_limit": 2},
                    "derived": {},
                    "intents": [
                        {
                            "net_name": "USB_D_P",
                            "intent": "HS_DIFF",
                            "track_length_mm": 0.0,
                            "priority": 90,
                            "diff_partner": "USB_D_N",
                        },
                        {
                            "net_name": "USB_D_N",
                            "intent": "HS_DIFF",
                            "track_length_mm": 0.0,
                            "priority": 90,
                            "diff_partner": "USB_D_P",
                        },
                    ],
                },
            }
        }
    )

    assert result["success"] is True
    assert diff_pair_calls[0]["layer"] == "F.Cu"
    assert result["ordering"][0]["selectedLayer"] == "F.Cu"
    assert result["ordering"][0]["transitionPolicy"] == "stay_on_endpoint_layer"
    assert result["ordering"][0]["estimatedViaCountPerNet"] == 0.0
    assert result["routed"][0]["transitionPolicy"] == "stay_on_endpoint_layer"


def test_route_critical_nets_uses_budget_safe_diff_pair_transitions(monkeypatch, tmp_path):
    def _footprint(ref: str, layer_id: int = 0):
        footprint = MagicMock()
        footprint.GetReference.return_value = ref
        footprint.GetLayer.return_value = layer_id
        return footprint

    bbox = MagicMock()
    bbox.GetLeft.return_value = 0
    bbox.GetTop.return_value = 0
    bbox.GetRight.return_value = int(80 * 1_000_000)
    bbox.GetBottom.return_value = int(40 * 1_000_000)

    board = MagicMock()
    board.GetFileName.return_value = str(tmp_path / "diff_pair_transition_budget_demo.kicad_pcb")
    board.GetBoardEdgesBoundingBox.return_value = bbox
    board.GetFootprints.return_value = [_footprint("J1", 1), _footprint("U1", 1)]
    board.GetLayerName.side_effect = lambda layer_id: {0: "F.Cu", 1: "In1.Cu", 31: "B.Cu"}.get(layer_id, "F.Cu")

    commands = AutorouteCFHACommands(board=board, routing_commands=MagicMock())
    diff_pair_calls = []

    def _route_diff_pair(net_pos, net_neg, *, inventory, constraints, width_mm, layer, board, footprints):
        diff_pair_calls.append(
            {
                "netPos": net_pos,
                "netNeg": net_neg,
                "layer": layer,
                "widthMm": width_mm,
            }
        )
        return {"success": True}

    monkeypatch.setattr(
        commands,
        "_ensure_board",
        lambda params: (board, Path(board.GetFileName()), None),
    )
    inventory = {
        "USB_D_P": {
            "pads": [
                {"ref": "J1", "pad": "1", "x": 2.0, "y": 10.0},
                {"ref": "U1", "pad": "1", "x": 18.0, "y": 10.0},
            ]
        },
        "USB_D_N": {
            "pads": [
                {"ref": "J1", "pad": "2", "x": 2.0, "y": 10.4},
                {"ref": "U1", "pad": "2", "x": 18.0, "y": 10.4},
            ]
        },
    }
    monkeypatch.setattr(commands, "_collect_inventory", lambda _board: inventory)
    monkeypatch.setattr(commands, "_estimate_net_congestion", lambda pads, _board: 0.0)
    monkeypatch.setattr(commands, "_estimate_escape_complexity", lambda net, pads, fps: 0.0)
    monkeypatch.setattr(commands, "_estimate_breakout_pressure", lambda net, pads, board, fps: 0.0)
    monkeypatch.setattr(commands, "_estimate_reference_alignment_pressure", lambda net, pads, board, planning: 0.0)
    monkeypatch.setattr(commands, "_route_diff_pair", _route_diff_pair)

    result = commands.route_critical_nets(
        {
            "constraintsResult": {
                "success": True,
                "constraints": {
                    "criticalClasses": ["HS_DIFF"],
                    "boardSummary": {
                        "trackPressureByLayer": {"F.Cu": 40.0, "B.Cu": 8.0},
                        "edgePressureByLayer": {
                            "F.Cu": {"left": 24.0, "right": 8.0, "center": 12.0},
                            "B.Cu": {"left": 2.0, "right": 2.0, "center": 3.0},
                        },
                    },
                    "referencePlanning": {
                        "preferredSignalLayer": "B.Cu",
                        "preferredEntryEdge": "left",
                        "referenceContinuityScore": 1.0,
                        "signalLayerCandidates": [
                            {
                                "layer": "B.Cu",
                                "splitRisk": False,
                                "adjacencyRank": 0,
                                "totalPressure": 8.0,
                            },
                            {
                                "layer": "F.Cu",
                                "splitRisk": False,
                                "adjacencyRank": 0,
                                "totalPressure": 40.0,
                            },
                        ],
                    },
                    "defaults": {"power_min_width_mm": 0.8, "hs_via_limit": 2},
                    "derived": {},
                    "intents": [
                        {
                            "net_name": "USB_D_P",
                            "intent": "HS_DIFF",
                            "track_length_mm": 0.0,
                            "priority": 90,
                            "diff_partner": "USB_D_N",
                        },
                        {
                            "net_name": "USB_D_N",
                            "intent": "HS_DIFF",
                            "track_length_mm": 0.0,
                            "priority": 90,
                            "diff_partner": "USB_D_P",
                        },
                    ],
                },
            }
        }
    )

    assert result["success"] is True
    assert diff_pair_calls[0]["layer"] == "B.Cu"
    assert result["ordering"][0]["selectedLayer"] == "B.Cu"
    assert result["ordering"][0]["transitionPolicy"] == "paired_transitions_required"
    assert result["ordering"][0]["estimatedViaCountPerNet"] == 2.0


def test_route_diff_pair_passes_transition_geometry_to_backend():
    def _footprint(ref: str, layer_id: int = 0):
        footprint = MagicMock()
        footprint.GetReference.return_value = ref
        footprint.GetLayer.return_value = layer_id
        return footprint

    board = MagicMock()
    board.GetLayerName.side_effect = lambda layer_id: {0: "F.Cu", 31: "B.Cu"}.get(layer_id, "F.Cu")
    routing_commands = MagicMock()
    routing_commands.route_differential_pair.return_value = {
        "success": True,
        "diffPair": {"pairedTransitions": True, "viaCount": 4},
    }

    commands = AutorouteCFHACommands(board=board, routing_commands=routing_commands)
    inventory = {
        "USB_D_P": {
            "pads": [
                {"ref": "J1", "pad": "1", "x": 2.0, "y": 10.0},
                {"ref": "U1", "pad": "1", "x": 18.0, "y": 10.0},
            ]
        },
        "USB_D_N": {
            "pads": [
                {"ref": "J1", "pad": "2", "x": 2.0, "y": 10.4},
                {"ref": "U1", "pad": "2", "x": 18.0, "y": 10.4},
            ]
        },
    }

    result = commands._route_diff_pair(
        "USB_D_P",
        "USB_D_N",
        inventory=inventory,
        constraints={
            "defaults": {"hs_diff_gap_mm": {"opt": 0.15}, "hs_diff_skew_mm": 0.25},
            "referencePlanning": {"groundNet": "AGND"},
        },
        width_mm=0.25,
        layer="B.Cu",
        board=board,
        footprints={"J1": _footprint("J1", 0), "U1": _footprint("U1", 0)},
    )

    assert result["success"] is True
    payload = routing_commands.route_differential_pair.call_args.args[0]
    assert payload["layer"] == "B.Cu"
    assert payload["startLayer"] == "F.Cu"
    assert payload["endLayer"] == "F.Cu"
    assert payload["startRef"] == "J1"
    assert payload["endRef"] == "U1"
    assert payload["allowLayerTransitions"] is True
    assert payload["referenceNet"] == "AGND"
    assert payload["addReturnPathStitching"] is True
    assert payload["startPosPos"]["x"] == 2.0
    assert payload["startPosNeg"]["y"] == 10.4
    assert payload["endPosPos"]["x"] == 18.0
    assert payload["endPosNeg"]["y"] == 10.4


def test_route_critical_nets_prefers_endpoint_layer_when_via_transition_penalty_is_higher(monkeypatch, tmp_path):
    def _footprint(ref: str, layer_id: int):
        footprint = MagicMock()
        footprint.GetReference.return_value = ref
        footprint.GetLayer.return_value = layer_id
        return footprint

    bbox = MagicMock()
    bbox.GetLeft.return_value = 0
    bbox.GetTop.return_value = 0
    bbox.GetRight.return_value = int(80 * 1_000_000)
    bbox.GetBottom.return_value = int(40 * 1_000_000)

    board = MagicMock()
    board.GetFileName.return_value = str(tmp_path / "via_transition_penalty_demo.kicad_pcb")
    board.GetBoardEdgesBoundingBox.return_value = bbox
    board.GetFootprints.return_value = [_footprint("J1", 0), _footprint("U1", 0)]
    board.GetLayerName.side_effect = lambda layer_id: {0: "F.Cu", 31: "B.Cu"}.get(layer_id, "F.Cu")

    routed_layers = {}
    routing_commands = MagicMock()

    def _route(params):
        routed_layers[params["net"]] = params["layer"]
        return {"success": True}

    routing_commands.route_pad_to_pad.side_effect = _route
    commands = AutorouteCFHACommands(board=board, routing_commands=routing_commands)

    monkeypatch.setattr(
        commands,
        "_ensure_board",
        lambda params: (board, Path(board.GetFileName()), None),
    )
    monkeypatch.setattr(
        commands,
        "_collect_inventory",
        lambda _board: {
            "CLK": {
                "pads": [
                    {"ref": "J1", "pad": "1", "x": 4.0, "y": 10.0},
                    {"ref": "U1", "pad": "1", "x": 18.0, "y": 10.0},
                ]
            }
        },
    )
    monkeypatch.setattr(commands, "_estimate_net_congestion", lambda pads, _board: 0.0)
    monkeypatch.setattr(commands, "_estimate_escape_complexity", lambda net, pads, fps: 0.0)
    monkeypatch.setattr(commands, "_estimate_breakout_pressure", lambda net, pads, board, fps: 0.0)
    monkeypatch.setattr(commands, "_estimate_reference_alignment_pressure", lambda net, pads, board, planning: 0.0)

    result = commands.route_critical_nets(
        {
            "constraintsResult": {
                "success": True,
                "constraints": {
                    "criticalClasses": ["HS_SINGLE"],
                    "boardSummary": {
                        "trackPressureByLayer": {"F.Cu": 40.0, "B.Cu": 10.0},
                        "edgePressureByLayer": {
                            "F.Cu": {"left": 24.0, "right": 8.0, "center": 12.0},
                            "B.Cu": {"left": 3.0, "right": 4.0, "center": 5.0},
                        },
                    },
                    "referencePlanning": {
                        "preferredSignalLayer": "B.Cu",
                        "preferredEntryEdge": "left",
                        "referenceContinuityScore": 0.8,
                        "signalLayerCandidates": [
                            {
                                "layer": "B.Cu",
                                "splitRisk": False,
                                "adjacencyRank": 0,
                                "totalPressure": 10.0,
                            },
                            {
                                "layer": "F.Cu",
                                "splitRisk": False,
                                "adjacencyRank": 0,
                                "totalPressure": 40.0,
                            },
                        ],
                    },
                    "defaults": {"power_min_width_mm": 0.8},
                    "derived": {},
                    "intents": [
                        {"net_name": "CLK", "intent": "HS_SINGLE", "track_length_mm": 0.0, "priority": 85},
                    ],
                },
            }
        }
    )

    assert result["success"] is True
    assert routed_layers["CLK"] == "F.Cu"
    assert result["ordering"][0]["selectedLayer"] == "F.Cu"


def test_post_tune_routes_heals_support_net_unconnected_items(monkeypatch, tmp_path):
    report_path = tmp_path / "heal_report.rpt"
    report_path.write_text(
        """
** Drc report **
[unconnected_items]: Missing connection between items
    Local override; Severity: error
    @(36.0000 mm, 14.1750 mm): Track [GND] on F.Cu, length 7.0250 mm
    @(56.8875 mm, 20.5375 mm): Track [GND] on F.Cu, length 27.9125 mm
""",
        encoding="utf-8",
    )

    board = MagicMock()
    board.GetFileName.return_value = str(tmp_path / "demo.kicad_pcb")
    board.GetTracks.return_value = []
    board.GetLayerID.return_value = 0
    bbox = MagicMock()
    bbox.GetLeft.return_value = 0
    bbox.GetTop.return_value = 0
    bbox.GetRight.return_value = int(80 * 1_000_000)
    bbox.GetBottom.return_value = int(40 * 1_000_000)
    board.GetBoardEdgesBoundingBox.return_value = bbox

    routing_commands = MagicMock()
    routing_commands.route_trace.return_value = {"success": True}
    routing_commands.add_via.return_value = {"success": True}
    routing_commands.refill_zones.return_value = {"success": True}
    routing_commands._get_track_width_mm.return_value = 0.25
    routing_commands._get_clearance_mm.return_value = 0.2
    routing_commands._collect_routing_obstacles.return_value = []

    design_rules = MagicMock()
    design_rules.run_drc.return_value = {
        "success": True,
        "reportPath": str(report_path),
    }

    commands = AutorouteCFHACommands(
        board=board,
        routing_commands=routing_commands,
        design_rule_commands=design_rules,
    )

    monkeypatch.setattr(
        commands,
        "_ensure_board",
        lambda params: (board, Path(board.GetFileName()), None),
    )
    monkeypatch.setattr(
        commands,
        "_collect_zones",
        lambda _board: [{"net": "GND", "layer": "B.Cu", "priority": 1}],
    )

    result = commands.post_tune_routes({"refillZones": True, "healingPasses": 1})

    assert result["success"] is True
    assert "support_net_healing" in result["actions"]
    assert len(result["healing"]["addedBridges"]) == 1
    assert result["healing"]["addedVias"] == []
    payload = routing_commands.route_trace.call_args_list[0].args[0]
    assert payload["net"] == "GND"
    assert payload["layer"] == "F.Cu"


def test_post_tune_routes_adds_matched_length_compensation(monkeypatch, tmp_path):
    board = MagicMock()
    board.GetFileName.return_value = str(tmp_path / "demo.kicad_pcb")
    board.GetLayerName.return_value = "F.Cu"
    bbox = MagicMock()
    bbox.GetLeft.return_value = 0
    bbox.GetTop.return_value = 0
    bbox.GetRight.return_value = int(80 * 1_000_000)
    bbox.GetBottom.return_value = int(40 * 1_000_000)
    board.GetBoardEdgesBoundingBox.return_value = bbox

    start = MagicMock()
    start.x = int(10 * 1_000_000)
    start.y = int(10 * 1_000_000)
    end = MagicMock()
    end.x = int(24 * 1_000_000)
    end.y = int(10 * 1_000_000)

    track = MagicMock()
    track.GetNetname.return_value = "DQ0"
    track.Type.return_value = -1
    track.GetStart.return_value = start
    track.GetEnd.return_value = end
    track.GetLayer.return_value = 0
    track.GetWidth.return_value = int(0.25 * 1_000_000)
    track.GetLength.return_value = int(14 * 1_000_000)
    track.m_Uuid.AsString.return_value = "seg-dq0"
    board.GetTracks.return_value = [track]

    routing_commands = MagicMock()
    routing_commands.route_trace.return_value = {"success": True}
    routing_commands._collect_routing_obstacles.return_value = []
    routing_commands._get_clearance_mm.return_value = 0.2

    commands = AutorouteCFHACommands(board=board, routing_commands=routing_commands)
    monkeypatch.setattr(
        commands,
        "_ensure_board",
        lambda params: (board, Path(board.GetFileName()), None),
    )
    monkeypatch.setattr(
        commands,
        "_collect_inventory",
        lambda _board: {
            "DQ0": {
                "pads": [{}, {}],
                "track_count": 1,
                "track_length_mm": 10.0,
                "via_count": 0,
                "zones": [],
                "min_track_width_mm": 0.25,
            },
            "DQ1": {
                "pads": [{}, {}],
                "track_count": 1,
                "track_length_mm": 10.9,
                "via_count": 0,
                "zones": [],
                "min_track_width_mm": 0.25,
            },
            "DQ2": {
                "pads": [{}, {}],
                "track_count": 1,
                "track_length_mm": 10.8,
                "via_count": 0,
                "zones": [],
                "min_track_width_mm": 0.25,
            },
        },
    )

    result = commands.post_tune_routes(
        {
            "refillZones": False,
            "autoHealSupportNets": False,
            "constraintsResult": {
                "constraints": {
                    "matchedLengthGroups": [
                        {"nets": ["DQ0", "DQ1", "DQ2"], "maxSkewMm": 0.2, "type": "bus"}
                    ]
                }
            },
        }
    )

    assert result["success"] is True
    assert "matched_length_tuning" in result["actions"]
    assert result["matchedLengthTuning"]["tunedNets"][0]["net"] == "DQ0"
    payload = routing_commands.route_trace.call_args_list[0].args[0]
    assert payload["net"] == "DQ0"
    assert payload["layer"] == "F.Cu"
    assert len(payload["waypoints"]) >= 3
    board.Remove.assert_called_once_with(track)


def test_post_tune_routes_creates_reference_ground_zone(monkeypatch, tmp_path):
    board = MagicMock()
    board.GetFileName.return_value = str(tmp_path / "reference_zone_demo.kicad_pcb")
    board.GetTracks.return_value = []
    bbox = MagicMock()
    bbox.GetLeft.return_value = 0
    bbox.GetTop.return_value = 0
    bbox.GetRight.return_value = int(60 * 1_000_000)
    bbox.GetBottom.return_value = int(30 * 1_000_000)
    board.GetBoardEdgesBoundingBox.return_value = bbox

    routing_commands = MagicMock()
    routing_commands.add_copper_pour.return_value = {"success": True}

    commands = AutorouteCFHACommands(board=board, routing_commands=routing_commands)
    monkeypatch.setattr(
        commands,
        "_ensure_board",
        lambda params: (board, Path(board.GetFileName()), None),
    )
    monkeypatch.setattr(commands, "_board_layers", lambda _board: ["F.Cu", "B.Cu"])
    monkeypatch.setattr(
        commands,
        "_collect_inventory",
        lambda _board: {
            "DQ0": {
                "pads": [{}, {}],
                "track_count": 1,
                "track_length_mm": 10.0,
                "via_count": 0,
                "zones": [],
                "min_track_width_mm": 0.25,
            },
            "GND": {
                "pads": [{}, {}],
                "track_count": 0,
                "track_length_mm": 0.0,
                "via_count": 0,
                "zones": [],
                "min_track_width_mm": None,
            },
        },
    )
    monkeypatch.setattr(commands, "_collect_zones", lambda _board: [])

    result = commands.post_tune_routes(
        {
            "refillZones": False,
            "autoTuneMatchedLengths": False,
            "autoHealSupportNets": False,
            "constraintsResult": {
                "constraints": {
                    "defaults": {"edge_clearance_mm": 0.25},
                    "intents": [
                        {"net_name": "DQ0", "intent": "HS_SINGLE"},
                        {"net_name": "GND", "intent": "GROUND"},
                    ],
                }
            },
        }
    )

    assert result["success"] is True
    assert "reference_ground_zone" in result["actions"]
    assert result["referenceZone"]["created"] is True
    payload = routing_commands.add_copper_pour.call_args.args[0]
    assert payload["net"] == "GND"
    assert payload["layer"] == "B.Cu"
    assert len(payload["points"]) == 4
    assert payload["points"][0]["x"] == 0.25
    assert payload["points"][0]["y"] == 0.25


def test_post_tune_routes_preserves_explicit_zero_skew(monkeypatch, tmp_path):
    board = MagicMock()
    board.GetFileName.return_value = str(tmp_path / "zero_skew_demo.kicad_pcb")
    board.GetLayerName.return_value = "F.Cu"
    bbox = MagicMock()
    bbox.GetLeft.return_value = 0
    bbox.GetTop.return_value = 0
    bbox.GetRight.return_value = int(80 * 1_000_000)
    bbox.GetBottom.return_value = int(40 * 1_000_000)
    board.GetBoardEdgesBoundingBox.return_value = bbox

    start = MagicMock()
    start.x = int(10 * 1_000_000)
    start.y = int(10 * 1_000_000)
    end = MagicMock()
    end.x = int(24 * 1_000_000)
    end.y = int(10 * 1_000_000)

    track = MagicMock()
    track.GetNetname.return_value = "DQ0"
    track.Type.return_value = -1
    track.GetStart.return_value = start
    track.GetEnd.return_value = end
    track.GetLayer.return_value = 0
    track.GetWidth.return_value = int(0.25 * 1_000_000)
    track.GetLength.return_value = int(14 * 1_000_000)
    track.m_Uuid.AsString.return_value = "seg-dq0-zero"
    board.GetTracks.return_value = [track]

    routing_commands = MagicMock()
    routing_commands.route_trace.return_value = {"success": True}
    routing_commands._collect_routing_obstacles.return_value = []
    routing_commands._get_clearance_mm.return_value = 0.2

    commands = AutorouteCFHACommands(board=board, routing_commands=routing_commands)
    monkeypatch.setattr(
        commands,
        "_ensure_board",
        lambda params: (board, Path(board.GetFileName()), None),
    )
    monkeypatch.setattr(
        commands,
        "_collect_inventory",
        lambda _board: {
            "DQ0": {
                "pads": [{}, {}],
                "track_count": 1,
                "track_length_mm": 10.0,
                "via_count": 0,
                "zones": [],
                "min_track_width_mm": 0.25,
            },
            "DQ1": {
                "pads": [{}, {}],
                "track_count": 1,
                "track_length_mm": 10.9,
                "via_count": 0,
                "zones": [],
                "min_track_width_mm": 0.25,
            },
            "DQ2": {
                "pads": [{}, {}],
                "track_count": 1,
                "track_length_mm": 10.8,
                "via_count": 0,
                "zones": [],
                "min_track_width_mm": 0.25,
            },
        },
    )

    result = commands.post_tune_routes(
        {
            "refillZones": False,
            "autoHealSupportNets": False,
            "constraintsResult": {
                "constraints": {
                    "matchedLengthGroups": [
                        {"nets": ["DQ0", "DQ1", "DQ2"], "maxSkewMm": 0.0, "type": "bus_auto"}
                    ]
                }
            },
        }
    )

    assert result["success"] is True
    assert "matched_length_tuning" in result["actions"]
    tuned = result["matchedLengthTuning"]["tunedNets"][0]
    assert tuned["net"] == "DQ0"
    assert tuned["targetExtraMm"] == 0.9


def test_verify_routing_qor_reports_matched_group_skew(monkeypatch, tmp_path):
    board = MagicMock()
    board.GetFileName.return_value = str(tmp_path / "demo.kicad_pcb")
    board.GetTracks.return_value = []
    board.GetFootprints.return_value = []
    board.Zones.return_value = []
    board.IsLayerEnabled.return_value = False

    commands = AutorouteCFHACommands(board=board, design_rule_commands=MagicMock())
    monkeypatch.setattr(
        commands,
        "_ensure_board",
        lambda params: (board, Path(board.GetFileName()), None),
    )
    monkeypatch.setattr(commands, "_board_layers", lambda _board: ["F.Cu", "B.Cu"])
    monkeypatch.setattr(
        commands,
        "_collect_inventory",
        lambda _board: {
            "DQ0": {"pads": [{}, {}], "track_length_mm": 10.0, "via_count": 0, "zones": []},
            "DQ1": {"pads": [{}, {}], "track_length_mm": 10.35, "via_count": 0, "zones": []},
            "DQ2": {"pads": [{}, {}], "track_length_mm": 10.1, "via_count": 0, "zones": []},
        },
    )
    monkeypatch.setattr(commands, "_collect_zones", lambda _board: [])
    monkeypatch.setattr(
        commands,
        "extract_routing_intents",
        lambda params: {
            "success": True,
            "intents": [
                {"net_name": "DQ0", "intent": "HS_SINGLE"},
                {"net_name": "DQ1", "intent": "HS_SINGLE"},
                {"net_name": "DQ2", "intent": "HS_SINGLE"},
            ],
        },
    )
    commands.design_rule_commands.run_drc.return_value = {
        "success": True,
        "summary": {"by_severity": {"error": 0, "warning": 0}},
        "violationsFile": str(tmp_path / "violations.json"),
        "reportPath": str(tmp_path / "demo.drc.rpt"),
    }

    result = commands.verify_routing_qor(
        {
            "constraintsResult": {
                "constraints": {
                    "defaults": {"hs_diff_skew_mm": 0.25, "hs_diff_uncoupled_mm": 3.0},
                    "matchedLengthGroups": [
                        {"nets": ["DQ0", "DQ1", "DQ2"], "maxSkewMm": 0.2, "type": "bus"}
                    ],
                }
            }
        }
    )

    assert result["success"] is True
    assert result["matchedGroupSkewMm"]["DQ0|DQ1|DQ2"] == 0.35
    assert result["metrics"]["maxMatchedGroupSkewRatio"] == 1.75
    assert result["flags"]["matchedLengthRisk"][0]["type"] == "bus"


def test_verify_routing_qor_preserves_explicit_zero_skew(monkeypatch, tmp_path):
    board = MagicMock()
    board.GetFileName.return_value = str(tmp_path / "zero_skew_verify.kicad_pcb")
    board.GetTracks.return_value = []
    board.GetFootprints.return_value = []
    board.Zones.return_value = []
    board.IsLayerEnabled.return_value = False

    commands = AutorouteCFHACommands(board=board, design_rule_commands=MagicMock())
    monkeypatch.setattr(
        commands,
        "_ensure_board",
        lambda params: (board, Path(board.GetFileName()), None),
    )
    monkeypatch.setattr(commands, "_board_layers", lambda _board: ["F.Cu", "B.Cu"])
    monkeypatch.setattr(
        commands,
        "_collect_inventory",
        lambda _board: {
            "DQ0": {"pads": [{}, {}], "track_length_mm": 10.0, "via_count": 0, "zones": []},
            "DQ1": {"pads": [{}, {}], "track_length_mm": 10.35, "via_count": 0, "zones": []},
            "DQ2": {"pads": [{}, {}], "track_length_mm": 10.1, "via_count": 0, "zones": []},
        },
    )
    monkeypatch.setattr(commands, "_collect_zones", lambda _board: [])
    monkeypatch.setattr(
        commands,
        "extract_routing_intents",
        lambda params: {
            "success": True,
            "intents": [
                {"net_name": "DQ0", "intent": "HS_SINGLE"},
                {"net_name": "DQ1", "intent": "HS_SINGLE"},
                {"net_name": "DQ2", "intent": "HS_SINGLE"},
            ],
        },
    )
    commands.design_rule_commands.run_drc.return_value = {
        "success": True,
        "summary": {"by_severity": {"error": 0, "warning": 0}},
        "violationsFile": str(tmp_path / "violations.json"),
        "reportPath": str(tmp_path / "demo.drc.rpt"),
    }

    result = commands.verify_routing_qor(
        {
            "constraintsResult": {
                "constraints": {
                    "defaults": {"hs_diff_skew_mm": 0.25, "hs_diff_uncoupled_mm": 3.0},
                    "matchedLengthGroups": [
                        {"nets": ["DQ0", "DQ1", "DQ2"], "maxSkewMm": 0.0, "type": "bus_auto"}
                    ],
                }
            }
        }
    )

    assert result["success"] is True
    assert result["metrics"]["maxMatchedGroupSkewRatio"] == 35.0
    assert result["flags"]["matchedLengthRisk"][0]["maxSkewMm"] == 0.0


def test_autoroute_cfha_analysis_only_skips_mutating_stages(tmp_path):
    commands = AutorouteCFHACommands()
    board_path = str(tmp_path / "analysis_only_demo.kicad_pcb")

    commands._ensure_board = MagicMock(return_value=(MagicMock(), Path(board_path), None))
    commands.analyze_board_routing_context = MagicMock(
        return_value={
            "success": True,
            "boardPath": board_path,
            "summary": {"copperLayers": ["F.Cu", "B.Cu"]},
            "backends": {},
            "profiles": ["generic_2layer"],
            "interfaces": ["DDR4"],
        }
    )
    commands.extract_routing_intents = MagicMock(
        return_value={
            "success": True,
            "boardPath": board_path,
            "profiles": ["generic_2layer"],
            "interfaces": ["DDR4"],
            "byIntent": {"HS_SINGLE": ["DQ0", "DQ1", "DQ2"]},
            "intents": [
                {"net_name": "DQ0", "intent": "HS_SINGLE"},
                {"net_name": "DQ1", "intent": "HS_SINGLE"},
                {"net_name": "DQ2", "intent": "HS_SINGLE"},
            ],
            "analysisSummary": {"copperLayers": ["F.Cu", "B.Cu"]},
            "netInventory": {},
            "inferredMatchedLengthGroups": [
                {"nets": ["DQ0", "DQ1", "DQ2"], "maxSkewMm": 0.08, "type": "bus_auto"}
            ],
        }
    )
    commands.generate_routing_constraints = MagicMock(
        return_value={
            "success": True,
            "constraints": {
                "defaults": {"hs_diff_skew_mm": 0.08, "hs_diff_uncoupled_mm": 3.0},
                "matchedLengthGroups": [
                    {"nets": ["DQ0", "DQ1", "DQ2"], "maxSkewMm": 0.08, "type": "bus_auto"}
                ],
            },
        }
    )
    commands.generate_kicad_dru = MagicMock(return_value={"success": True, "path": str(tmp_path / "demo.kicad_dru")})
    commands.route_critical_nets = MagicMock(return_value={"success": True})
    commands.post_tune_routes = MagicMock(return_value={"success": True})
    commands.verify_routing_qor = MagicMock(
        return_value={
            "success": True,
            "completionRate": 1.0,
            "qorScore": 0.8,
            "qorGrade": "B",
            "qorDetail": {"score": 0.8, "grade": "B", "subScores": {}, "weights": {}},
            "drc": {"errors": 0, "warnings": 0, "reportPath": str(tmp_path / "demo.drc.rpt")},
            "metrics": {"runtimeSec": 0.01},
            "flags": {"powerNetMisuse": [], "returnPathRisk": [], "matchedLengthRisk": []},
            "pairSkewMm": {},
            "matchedGroupSkewMm": {},
            "reportPath": str(tmp_path / "demo.autoroute_cfha.json"),
        }
    )

    result = commands.autoroute_cfha({"boardPath": board_path, "strategy": "analysis_only"})

    assert result["success"] is True
    assert result["strategy"] == "analysis_only"
    assert result["stages"]["preRouteReference"]["skipped"] is True
    assert result["stages"]["critical"]["skipped"] is True
    assert result["stages"]["postTune"]["skipped"] is True
    assert result["stages"]["timingsSec"]["pre_route_reference"] == 0.0
    assert result["stages"]["timingsSec"]["route_critical"] == 0.0
    assert result["stages"]["timingsSec"]["post_tune"] == 0.0
    commands.route_critical_nets.assert_not_called()
    commands.post_tune_routes.assert_not_called()


def test_autoroute_cfha_hybrid_avoids_prebulk_drc_when_freerouting_unavailable(tmp_path):
    commands = AutorouteCFHACommands()
    board_path = str(tmp_path / "hybrid_demo.kicad_pcb")
    board = MagicMock()

    commands._ensure_board = MagicMock(return_value=(board, Path(board_path), None))
    commands.analyze_board_routing_context = MagicMock(
        return_value={
            "success": True,
            "boardPath": board_path,
            "summary": {"copperLayers": ["F.Cu", "B.Cu"]},
            "backends": {"freerouting_ready": False},
            "profiles": ["generic_2layer"],
            "interfaces": ["DDR4"],
        }
    )
    commands.extract_routing_intents = MagicMock(
        return_value={
            "success": True,
            "boardPath": board_path,
            "profiles": ["generic_2layer"],
            "interfaces": ["DDR4"],
            "byIntent": {"HS_SINGLE": ["DQ0", "DQ1", "DQ2"]},
            "intents": [
                {"net_name": "DQ0", "intent": "HS_SINGLE"},
                {"net_name": "DQ1", "intent": "HS_SINGLE"},
                {"net_name": "DQ2", "intent": "HS_SINGLE"},
            ],
            "analysisSummary": {"copperLayers": ["F.Cu", "B.Cu"]},
            "netInventory": {},
            "inferredMatchedLengthGroups": [
                {"nets": ["DQ0", "DQ1", "DQ2"], "maxSkewMm": 0.08, "type": "bus_auto"}
            ],
        }
    )
    commands.generate_routing_constraints = MagicMock(
        return_value={
            "success": True,
            "constraints": {
                "defaults": {"hs_diff_skew_mm": 0.08, "hs_diff_uncoupled_mm": 3.0},
                "matchedLengthGroups": [
                    {"nets": ["DQ0", "DQ1", "DQ2"], "maxSkewMm": 0.08, "type": "bus_auto"}
                ],
            },
        }
    )
    commands.generate_kicad_dru = MagicMock(return_value={"success": True, "path": str(tmp_path / "demo.kicad_dru")})
    commands.route_critical_nets = MagicMock(return_value={"success": True})
    commands.post_tune_routes = MagicMock(return_value={"success": True})
    commands.run_freerouting = MagicMock(return_value={"success": True})
    commands._completion_snapshot = MagicMock(
        return_value={
            "inventory": {},
            "routeableNetCount": 3,
            "completedNetCount": 1,
            "completionRate": 0.3333,
        }
    )
    commands.verify_routing_qor = MagicMock(
        return_value={
            "success": True,
            "completionRate": 1.0,
            "qorScore": 0.8,
            "qorGrade": "B",
            "qorDetail": {"score": 0.8, "grade": "B", "subScores": {}, "weights": {}},
            "drc": {"errors": 0, "warnings": 0, "reportPath": str(tmp_path / "demo.drc.rpt")},
            "metrics": {"runtimeSec": 0.01},
            "flags": {"powerNetMisuse": [], "returnPathRisk": [], "matchedLengthRisk": []},
            "pairSkewMm": {},
            "matchedGroupSkewMm": {},
            "reportPath": str(tmp_path / "demo.autoroute_cfha.json"),
        }
    )

    result = commands.autoroute_cfha({"boardPath": board_path, "strategy": "hybrid"})

    assert result["success"] is True
    assert result["stages"]["bulk"]["skipped"] is True
    assert result["stages"]["bulk"]["message"] == "Bulk router unavailable; Freerouting is not ready"
    commands._completion_snapshot.assert_called_once()
    commands.verify_routing_qor.assert_called_once()
    commands.run_freerouting.assert_not_called()


def test_route_critical_nets_uses_reference_planning_layer_fallback(monkeypatch, tmp_path):
    board = MagicMock()
    board_path = Path(tmp_path / "critical_layer_plan_demo.kicad_pcb")
    board.GetFileName.return_value = str(board_path)
    board.GetFootprints.return_value = []
    board.Save = MagicMock()

    commands = AutorouteCFHACommands(board=board)
    commands.routing_commands = MagicMock()
    commands.routing_commands.route_pad_to_pad.return_value = {"success": True}
    commands.ipc_board_api = None

    monkeypatch.setattr(
        commands,
        "_ensure_board",
        lambda params: (board, board_path, None),
    )
    monkeypatch.setattr(
        commands,
        "_collect_inventory",
        lambda _board: {
            "CLK": {
                "pads": [
                    {"ref": "J1", "pad": "1", "x": 0.0, "y": 0.0},
                    {"ref": "U1", "pad": "1", "x": 20.0, "y": 0.0},
                ],
                "track_length_mm": 0.0,
            }
        },
    )
    monkeypatch.setattr(commands, "_estimate_net_congestion", lambda pads, board: 0.0)
    monkeypatch.setattr(commands, "_estimate_escape_complexity", lambda net_name, pads, footprints: 0.0)
    monkeypatch.setattr(commands, "_estimate_breakout_pressure", lambda net_name, pads, board, footprints: 0.0)

    result = commands.route_critical_nets(
        {
            "constraintsResult": {
                "success": True,
                "constraints": {
                    "criticalClasses": ["HS_SINGLE"],
                    "referencePlanning": {"preferredSignalLayer": "B.Cu"},
                    "defaults": {"power_min_width_mm": 1.0},
                    "intents": [
                        {"net_name": "CLK", "intent": "HS_SINGLE", "priority": 70, "track_length_mm": 0.0}
                    ],
                },
            }
        }
    )

    assert result["success"] is True
    assert result["criticalLayer"] == "B.Cu"
    route_call = commands.routing_commands.route_pad_to_pad.call_args.args[0]
    assert route_call["layer"] == "B.Cu"


def test_ensure_reference_ground_zone_creates_selected_domain_even_if_other_ground_zone_exists(tmp_path):
    board = MagicMock()
    board.BuildConnectivity = MagicMock()
    commands = AutorouteCFHACommands(board=board)
    commands.routing_commands = MagicMock()
    commands.routing_commands.add_copper_pour.return_value = {"success": True}

    commands._collect_zones = MagicMock(
        return_value=[{"net": "GND", "layer": "In1.Cu", "priority": 0}]
    )
    commands._collect_inventory = MagicMock(
        return_value={
            "USB_D_P": {
                "pad_refs": ["J1", "U1"],
                "pads": [
                    {"ref": "J1", "x": 0.0, "y": 0.0},
                    {"ref": "U1", "x": 20.0, "y": 0.0},
                ],
                "zones": [],
            },
            "USB_D_N": {
                "pad_refs": ["J1", "U1"],
                "pads": [
                    {"ref": "J1", "x": 0.0, "y": 0.45},
                    {"ref": "U1", "x": 20.0, "y": 0.45},
                ],
                "zones": [],
            },
            "AGND": {
                "pad_refs": ["J1", "U1"],
                "pads": [
                    {"ref": "J1", "x": 0.0, "y": 1.0},
                    {"ref": "U1", "x": 20.0, "y": 1.0},
                ],
                "zones": [],
            },
            "GND": {
                "pad_refs": ["U2"],
                "pads": [{"ref": "U2", "x": 60.0, "y": 20.0}],
                "zones": [{"net": "GND", "layer": "In1.Cu"}],
            },
        }
    )
    commands._reference_zone_outline = MagicMock(
        return_value=[
            {"x": 1.0, "y": 1.0},
            {"x": 29.0, "y": 1.0},
            {"x": 29.0, "y": 19.0},
            {"x": 1.0, "y": 19.0},
        ]
    )

    result = commands._ensure_reference_ground_zone(
        board,
        Path(tmp_path / "reference_zone_domain_demo.kicad_pcb"),
        constraints_data={
            "referencePlanning": {"groundNet": "AGND", "preferredZoneLayer": "In1.Cu"},
            "defaults": {"edge_clearance_mm": 0.2},
            "intents": [
                {"net_name": "USB_D_P", "intent": "HS_DIFF", "diff_partner": "USB_D_N"},
                {"net_name": "USB_D_N", "intent": "HS_DIFF", "diff_partner": "USB_D_P"},
                {"net_name": "AGND", "intent": "GROUND"},
                {"net_name": "GND", "intent": "GROUND"},
            ],
        },
        params={},
    )

    assert result["success"] is True
    assert result["created"] is True
    assert result["net"] == "AGND"
    assert result["layer"] == "In1.Cu"
    pour_call = commands.routing_commands.add_copper_pour.call_args.args[0]
    assert pour_call["net"] == "AGND"
    assert pour_call["layer"] == "In1.Cu"
    board.BuildConnectivity.assert_called_once()


def test_autoroute_cfha_hybrid_runs_pre_route_reference_stage(tmp_path):
    commands = AutorouteCFHACommands()
    board_path = str(tmp_path / "hybrid_reference_demo.kicad_pcb")
    board = MagicMock()

    commands._ensure_board = MagicMock(return_value=(board, Path(board_path), None))
    commands.analyze_board_routing_context = MagicMock(
        return_value={
            "success": True,
            "boardPath": board_path,
            "summary": {"copperLayers": ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"]},
            "backends": {"freerouting_ready": False},
            "profiles": ["generic_4layer"],
            "interfaces": ["USB2"],
        }
    )
    commands.extract_routing_intents = MagicMock(
        return_value={
            "success": True,
            "boardPath": board_path,
            "profiles": ["generic_4layer"],
            "interfaces": ["USB2"],
            "byIntent": {"HS_DIFF": ["USB_D_N", "USB_D_P"], "GROUND": ["GND"]},
            "intents": [
                {"net_name": "USB_D_P", "intent": "HS_DIFF", "track_length_mm": 0.0, "diff_partner": "USB_D_N"},
                {"net_name": "USB_D_N", "intent": "HS_DIFF", "track_length_mm": 0.0, "diff_partner": "USB_D_P"},
                {"net_name": "GND", "intent": "GROUND", "track_length_mm": 0.0},
            ],
            "analysisSummary": {"copperLayers": ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"]},
            "netInventory": {"GND": {"pads": [{}], "zones": []}},
        }
    )
    commands.generate_routing_constraints = MagicMock(
        return_value={
            "success": True,
            "constraints": {
                "criticalClasses": ["HS_DIFF"],
                "referencePlanning": {
                    "groundNet": "GND",
                    "highSpeedNets": ["USB_D_N", "USB_D_P"],
                    "existingGroundZoneLayers": [],
                    "preferredZoneLayer": "In1.Cu",
                    "preferredSignalLayer": "F.Cu",
                    "splitRiskLayers": [],
                    "shouldAutoCreate": True,
                    "reason": "high_speed_nets_need_reference_plane",
                },
                "defaults": {"hs_diff_skew_mm": 0.08, "hs_diff_uncoupled_mm": 3.0},
                "intents": [
                    {"net_name": "USB_D_P", "intent": "HS_DIFF", "track_length_mm": 0.0, "priority": 80, "diff_partner": "USB_D_N"},
                    {"net_name": "USB_D_N", "intent": "HS_DIFF", "track_length_mm": 0.0, "priority": 80, "diff_partner": "USB_D_P"},
                    {"net_name": "GND", "intent": "GROUND", "track_length_mm": 0.0, "priority": 0},
                ],
            },
        }
    )
    commands.generate_kicad_dru = MagicMock(return_value={"success": True, "path": str(tmp_path / "demo.kicad_dru")})
    commands._ensure_reference_ground_zone = MagicMock(
        return_value={"success": True, "created": True, "net": "GND", "layer": "In1.Cu"}
    )
    commands.route_critical_nets = MagicMock(return_value={"success": True, "routed": [], "skipped": []})
    commands.post_tune_routes = MagicMock(return_value={"success": True})
    commands._completion_snapshot = MagicMock(
        return_value={
            "inventory": {},
            "routeableNetCount": 2,
            "completedNetCount": 2,
            "completionRate": 1.0,
        }
    )
    commands.verify_routing_qor = MagicMock(
        return_value={
            "success": True,
            "completionRate": 1.0,
            "qorScore": 0.95,
            "qorGrade": "A",
            "qorDetail": {"score": 0.95, "grade": "A", "subScores": {}, "weights": {}},
            "drc": {"errors": 0, "warnings": 0, "reportPath": str(tmp_path / "demo.drc.rpt")},
            "metrics": {"runtimeSec": 0.01},
            "flags": {"powerNetMisuse": [], "returnPathRisk": [], "matchedLengthRisk": []},
            "pairSkewMm": {},
            "matchedGroupSkewMm": {},
            "reportPath": str(tmp_path / "demo.autoroute_cfha.json"),
        }
    )

    result = commands.autoroute_cfha({"boardPath": board_path, "strategy": "hybrid"})

    assert result["success"] is True
    assert result["stages"]["preRouteReference"]["referenceZone"]["created"] is True
    assert result["stages"]["preRouteReference"]["criticalLayer"] == "F.Cu"
    assert result["stages"]["preRouteReference"]["criticalLayerSource"] == "referencePlanning"
    route_params = commands.route_critical_nets.call_args.args[0]
    assert route_params["criticalLayer"] == "F.Cu"
