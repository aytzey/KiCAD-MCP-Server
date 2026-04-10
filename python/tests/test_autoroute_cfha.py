from pathlib import Path
from unittest.mock import MagicMock

from commands.autoroute_cfha import AutorouteCFHACommands, compile_kicad_dru


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
        "local_congestion",
    ]
    assert "cfha_rf_clearance" in result["constraints"]["policy"]["compiledRuleFamilies"]


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
