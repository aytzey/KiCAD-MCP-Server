import json
from unittest.mock import MagicMock

from commands.design_rules import DesignRuleCommands


def test_parse_drc_report_text_extracts_summary_and_locations():
    report = """
** Drc report for /tmp/demo.kicad_pcb **
** Created on 2026-04-10 03:40:54 **

** Found 2 DRC violations **
[clearance]: Clearance violation
    Rule: cfha_rf_clearance; Severity: error
    @(134.0500 mm, 56.4100 mm): Track [RF_IN] on F.Cu
[lib_footprint_issues]: The current configuration does not include the library 'Demo'
    Local override; Severity: warning
    @(53.3167 mm, 5.9500 mm): Footprint J3

** End of Report **
""".strip()

    violations, summary = DesignRuleCommands._parse_drc_report_text(report)

    assert len(violations) == 2
    assert violations[0]["type"] == "clearance"
    assert violations[0]["severity"] == "error"
    assert violations[0]["location"] == {"x": 134.05, "y": 56.41, "unit": "mm"}
    assert violations[1]["type"] == "lib_footprint_issues"
    assert summary["by_type"]["clearance"] == 1
    assert summary["by_type"]["lib_footprint_issues"] == 1
    assert summary["by_severity"]["error"] == 1
    assert summary["by_severity"]["warning"] == 1


def test_run_drc_falls_back_to_pcbnew_report(monkeypatch, tmp_path):
    board_path = tmp_path / "demo.kicad_pcb"
    board_path.write_text("(kicad_pcb)", encoding="utf-8")
    board = MagicMock()
    board.GetFileName.return_value = str(board_path)
    commands = DesignRuleCommands(board)

    monkeypatch.setattr(commands, "_find_kicad_cli", lambda: "kicad-cli")
    monkeypatch.setattr(
        "subprocess.run",
        lambda *_args, **_kwargs: MagicMock(
            returncode=1, stderr="unknown command: pcb drc", stdout=""
        ),
    )

    def write_report(_board, output, _units, _all_errors):
        from pathlib import Path

        Path(output).write_text(
            "[clearance]: Too close\n    Severity: error\n" "    @(1.25 mm, 2.5 mm): Track\n",
            encoding="utf-8",
        )
        return True

    monkeypatch.setattr("commands.design_rules.pcbnew.WriteDRCReport", write_report, raising=False)
    monkeypatch.setattr(
        "commands.design_rules.pcbnew.EDA_UNITS_MILLIMETRES", object(), raising=False
    )

    result = commands.run_drc({})

    assert result["success"] is True
    assert result["backend"] == "pcbnew-report"
    assert result["summary"]["total"] == 1
    saved = json.loads((tmp_path / "demo_drc_violations.json").read_text(encoding="utf-8"))
    assert saved["severity_counts"]["error"] == 1
