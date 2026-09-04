from pathlib import Path


def test_connect_to_net_accepts_schema_aliases(monkeypatch, tmp_path):
    from commands import schematic_handlers as module
    from commands.schematic_handlers import SchematicHandlers

    captured = {}

    def _fake_connect(schematic_path, component_ref, pin_name, net_name):
        captured["schematic_path"] = schematic_path
        captured["component_ref"] = component_ref
        captured["pin_name"] = pin_name
        captured["net_name"] = net_name
        return True

    monkeypatch.setattr(module.ConnectionManager, "connect_to_net", _fake_connect)

    handlers = SchematicHandlers()
    schematic_path = tmp_path / "demo.kicad_sch"
    result = handlers.connect_to_net(
        {
            "schematicPath": str(schematic_path),
            "reference": "U1",
            "pinNumber": "1",
            "netName": "USB_D_P",
        }
    )

    assert result["success"] is True
    assert captured == {
        "schematic_path": Path(schematic_path),
        "component_ref": "U1",
        "pin_name": "1",
        "net_name": "USB_D_P",
    }
