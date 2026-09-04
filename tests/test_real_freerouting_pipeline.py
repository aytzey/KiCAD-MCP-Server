"""Opt-in end-to-end smoke test for real KiCad plus the local Freerouting JAR."""

import os
import sys
from pathlib import Path

import pytest

PYTHON_DIR = Path(__file__).parent.parent / "python"
sys.path.insert(0, str(PYTHON_DIR))

pytestmark = [pytest.mark.integration, pytest.mark.real_pcbnew]


@pytest.fixture(autouse=True)
def require_real_freerouting() -> None:
    if os.environ.get("KICAD_USE_REAL_PCBNEW") != "1":
        pytest.skip("real Freerouting smoke test requires KICAD_USE_REAL_PCBNEW=1")
    if os.environ.get("KICAD_USE_REAL_FREEROUTING") != "1":
        pytest.skip("set KICAD_USE_REAL_FREEROUTING=1 to launch the local JAR")
    jar_path = Path(os.environ.get("FREEROUTING_JAR", ""))
    if not jar_path.is_file():
        pytest.skip("FREEROUTING_JAR must point to an installed Freerouting JAR")


def _build_board(pcbnew, board_path: Path):
    mm = pcbnew.FromMM
    board = pcbnew.BOARD()
    net = pcbnew.NETINFO_ITEM(board, "SIG")
    board.Add(net)

    for x1, y1, x2, y2 in (
        (0, 0, 40, 0),
        (40, 0, 40, 30),
        (40, 30, 0, 30),
        (0, 30, 0, 0),
    ):
        edge = pcbnew.PCB_SHAPE(board)
        edge.SetShape(pcbnew.SHAPE_T_SEGMENT)
        edge.SetStart(pcbnew.VECTOR2I(mm(x1), mm(y1)))
        edge.SetEnd(pcbnew.VECTOR2I(mm(x2), mm(y2)))
        edge.SetLayer(pcbnew.Edge_Cuts)
        edge.SetWidth(mm(0.1))
        board.Add(edge)

    for index, x in enumerate((10.0, 30.0), start=1):
        footprint = pcbnew.FOOTPRINT(board)
        footprint.SetReference(f"J{index}")
        footprint.SetValue("TEST_POINT")
        footprint.SetFPID(pcbnew.LIB_ID("TestPoint", "TestPoint_Plated_Hole_D2.0mm"))
        footprint.SetAttributes(pcbnew.FP_THROUGH_HOLE)
        pad = pcbnew.PAD(footprint)
        pad.SetNumber("1")
        pad.SetShape(pcbnew.PAD_SHAPE_CIRCLE)
        pad.SetAttribute(pcbnew.PAD_ATTRIB_PTH)
        pad.SetSize(pcbnew.VECTOR2I(mm(2.0), mm(2.0)))
        pad.SetDrillSize(pcbnew.VECTOR2I(mm(1.0), mm(1.0)))
        pad.SetLayerSet(pad.PTHMask())
        pad.SetPosition(pcbnew.VECTOR2I(mm(x), mm(15.0)))
        pad.SetNet(net)
        footprint.Add(pad)
        board.Add(footprint)

    pcbnew.SaveBoard(str(board_path), board)
    return board


def test_real_freerouting_routes_and_imports_a_two_pad_net(tmp_path: Path) -> None:
    import pcbnew
    from commands.freerouting import FreeroutingCommands

    board_path = tmp_path / "freerouting-smoke.kicad_pcb"
    board = _build_board(pcbnew, board_path)
    result = FreeroutingCommands(board).autoroute(
        {
            "boardPath": str(board_path),
            "freeroutingJar": os.environ["FREEROUTING_JAR"],
            "maxPasses": 5,
            "timeout": 120,
            "attempts": 1,
            "targetNets": ["SIG"],
        }
    )

    assert result["success"] is True, result
    assert result["mode"] == "direct"
    assert result["board_stats"]["tracks"] >= 1

    connectivity = pcbnew.CONNECTIVITY_DATA()
    connectivity.Build(board)
    connectivity.RecalculateRatsnest()
    assert connectivity.GetUnconnectedCount(False) == 0
