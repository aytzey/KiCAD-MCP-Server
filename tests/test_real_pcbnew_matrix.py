import os
import sys
from pathlib import Path

import pytest

PYTHON_DIR = Path(__file__).parent.parent / "python"
sys.path.insert(0, str(PYTHON_DIR))

pytestmark = [
    pytest.mark.integration,
    pytest.mark.real_pcbnew,
    pytest.mark.linux,
]


@pytest.fixture(autouse=True)
def require_real_pcbnew() -> None:
    if os.environ.get("KICAD_USE_REAL_PCBNEW") != "1":
        pytest.skip("real pcbnew smoke tests require KICAD_USE_REAL_PCBNEW=1")


def test_project_commands_create_and_load_board_with_real_pcbnew(tmp_path: Path) -> None:
    import pcbnew
    from commands.project import ProjectCommands

    version = pcbnew.GetBuildVersion()
    assert version
    assert not str(version).endswith("-stub")

    commands = ProjectCommands()
    result = commands.create_project({"name": "matrix_smoke", "path": str(tmp_path)})

    assert result["success"] is True, result

    board_path = Path(result["project"]["boardPath"])
    assert board_path.exists()

    board = pcbnew.LoadBoard(str(board_path))
    assert board is not None
    assert hasattr(board, "GetFileName")
    assert board.GetFileName().endswith(".kicad_pcb")


def test_cfha_completion_rejects_partial_trace_with_real_connectivity() -> None:
    import pcbnew
    from commands.autoroute_cfha import AutorouteCFHACommands

    mm = pcbnew.FromMM
    board = pcbnew.BOARD()
    net = pcbnew.NETINFO_ITEM(board, "SIG")
    board.Add(net)
    pad_positions = [(10.0, 10.0), (30.0, 10.0)]
    for index, (x, y) in enumerate(pad_positions, start=1):
        footprint = pcbnew.FOOTPRINT(board)
        footprint.SetReference(f"J{index}")
        pad = pcbnew.PAD(footprint)
        pad.SetNumber("1")
        pad.SetShape(pcbnew.PAD_SHAPE_CIRCLE)
        pad.SetAttribute(pcbnew.PAD_ATTRIB_PTH)
        pad.SetSize(pcbnew.VECTOR2I(mm(1.6), mm(1.6)))
        pad.SetDrillSize(pcbnew.VECTOR2I(mm(0.8), mm(0.8)))
        pad.SetLayerSet(pad.PTHMask())
        pad.SetPosition(pcbnew.VECTOR2I(mm(x), mm(y)))
        pad.SetNet(net)
        footprint.Add(pad)
        board.Add(footprint)

    commands = AutorouteCFHACommands(board=board)
    intents = {"intents": [{"net_name": "SIG", "intent": "GENERIC"}]}
    bare = commands._completion_snapshot(board, intents)

    track = pcbnew.PCB_TRACK(board)
    track.SetStart(pcbnew.VECTOR2I(mm(10.0), mm(10.0)))
    track.SetEnd(pcbnew.VECTOR2I(mm(15.0), mm(10.0)))
    track.SetLayer(pcbnew.F_Cu)
    track.SetWidth(mm(0.25))
    track.SetNet(net)
    board.Add(track)
    partial = commands._completion_snapshot(board, intents)

    track.SetEnd(pcbnew.VECTOR2I(mm(30.0), mm(10.0)))
    complete = commands._completion_snapshot(board, intents)

    assert (bare["completionRate"], bare["unconnectedItemCount"]) == (0.0, 1)
    assert (partial["completionRate"], partial["unconnectedItemCount"]) == (0.0, 1)
    assert (complete["completionRate"], complete["unconnectedItemCount"]) == (1.0, 0)
    assert complete["completionVerified"] is True
