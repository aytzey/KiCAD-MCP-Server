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
