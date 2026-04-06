"""
Tests for the schematic readability guard in KiCADInterface.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kicad_interface import KiCADInterface


def test_guard_reverts_when_new_issue_is_introduced(tmp_path, monkeypatch):
    sch = tmp_path / "guard_test.kicad_sch"
    sch.write_text("(kicad_sch original)\n", encoding="utf-8")

    iface = KiCADInterface()
    reports = [
        {"issueSignatures": [], "issueMessages": {}, "totalIssues": 0, "counts": {}},
        {
            "issueSignatures": ["overlap:symbol:symbol_overlap:R1:R2"],
            "issueMessages": {
                "overlap:symbol:symbol_overlap:R1:R2": "overlapping symbols: R1 and R2"
            },
            "totalIssues": 1,
            "counts": {"overlaps": 1, "wireCrossings": 0, "fieldIssues": 0, "offGridItems": 0},
        },
    ]

    def fake_check(_path):
        return reports.pop(0)

    monkeypatch.setattr(iface, "_check_schematic_readability", fake_check)

    def mutate():
        sch.write_text("(kicad_sch changed)\n", encoding="utf-8")
        return {"success": True, "message": "changed"}

    result = iface._guard_schematic_mutation(str(sch), "test_operation", mutate)

    assert result["success"] is False
    assert "reverted by schematic readability gate" in result["message"]
    assert sch.read_text(encoding="utf-8") == "(kicad_sch original)\n"


def test_guard_allows_existing_issues_when_no_new_ones_are_added(tmp_path, monkeypatch):
    sch = tmp_path / "guard_test_ok.kicad_sch"
    sch.write_text("(kicad_sch original)\n", encoding="utf-8")

    iface = KiCADInterface()
    report = {
        "issueSignatures": ["field:field_inside_symbol_body:U1:Reference:10:10"],
        "issueMessages": {
            "field:field_inside_symbol_body:U1:Reference:10:10": "visible field inside symbol body: U1.Reference"
        },
        "totalIssues": 1,
        "counts": {"overlaps": 0, "wireCrossings": 0, "fieldIssues": 1, "offGridItems": 0},
    }

    monkeypatch.setattr(iface, "_check_schematic_readability", lambda _path: report)

    def mutate():
        sch.write_text("(kicad_sch changed)\n", encoding="utf-8")
        return {"success": True, "message": "changed"}

    result = iface._guard_schematic_mutation(str(sch), "test_operation", mutate)

    assert result["success"] is True
    assert sch.read_text(encoding="utf-8") == "(kicad_sch changed)\n"
    assert result["readability"]["remainingIssues"] == 1
