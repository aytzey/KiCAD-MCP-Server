import csv
import json
import zipfile
from pathlib import Path
from types import SimpleNamespace
from typing import Tuple, Union

import pcbnew
import pytest

from commands.manufacturing import ManufacturingCommands


def _vec(x_mm: float, y_mm: float):
    return SimpleNamespace(x=int(x_mm * 1_000_000), y=int(y_mm * 1_000_000))


class _Box:
    def GetWidth(self):
        return 100_000_000

    def GetHeight(self):
        return 80_000_000

    def GetLeft(self):
        return 0

    def GetTop(self):
        return 0

    def GetRight(self):
        return 100_000_000

    def GetBottom(self):
        return 80_000_000


class _Pad:
    def __init__(
        self,
        x: float,
        y: float,
        drill: Union[float, Tuple[float, float]] = 0.0,
        *,
        size: Union[float, Tuple[float, float]] = 1.0,
        attribute=None,
    ):
        self._position = _vec(x, y)
        drill_x, drill_y = drill if isinstance(drill, tuple) else (drill, drill)
        size_x, size_y = size if isinstance(size, tuple) else (size, size)
        self._drill = _vec(drill_x, drill_y)
        self._size = _vec(size_x, size_y)
        self._attribute = attribute

    def GetSize(self):
        return self._size

    def GetDrillSize(self):
        return self._drill

    def GetPosition(self):
        return self._position

    def GetAttribute(self):
        return self._attribute


class _Fpid:
    def GetUniStringLibId(self):
        return "Package_SO:SOIC-8"


class _Footprint:
    def __init__(
        self,
        reference: str = "U1",
        properties=None,
        *,
        excluded: bool = False,
        dnp: bool = False,
        pads=None,
    ):
        self.reference = reference
        self.properties = properties or {}
        self.excluded = excluded
        self.dnp = dnp
        self.pads = pads

    def GetReference(self):
        return self.reference

    def GetValue(self):
        return "MCU"

    def GetFPID(self):
        return _Fpid()

    def Pads(self):
        return self.pads if self.pads is not None else [_Pad(10, 10), _Pad(11.27, 10)]

    def GetProperties(self):
        return self.properties

    def GetFields(self):
        return []

    def IsExcludedFromBOM(self):
        return self.excluded

    def IsDNP(self):
        return self.dnp


class _Drawing:
    def GetLayer(self):
        return 44


class _Board:
    def __init__(self, path: Path, layers: int = 2, footprints=None):
        self.path = path
        self.layers = layers
        self.footprints = footprints if footprints is not None else [_Footprint()]

    def GetFileName(self):
        return str(self.path)

    def GetCopperLayerCount(self):
        return self.layers

    def GetBoardEdgesBoundingBox(self):
        return _Box()

    def GetDrawings(self):
        return [_Drawing()] * 4

    def GetLayerID(self, name):
        assert name == "Edge.Cuts"
        return 44

    def GetFootprints(self):
        return self.footprints

    def GetTracks(self):
        return []

    def GetDesignSettings(self):
        return SimpleNamespace(
            m_TrackMinWidth=200_000,
            m_MinClearance=200_000,
            m_MinThroughDrill=300_000,
            m_ViasMinAnnularWidth=150_000,
            m_CopperEdgeClearance=250_000,
        )


def _drc_clean(_params):
    return {
        "success": True,
        "summary": {
            "total": 0,
            "by_severity": {"error": 0, "warning": 0, "info": 0},
            "by_type": {},
        },
    }


def _placement_clean(_params):
    return {"success": True, "overlaps": [], "boundary_violations": []}


def _commands(board, **kwargs):
    return ManufacturingCommands(
        board,
        run_drc=kwargs.get("run_drc", _drc_clean),
        check_placement=kwargs.get("check_placement", _placement_clean),
        export_gerbers=kwargs.get("export_gerbers"),
        export_drill=kwargs.get("export_drill"),
        export_position=kwargs.get("export_position"),
        export_bom=kwargs.get("export_bom"),
        export_schematic_bom=kwargs.get("export_schematic_bom"),
    )


def test_hand_assembly_two_layer_board_passes_conservative_preflight(tmp_path):
    board_path = tmp_path / "demo.kicad_pcb"
    board_path.write_text("(kicad_pcb)", encoding="utf-8")

    result = _commands(_Board(board_path)).analyze_manufacturing_readiness({})

    assert result["success"] is True
    assert result["ready"] is True
    assert result["assemblyMode"] == "hand"
    assert result["summary"]["copperLayers"] == ["F.Cu", "B.Cu"]
    assert result["summary"]["blockers"] == 0


def _analyze_single_pad(tmp_path, pad):
    board_path = tmp_path / "drilled-pad.kicad_pcb"
    board_path.write_text("(kicad_pcb)", encoding="utf-8")
    footprint = _Footprint(pads=[pad])
    return _commands(_Board(board_path, footprints=[footprint])).analyze_manufacturing_readiness(
        {"runDrc": False}
    )


def test_pth_pad_drill_is_checked_even_when_drc_is_disabled(tmp_path):
    result = _analyze_single_pad(tmp_path, _Pad(10, 10, drill=0.2, size=0.6))

    assert result["ready"] is False
    assert any(issue["code"] == "fab_limit_drillMm" for issue in result["issues"])
    assert result["fabrication"]["observed"]["minDrillMm"] == 0.2
    assert result["fabrication"]["observed"]["drilledPadCount"] == 1
    assert result["fabrication"]["observed"]["platedPadCount"] == 1


def test_pth_pad_annular_ring_is_checked_even_when_drc_is_disabled(tmp_path):
    result = _analyze_single_pad(tmp_path, _Pad(10, 10, drill=0.3, size=0.5))

    assert result["ready"] is False
    assert any(issue["code"] == "fab_limit_annularRingMm" for issue in result["issues"])
    assert result["fabrication"]["observed"]["minAnnularRingMm"] == 0.1


def test_npth_pad_checks_drill_but_not_annular_ring(tmp_path):
    result = _analyze_single_pad(
        tmp_path,
        _Pad(10, 10, drill=0.2, size=0.2, attribute=pcbnew.PAD_ATTRIB_NPTH),
    )

    codes = {issue["code"] for issue in result["issues"]}
    assert "fab_limit_drillMm" in codes
    assert "fab_limit_annularRingMm" not in codes
    assert result["fabrication"]["observed"]["npthPadCount"] == 1
    assert result["fabrication"]["observed"]["platedPadCount"] == 0


def test_oval_pad_uses_narrow_drill_axis_and_axis_specific_ring(tmp_path):
    result = _analyze_single_pad(
        tmp_path,
        _Pad(10, 10, drill=(0.2, 1.0), size=(0.6, 1.4)),
    )

    assert result["fabrication"]["observed"]["minDrillMm"] == 0.2
    assert result["fabrication"]["observed"]["minAnnularRingMm"] == 0.2
    assert any(issue["code"] == "fab_limit_drillMm" for issue in result["issues"])
    assert not any(issue["code"] == "fab_limit_annularRingMm" for issue in result["issues"])


def test_safe_pth_pad_meets_drill_and_annular_ring_limits(tmp_path):
    result = _analyze_single_pad(tmp_path, _Pad(10, 10, drill=0.3, size=0.6))

    assert result["ready"] is True
    assert result["fabrication"]["observed"] == {
        "minTrackWidthMm": None,
        "minDrillMm": 0.3,
        "minAnnularRingMm": 0.15,
        "trackCount": 0,
        "viaCount": 0,
        "drilledPadCount": 1,
        "platedPadCount": 1,
        "npthPadCount": 0,
    }


def test_four_layer_board_is_a_hard_blocker(tmp_path):
    board_path = tmp_path / "demo.kicad_pcb"
    board_path.write_text("(kicad_pcb)", encoding="utf-8")
    result = _commands(_Board(board_path, layers=4)).analyze_manufacturing_readiness({})

    assert result["ready"] is False
    assert any(issue["code"] == "not_two_layer" for issue in result["issues"])


def test_smt_mode_requires_traceable_part_numbers_by_default(tmp_path):
    board_path = tmp_path / "demo.kicad_pcb"
    board_path.write_text("(kicad_pcb)", encoding="utf-8")
    result = _commands(_Board(board_path)).analyze_manufacturing_readiness({"assemblyMode": "smt"})

    assert result["ready"] is False
    assert any(issue["code"] == "assembly_part_numbers_missing" for issue in result["issues"])


def test_board_bom_preserves_procurement_fields_and_never_merges_different_mpns(tmp_path):
    board_path = tmp_path / "demo.kicad_pcb"
    footprints = [
        _Footprint(
            "U1",
            {
                "Manufacturer": "Acme",
                "MPN": "ACME-100",
                "Supplier": "LCSC",
                "LCSC": "C100",
                "Tolerance": "1%",
            },
        ),
        _Footprint(
            "U2",
            {
                "Manufacturer": "Acme",
                "MPN": "ACME-200",
                "Supplier": "LCSC",
                "LCSC": "C200",
                "Tolerance": "1%",
            },
        ),
        _Footprint("U3", {"MPN": "NOFIT"}, dnp=True),
        _Footprint("U4", {"MPN": "EXCLUDED"}, excluded=True),
    ]
    commands = _commands(_Board(board_path, footprints=footprints))
    output = tmp_path / "bom.csv"

    result = commands._write_board_bom(output)

    assert result["success"] is True
    with output.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 2
    assert {row["References"] for row in rows} == {"U1", "U2"}
    assert {row["MPN"] for row in rows} == {"ACME-100", "ACME-200"}
    assert {row["Supplier Part Number"] for row in rows} == {"C100", "C200"}
    assert {row["Manufacturer"] for row in rows} == {"Acme"}
    assert {row["Property:tolerance"] for row in rows} == {"1%"}


def test_hand_mode_board_bom_without_procurement_fields_still_succeeds(tmp_path):
    output = tmp_path / "hand-bom.csv"
    result = _commands(_Board(tmp_path / "demo.kicad_pcb"))._write_board_bom(output)

    assert result["success"] is True
    row = next(csv.DictReader(output.open(encoding="utf-8", newline="")))
    assert row["References"] == "U1"
    assert row["MPN"] == ""


def test_preflight_blocker_prevents_any_export(tmp_path):
    board_path = tmp_path / "demo.kicad_pcb"
    board_path.write_text("(kicad_pcb)", encoding="utf-8")
    calls = []

    def exporter(_params):
        calls.append(True)
        return {"success": True}

    commands = _commands(
        _Board(board_path, layers=4),
        export_gerbers=exporter,
        export_drill=exporter,
        export_position=exporter,
        export_bom=exporter,
    )
    result = commands.prepare_manufacturing_package({"outputDir": str(tmp_path / "package")})

    assert result["success"] is False
    assert result["stage"] == "preflight"
    assert calls == []
    assert not (tmp_path / "package").exists()


def test_package_is_atomic_checksummed_and_zipped(tmp_path):
    board_path = tmp_path / "demo.kicad_pcb"
    board_path.write_text("(kicad_pcb)", encoding="utf-8")

    def gerbers(params):
        output = Path(params["outputDir"])
        output.mkdir(parents=True)
        (output / "demo-F_Cu.gbr").write_text("GERBER", encoding="utf-8")
        return {"success": True, "outputDir": str(output), "files": ["demo-F_Cu.gbr"]}

    def drill(params):
        output = Path(params["outputDir"])
        output.mkdir(parents=True)
        (output / "demo.drl").write_text("DRILL", encoding="utf-8")
        return {"success": True, "outputDir": str(output), "files": ["demo.drl"]}

    def position(params):
        Path(params["outputPath"]).write_text("Ref,PosX,PosY\nU1,10,10\n", encoding="utf-8")
        return {"success": True, "outputPath": params["outputPath"]}

    def bom(params):
        Path(params["outputPath"]).write_text("reference,value\nU1,MCU\n", encoding="utf-8")
        return {"success": True, "file": {"path": params["outputPath"]}}

    output_dir = tmp_path / "package.v1"
    result = _commands(
        _Board(board_path),
        export_gerbers=gerbers,
        export_drill=drill,
        export_position=position,
        export_bom=bom,
    ).prepare_manufacturing_package({"outputDir": str(output_dir)})

    assert result["success"] is True
    assert output_dir.is_dir()
    manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["readiness"]["ready"] is True
    assert manifest["unsafeOverride"] is False
    paths = {entry["path"] for entry in manifest["files"]}
    assert "fabrication/gerbers/demo-F_Cu.gbr" in paths
    assert "fabrication/drill/demo.drl" in paths
    assert "assembly/demo-bom.csv" in paths
    bom_text = (output_dir / "assembly" / "demo-bom.csv").read_text(encoding="utf-8")
    assert "Manufacturer,MPN,Supplier,Supplier Part Number" in bom_text
    assert all(len(entry["sha256"]) == 64 for entry in manifest["files"])

    archive_path = Path(result["archivePath"])
    assert archive_path == Path(f"{output_dir}.zip")
    assert archive_path.is_file()
    with zipfile.ZipFile(archive_path) as archive:
        assert "manifest.json" in archive.namelist()
        assert "assembly/demo-positions.csv" in archive.namelist()


def test_archive_failure_rolls_back_all_public_outputs(tmp_path, monkeypatch):
    board_path = tmp_path / "demo.kicad_pcb"
    board_path.write_text("(kicad_pcb)", encoding="utf-8")

    def gerbers(params):
        output = Path(params["outputDir"])
        output.mkdir(parents=True)
        (output / "demo-F_Cu.gbr").write_text("GERBER", encoding="utf-8")
        return {"success": True}

    def drill(params):
        output = Path(params["outputDir"])
        output.mkdir(parents=True)
        (output / "demo.drl").write_text("DRILL", encoding="utf-8")
        return {"success": True}

    def position(params):
        Path(params["outputPath"]).write_text("Ref,PosX,PosY\n", encoding="utf-8")
        return {"success": True}

    def bom(params):
        Path(params["outputPath"]).write_text("reference,value\n", encoding="utf-8")
        return {"success": True}

    def fail_zip(*_args, **_kwargs):
        raise OSError("simulated archive failure")

    monkeypatch.setattr("commands.manufacturing.zipfile.ZipFile", fail_zip)
    output_dir = tmp_path / "package"
    result = _commands(
        _Board(board_path),
        export_gerbers=gerbers,
        export_drill=drill,
        export_position=position,
        export_bom=bom,
    ).prepare_manufacturing_package({"outputDir": str(output_dir)})

    assert result["success"] is False
    assert not output_dir.exists()
    assert not Path(f"{output_dir}.zip").exists()
    assert not list(tmp_path.glob(".*.tmp"))


@pytest.mark.parametrize(
    ("failing_export", "expected_stage"),
    [
        ("gerbers", "gerbers"),
        ("drill", "drill"),
        ("positions", "positions"),
    ],
)
def test_export_failure_removes_staging_and_public_outputs(
    tmp_path, failing_export, expected_stage
):
    board_path = tmp_path / "demo.kicad_pcb"
    board_path.write_text("(kicad_pcb)", encoding="utf-8")

    def result_for(stage):
        if stage == failing_export:
            return {"success": False, "message": f"simulated {stage} failure"}
        return {"success": True}

    def gerbers(params):
        output = Path(params["outputDir"])
        output.mkdir(parents=True)
        (output / "partial.gbr").write_text("PARTIAL", encoding="utf-8")
        return result_for("gerbers")

    def drill(params):
        output = Path(params["outputDir"])
        output.mkdir(parents=True)
        (output / "partial.drl").write_text("PARTIAL", encoding="utf-8")
        return result_for("drill")

    def position(params):
        Path(params["outputPath"]).write_text("PARTIAL", encoding="utf-8")
        return result_for("positions")

    def bom(params):
        Path(params["outputPath"]).write_text("PARTIAL", encoding="utf-8")
        return result_for("bom")

    output_dir = tmp_path / "package"
    result = _commands(
        _Board(board_path),
        export_gerbers=gerbers,
        export_drill=drill,
        export_position=position,
        export_bom=bom,
    ).prepare_manufacturing_package({"outputDir": str(output_dir)})

    assert result["success"] is False
    assert result["stage"] == expected_stage
    assert not output_dir.exists()
    assert not Path(f"{output_dir}.zip").exists()
    assert not list(tmp_path.glob(".demo-manufacturing-*"))
    assert not list(tmp_path.glob(".package.zip.*.tmp"))
