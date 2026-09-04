"""Real KiCad smoke test for the gated two-layer manufacturing package.

Run with KiCad's bundled Python and ``KICAD_USE_REAL_PCBNEW=1``. The normal
suite skips it so CI hosts without KiCad remain supported.
"""

import os
from pathlib import Path

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.real_pcbnew]


@pytest.fixture(autouse=True)
def require_real_pcbnew() -> None:
    if os.environ.get("KICAD_USE_REAL_PCBNEW") != "1":
        pytest.skip("real manufacturing smoke test requires KICAD_USE_REAL_PCBNEW=1")


def _build_two_layer_board(pcbnew, board_path: Path) -> None:
    mm = pcbnew.FromMM
    board = pcbnew.BOARD()
    settings = board.GetDesignSettings()
    settings.m_TrackMinWidth = mm(0.20)
    settings.m_MinClearance = mm(0.20)
    settings.m_MinThroughDrill = mm(0.30)
    settings.m_ViasMinAnnularWidth = mm(0.15)
    settings.m_CopperEdgeClearance = mm(0.25)

    for x1, y1, x2, y2 in (
        (0, 0, 50, 0),
        (50, 0, 50, 40),
        (50, 40, 0, 40),
        (0, 40, 0, 0),
    ):
        edge = pcbnew.PCB_SHAPE(board)
        edge.SetShape(pcbnew.SHAPE_T_SEGMENT)
        edge.SetStart(pcbnew.VECTOR2I(mm(x1), mm(y1)))
        edge.SetEnd(pcbnew.VECTOR2I(mm(x2), mm(y2)))
        edge.SetLayer(pcbnew.Edge_Cuts)
        edge.SetWidth(mm(0.10))
        board.Add(edge)

    footprint = pcbnew.FOOTPRINT(board)
    footprint.SetReference("J1")
    footprint.SetValue("TEST_HEADER")
    footprint.SetFPID(pcbnew.LIB_ID("Connector_PinHeader_2.54mm", "PinHeader_1x02"))
    footprint.SetAttributes(pcbnew.FP_THROUGH_HOLE)
    footprint.SetPosition(pcbnew.VECTOR2I(mm(25), mm(20)))
    for number, x in (("1", 23.73), ("2", 26.27)):
        pad = pcbnew.PAD(footprint)
        pad.SetNumber(number)
        pad.SetShape(pcbnew.PAD_SHAPE_CIRCLE)
        pad.SetAttribute(pcbnew.PAD_ATTRIB_PTH)
        pad.SetSize(pcbnew.VECTOR2I(mm(1.7), mm(1.7)))
        pad.SetDrillSize(pcbnew.VECTOR2I(mm(0.8), mm(0.8)))
        pad.SetLayerSet(pad.PTHMask())
        pad.SetPosition(pcbnew.VECTOR2I(mm(x), mm(20)))
        footprint.Add(pad)
    board.Add(footprint)
    pcbnew.SaveBoard(str(board_path), board)


def test_real_kicad_generates_complete_manufacturing_package(tmp_path: Path) -> None:
    import pcbnew
    from kicad_interface import KiCADInterface

    board_path = tmp_path / "manufacturing-smoke.kicad_pcb"
    _build_two_layer_board(pcbnew, board_path)

    interface = KiCADInterface()
    output_dir = tmp_path / "release.v1"
    result = interface._handle_prepare_manufacturing_package(
        {
            "boardPath": str(board_path),
            "outputDir": str(output_dir),
            "assemblyMode": "hand",
            "allowUnsafe": False,
            "timeoutSec": 120,
        }
    )

    assert result["success"] is True, result
    assert result["readiness"]["ready"] is True, result["readiness"]
    observed = result["readiness"]["fabrication"]["observed"]
    assert observed["minDrillMm"] == 0.8
    assert observed["minAnnularRingMm"] == 0.45
    assert observed["drilledPadCount"] == 2
    assert observed["platedPadCount"] == 2
    assert (output_dir / "manifest.json").is_file()
    assert list((output_dir / "fabrication" / "gerbers").glob("*.g*"))
    assert list((output_dir / "fabrication" / "drill").glob("*.drl"))
    assert (output_dir / "assembly" / "manufacturing-smoke-bom.csv").is_file()
    assert (output_dir / "assembly" / "manufacturing-smoke-positions.csv").is_file()
    assert Path(result["archivePath"]) == Path(f"{output_dir}.zip")
    assert Path(result["archivePath"]).is_file()
