from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

from commands.library import LibraryManager


def test_library_manager_discovers_pretty_dirs_without_fp_lib_table(tmp_path, monkeypatch):
    pretty_dir = tmp_path / "Connector_PinHeader_2.54mm.pretty"
    pretty_dir.mkdir()
    (pretty_dir / "PinHeader_1x04_P2.54mm_Vertical.kicad_mod").write_text(
        '(footprint "PinHeader_1x04_P2.54mm_Vertical")\n',
        encoding="utf-8",
    )

    monkeypatch.setattr(LibraryManager, "_get_global_fp_lib_table", lambda self: None)
    monkeypatch.setattr(LibraryManager, "_candidate_footprint_roots", lambda self: [tmp_path])

    manager = LibraryManager()

    assert manager.get_library_path("Connector_PinHeader_2.54mm") == str(pretty_dir)
    assert manager.find_footprint(
        "Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical"
    ) == (str(pretty_dir), "PinHeader_1x04_P2.54mm_Vertical")
    assert manager.search_footprints("*PinHeader_1x04_P2.54mm_Vertical*", limit=5) == [
        {
            "library": "Connector_PinHeader_2.54mm",
            "footprint": "PinHeader_1x04_P2.54mm_Vertical",
            "full_name": "Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical",
        }
    ]
