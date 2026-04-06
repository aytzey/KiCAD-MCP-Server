from unittest.mock import MagicMock


def test_create_project_blank_defaults_to_100mm_board_and_2_layers(tmp_path, monkeypatch):
    import pcbnew
    from commands.project import ProjectCommands

    board = MagicMock()
    title_block = MagicMock()
    board.GetTitleBlock.return_value = title_block
    pcbnew.BOARD.return_value = board
    pcbnew.SaveBoard.reset_mock()

    outline_calls = []

    def _fake_add_board_outline(self, params):
        outline_calls.append(params)
        return {"success": True}

    monkeypatch.setattr(
        "commands.board.outline.BoardOutlineCommands.add_board_outline",
        _fake_add_board_outline,
    )

    result = ProjectCommands().create_project({"name": "demo", "path": str(tmp_path)})

    assert result["success"] is True
    assert outline_calls == [
        {
            "shape": "rectangle",
            "params": {"x": 0, "y": 0, "width": 100.0, "height": 100.0, "unit": "mm"},
        }
    ]
    board.SetCopperLayerCount.assert_called_once_with(2)
    assert result["project"]["defaults"] == {
        "boardWidthMm": 100.0,
        "boardHeightMm": 100.0,
        "boardUnit": "mm",
        "copperLayers": 2,
    }


def test_create_project_allows_custom_blank_board_defaults(tmp_path, monkeypatch):
    import pcbnew
    from commands.project import ProjectCommands

    board = MagicMock()
    title_block = MagicMock()
    board.GetTitleBlock.return_value = title_block
    pcbnew.BOARD.return_value = board
    pcbnew.SaveBoard.reset_mock()

    outline_calls = []

    def _fake_add_board_outline(self, params):
        outline_calls.append(params)
        return {"success": True}

    monkeypatch.setattr(
        "commands.board.outline.BoardOutlineCommands.add_board_outline",
        _fake_add_board_outline,
    )

    result = ProjectCommands().create_project(
        {
            "name": "demo_custom",
            "path": str(tmp_path),
            "boardWidthMm": 80,
            "boardHeightMm": 60,
            "copperLayers": 4,
        }
    )

    assert result["success"] is True
    assert outline_calls == [
        {
            "shape": "rectangle",
            "params": {"x": 0, "y": 0, "width": 80.0, "height": 60.0, "unit": "mm"},
        }
    ]
    board.SetCopperLayerCount.assert_called_once_with(4)
    assert result["project"]["defaults"]["boardWidthMm"] == 80.0
    assert result["project"]["defaults"]["boardHeightMm"] == 60.0
    assert result["project"]["defaults"]["copperLayers"] == 4
