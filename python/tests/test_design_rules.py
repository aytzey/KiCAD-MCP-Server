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
