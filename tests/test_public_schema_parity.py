from schemas.tool_schemas import TOOL_SCHEMAS


def _properties(tool_name):
    return TOOL_SCHEMAS[tool_name]["inputSchema"]["properties"]


def test_python_cfha_schema_advertises_node_orchestration_controls():
    properties = _properties("autoroute_cfha")

    assert {
        "strategy",
        "placementRoutingCorridors",
        "matchedLengthGroups",
        "qorWeights",
        "skipBulkRoute",
        "autoTuneMatchedLengths",
        "autoHealSupportNets",
        "referenceZoneLayer",
        "reportPath",
        "qorReportPath",
    }.issubset(properties)


def test_python_manufacturing_schema_advertises_node_export_controls():
    readiness = _properties("analyze_manufacturing_readiness")
    package = _properties("prepare_manufacturing_package")

    assert "reportPath" in readiness
    assert "gerberLayers" in package
    assert package["gerberPrecision"] == {
        "type": "integer",
        "minimum": 5,
        "maximum": 6,
    }
