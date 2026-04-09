# Graph Report - .  (2026-04-10)

## Corpus Check
- 153 files · ~200,563 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 2250 nodes · 6237 edges · 193 communities detected
- Extraction: 45% EXTRACTED · 55% INFERRED · 0% AMBIGUOUS · INFERRED: 3452 edges (avg confidence: 0.5)
- Token cost: 0 input · 0 output

## God Nodes (most connected - your core abstractions)
1. `KiCADInterface` - 272 edges
2. `PinLocator` - 213 edges
3. `WireManager` - 178 edges
4. `ConnectionManager` - 151 edges
5. `WireDragger` - 135 edges
6. `LibraryManager` - 128 edges
7. `ComponentCommands` - 127 edges
8. `IPCBackend` - 124 edges
9. `SchematicManager` - 118 edges
10. `RoutingCommands` - 117 edges

## Surprising Connections (you probably didn't know these)
- `KiCAD IPC API Backend` --semantically_similar_to--> `Visual Feedback / UI Reload Workflow`  [INFERRED] [semantically similar]
  CHANGELOG.md → docs/VISUAL_FEEDBACK.md
- `Tests for platform_helper utility  These are unit tests that work on all platf` --uses--> `PlatformHelper`  [INFERRED]
  tests/test_platform_helper.py → python/utils/platform_helper.py
- `Test platform detection functions` --uses--> `PlatformHelper`  [INFERRED]
  tests/test_platform_helper.py → python/utils/platform_helper.py
- `Ensure exactly one platform is detected` --uses--> `PlatformHelper`  [INFERRED]
  tests/test_platform_helper.py → python/utils/platform_helper.py
- `Test platform name is human-readable` --uses--> `PlatformHelper`  [INFERRED]
  tests/test_platform_helper.py → python/utils/platform_helper.py

## Hyperedges (group relationships)
- **Schematic Wiring Subsystem (WireManager + PinLocator + DynamicSymbolLoader)** — concept_wire_manager, concept_pin_locator, concept_dynamic_symbol_loader [EXTRACTED 0.95]
- **Dual Backend System (SWIG + IPC with Factory Auto-Detection)** — concept_swig_backend, concept_ipc_backend, concept_backend_factory [EXTRACTED 0.95]
- **FFC/Ribbon Passthrough PCB Workflow** — tool_connect_passthrough, tool_sync_schematic_to_board, tool_route_pad_to_pad, tool_snapshot_project [EXTRACTED 0.95]
- **End-to-End PCB Design Workflow** — pcb_workflow_stage1_project_setup, pcb_workflow_stage2_schematic, pcb_workflow_stage3_layout, pcb_workflow_stage4_verification, pcb_workflow_stage5_manufacturing [EXTRACTED 1.00]
- **Router Pattern: Registry + Router Tools + Direct Tools** — mcp_router_guide_tool_registry, mcp_router_guide_router_tools, mcp_router_guide_direct_tools [EXTRACTED 1.00]
- **kicad-skip Limitation Workaround: Template + Injection + Clone** — archive_dynamic_library_kicad_skip_limitation, archive_schematic_template_approach, archive_dynamic_library_symbol_inject [EXTRACTED 0.95]

## Communities

### Community 0 - "KiCAD Interface Dispatcher"
Cohesion: 0.01
Nodes (72): KiCADInterface, main(), Get a rasterised image of the schematic (SVG export → optional PNG conversion), Annotate unannotated components in schematic (R? -> R1, R2, ...), Add a track using IPC backend (real-time), Add a via using IPC backend (real-time), Add text using IPC backend (real-time), Add a component to a schematic using text-based injection (no sexpdata) (+64 more)

### Community 1 - "Schematic Connection Engine"
Cohesion: 0.02
Nodes (152): Return True if the candidate label point is too close to an existing label., Reject paths that would create wire-wire crossings or overlaps., Return True if any segment passes through another symbol body., Connect a component pin to a named net using a wire stub and label          Ar, Manage connections between components in schematics, Connect all pins of source_ref to matching pins of target_ref via shared net lab, Get or create pin locator instance, Get all connections for a named net using wire graph analysis          Args: (+144 more)

### Community 2 - "Board & Component Commands"
Cohesion: 0.15
Nodes (165): AutorouteCFHACommands, Constraint-first hybrid autorouting commands., ComponentCommands, Move an existing component to a new position, Handles component-related KiCAD operations, Initialize with optional board instance and library manager, Rotate an existing component, Delete a component from the PCB (+157 more)

### Community 3 - "Backend API Abstraction"
Cohesion: 0.03
Nodes (93): ABC, APINotAvailableError, BackendError, BoardAPI, ConnectionError, KiCADBackend, Abstract base class for KiCAD API backends  Defines the interface that all KiC, Abstract interface for board operations (+85 more)

### Community 4 - "TypeScript MCP Layer"
Cohesion: 0.03
Nodes (58): Board-related command implementations for KiCAD interface  This file is mainta, Component-related command implementations for KiCAD interface, Design rules command implementations for KiCAD interface, Export command implementations for KiCAD interface, BoardCommands, Tests for KiCAD MCP Server, Handles board-related KiCAD operations, Initialize with optional board instance (+50 more)

### Community 5 - "Wire Junction Tests"
Cohesion: 0.03
Nodes (40): _find_elements(), _make_sch_data_with_wires(), _make_temp_sch(), _parse_sch(), Tests for fix/tool-schema-descriptions branch changes: - add_schematic_wire: wa, Polyline with exactly 2 points should produce 1 wire segment., Verify KiCADInterface registers the right tool handlers., Unit tests for _handle_add_schematic_wire validation paths (no disk I/O). (+32 more)

### Community 6 - "Wire Preservation Tests"
Cohesion: 0.06
Nodes (30): _make_junction(), _make_lib_symbol_r(), _make_sch_data(), _make_symbol(), _make_wire(), Tests for move_schematic_component with wire preservation (WireDragger).  Unit, Build a minimal sch_data list with lib_symbols and sheet_instances., Device:R at (0, 0) rot=0 — pin 1 is above and pin 2 is below in schematic space. (+22 more)

### Community 7 - "Schematic Tool Tests"
Cohesion: 0.04
Nodes (17): _make_handler_under_test(), Tests for schematic inspection and editing tools added in the schematic_tools br, Integration tests that read/write real .kicad_sch files., Deleting a wire must not remove unrelated elements., Return the unbound handler method from kicad_interface by importing only     th, Verify that each new handler returns success=False with an informative     mess, Return a stub that exposes only the handler methods under test., Write *content* to a temp file and return its Path. (+9 more)

### Community 8 - "Freerouting Tests"
Cohesion: 0.04
Nodes (22): _patch_direct_java(), _patch_docker_mode(), _patch_no_runtime(), Tests for the Freerouting autoroute integration.  Covers:   - FreeroutingCommand, Reset pcbnew mock before each test., Patch to simulate Java 21+ available locally., Patch to simulate Docker execution mode., Patch to simulate no Java and no Docker. (+14 more)

### Community 9 - "Platform Helper Tests"
Cohesion: 0.05
Nodes (25): Tests for platform_helper utility  These are unit tests that work on all platf, Relative XDG_CACHE_HOME should be ignored on Linux., Test that Python executable path is valid, Test that library search paths returns a list, Test the detect_platform convenience function, Test that detect_platform returns a dictionary, Test that detect_platform includes all required keys, Test that Python version is in correct format (+17 more)

### Community 10 - "CFHA Autorouter Core"
Cohesion: 0.09
Nodes (17): BackendAvailability, _best_intent(), compile_kicad_dru(), _condition_for_nets(), _diff_partner_name(), HybridRouteApplier, _norm(), _profile_merge() (+9 more)

### Community 11 - "Wire Junction Rationale"
Cohesion: 0.08
Nodes (16): _fn(), Unit tests for WireManager._point_strictly_on_wire geometry helper., Point at wire start should NOT be strictly on wire., Point at wire end should NOT be strictly on wire., Point above a horizontal wire., Point to the right of a vertical wire., Point collinear but past the end of a horizontal wire., Point collinear but past the end of a vertical wire. (+8 more)

### Community 12 - "Dynamic Symbol Loader"
Cohesion: 0.06
Nodes (24): _default_field_positions(), _effects_block(), _project_instance_name(), Dynamic Symbol Loader for KiCad Schematics  Loads symbols from .kicad_sym librar, Find all KiCad symbol library directories, Find the .kicad_sym file for a given library name.          Search order:, Parse a sym-lib-table file and return the resolved path for the given library ni, Resolve environment variables in a sym-lib-table URI. (+16 more)

### Community 13 - "Wire Connectivity Tests"
Cohesion: 0.08
Nodes (9): _make_point(), _make_schematic(), _make_wire(), Tests for the wire_connectivity module and the get_wire_connections handler., Handler returns error responses for bad or missing parameters., Return a bound _handle_get_wire_connections without full init., Unit tests for the pure-logic functions in wire_connectivity., TestCoreLogic (+1 more)

### Community 14 - "PCB Routing Engine"
Cohesion: 0.08
Nodes (16): _bbox_to_rect_mm(), Routing-related command implementations for KiCAD interface, Return the union of all pad bounding boxes for a footprint., Escape from a pad to the nearest outside edge of its footprint keepout., Route a differential pair between two sets of points or pads, Convert point specification to KiCAD point, Collect inflated copper keepouts for simple obstacle-aware routing.          Foo, Plan a simple orthogonal route around inflated board obstacles. (+8 more)

### Community 15 - "Architecture Archive"
Cohesion: 0.08
Nodes (30): KiCAD Backend Abstraction Layer (base/ipc/swig/factory), IPC->SWIG Auto-Detect Fallback Decision, IPC API Migration Plan (archived), JLCPCB Package to KiCAD Footprint Mapping, Conditional Tool Registration (Phase 2 plan), Router Implementation Status (archived, Phase 1 complete), Decision: Migrate to IPC API Immediately, SWIG Deprecation Discovery (KiCAD 10 removal) (+22 more)

### Community 16 - "JLCPCB & Datasheet Tools"
Cohesion: 0.09
Nodes (27): Dynamic Loading MCP Integration (100% passing), Basic Parts Preference for Cost Optimization, JLCPCB Parts Integration Plan (archived), JLCPCB SQLite Local Cache Architecture, Pin Absolute Position Calculation Algorithm, enrich_datasheets Tool (LCSC URL fill), get_datasheet_url Tool, LCSC Datasheet URL Construction (no API key) (+19 more)

### Community 17 - "Orthogonal Router Algorithm"
Cohesion: 0.14
Nodes (25): compress_path(), inflate_rect(), manhattan_distance(), manhattan_path_length(), normalize_rect(), pick_escape_point(), plan_orthogonal_path(), point_in_rect() (+17 more)

### Community 18 - "Core Architecture Concepts"
Cohesion: 0.13
Nodes (24): Changelog v2.0.0-alpha, Backend Factory Auto-Detection, KiCAD IPC API Backend, IPC UNIX Socket Connection, kicad_interface.py Main Entry Point, kicad-python (kipy) Library, Model Context Protocol (MCP), Python KiCAD Interface Layer (+16 more)

### Community 19 - "Library Symbol Management"
Cohesion: 0.11
Nodes (10): Library management for KiCAD symbols  Handles parsing sym-lib-table files, disco, Information about a symbol in a library, Parse a .kicad_sym file to extract symbol metadata          Args:             li, Extract properties from a symbol block, List all symbols in a library          Args:             library_nickname: Libra, Search for symbols matching a query          Args:             query: Search que, Score how well a symbol matches a query          Returns:             Score (0 =, Get information about a specific symbol          Args:             library_nickn (+2 more)

### Community 20 - "Freerouting Integration"
Cohesion: 0.16
Nodes (14): _build_freerouting_cmd(), _docker_available(), _find_docker(), _find_java(), _java_version_ok(), Freerouting autoroute integration for KiCAD MCP Server.  Exports the board to Sp, Determine how to run Freerouting: direct or docker.          Returns dict with ', Run Freerouting autorouter on the current board.          Flow:         1. Expor (+6 more)

### Community 21 - "MCP Resource Definitions"
Cohesion: 0.11
Nodes (17): _get_board_info(), _get_board_preview(), _get_components(), _get_design_rules(), _get_layers(), _get_nets(), _get_project_info(), handle_resource_read() (+9 more)

### Community 22 - "Symbol Creator Engine"
Cohesion: 0.17
Nodes (11): _esc(), _fmt(), _pin_lines(), _polyline_lines(), _property_block(), Symbol Creator for KiCAD MCP Server  Creates and edits .kicad_sym symbol library, Remove a symbol from a .kicad_sym library., Register a .kicad_sym library in KiCAD's sym-lib-table.          Parameters (+3 more)

### Community 23 - "SVG Import Pipeline"
Cohesion: 0.19
Nodes (17): _apply_transform(), _bounding_box(), _build_gr_poly(), _extract_polygons_from_element(), _get_attr(), _identity(), import_svg_to_pcb(), _mat_mul() (+9 more)

### Community 24 - "IPC Backend Tests"
Cohesion: 0.17
Nodes (16): Test adding a track in real-time (appears immediately in KiCAD UI)., Test adding a via in real-time (appears immediately in KiCAD UI)., Test adding text in real-time., Test getting the current selection from KiCAD UI., Run all IPC backend tests., Test basic IPC connection to KiCAD., Test board access and component listing., Test getting board information. (+8 more)

### Community 25 - "Module Group 25"
Cohesion: 0.33
Nodes (16): add_kicad_to_python_path(), detect_platform(), ensure_directories(), get_cache_dir(), get_config_dir(), get_kicad_library_search_paths(), get_kicad_python_path(), get_kicad_python_paths() (+8 more)

### Community 26 - "Module Group 26"
Cohesion: 0.14
Nodes (5): add_component(), get_dynamic_loader(), get_or_create_template(), Snap schematic placements to the conventional KiCad connection grid., _snap_schematic_coordinate()

### Community 27 - "Module Group 27"
Cohesion: 0.14
Nodes (16): Changelog v2.2.2-alpha, Changelog v2.2.3, KICAD_MCP_DEV Developer Mode, SVG to PCB Polygon Conversion, Routing Tools Reference Documentation, SVG Import Guide, CairoSVG Rendering Library, MCP Tool: connect_passthrough (+8 more)

### Community 28 - "Module Group 28"
Cohesion: 0.21
Nodes (10): _esc(), _fmt(), _new_uuid(), _pad_lines(), Footprint Creator for KiCAD MCP Server  Creates and edits .kicad_mod footprint f, Format a float without unnecessary trailing zeros., Register a .pretty library in KiCAD's fp-lib-table so KiCAD can find it., Escape double-quotes inside S-Expression string values. (+2 more)

### Community 29 - "Module Group 29"
Cohesion: 0.14
Nodes (9): _generate_nonce(), JLCPCB API client for fetching parts data  Handles authentication and download, Generate the Authorization header for JLCPCB API requests          Args:, Fetch one page of parts from JLCPCB API          Args:             last_key:, Download entire parts library from JLCPCB          Args:             callback, Test JLCPCB API connection      Args:         app_id: Optional App ID (uses e, Build the signature string according to JLCPCB spec          Format:, Sign the signature string with HMAC-SHA256          Args:             signatu (+1 more)

### Community 30 - "Module Group 30"
Cohesion: 0.26
Nodes (13): compute_pin_positions(), _coords_match(), drag_wires(), find_symbol(), get_all_stationary_pin_positions(), get_pin_defs(), _make_wire_sexp(), pin_world_xy() (+5 more)

### Community 31 - "Module Group 31"
Cohesion: 0.14
Nodes (7): Parse sym-lib-table file          Format is S-expression (Lisp-like):         (s, Resolve environment variables and paths in library URI          Handles:, Find KiCAD symbol directory, Find KiCAD 3rd party library directory (PCM installed libs), Initialize symbol library manager          Args:             project_path: Optio, Load libraries from sym-lib-table files, Get path to global sym-lib-table file

### Community 32 - "Module Group 32"
Cohesion: 0.23
Nodes (8): add_junction(), add_polyline_wire(), add_wire(), _break_wires_at_point(), _make_wire_sexp(), _parse_wire(), _point_strictly_on_wire(), Wire Manager for KiCad Schematics  Handles wire creation using S-expression ma

### Community 33 - "Module Group 33"
Cohesion: 0.14
Nodes (8): JLCSearch API client (public, no authentication required)  Alternative to offi, Search for capacitors          Args:             capacitance: Capacitance val, Get part details by LCSC number          Args:             lcsc_number: LCSC, Download all components from jlcsearch database          Note: tscircuit API h, Test JLCSearch API connection      Returns:         True if connection succes, Search components in JLCSearch database          Args:             category:, Search for resistors          Args:             resistance: Resistance value, test_jlcsearch_connection()

### Community 34 - "Module Group 34"
Cohesion: 0.14
Nodes (7): Resolve environment variables and paths in library URI          Handles:, Find KiCAD footprint directory, Find KiCAD 3rd party libraries directory.          Resolution order:, Initialize library manager          Args:             project_path: Optional, Load libraries from fp-lib-table files, Get path to global fp-lib-table file, Parse fp-lib-table file          Format is S-expression (Lisp-like):

### Community 35 - "Module Group 35"
Cohesion: 0.22
Nodes (4): buildPythonEnv(), defaultPythonPath(), findPythonExecutable(), KiCADMcpServer

### Community 36 - "Module Group 36"
Cohesion: 0.27
Nodes (10): connect_passthrough(), connect_to_net(), _direction_from_angle(), generate_netlist(), get_net_connections(), get_pin_locator(), _path_crosses_wires(), _path_hits_symbol_bboxes() (+2 more)

### Community 37 - "Module Group 37"
Cohesion: 0.23
Nodes (11): _extract_blocks(), _extract_courtyard(), _extract_pads(), parse_kicad_mod(), Parser for KiCad .kicad_mod footprint files.  Extracts the fields that the MCP, Parse all (pad …) blocks and return a list of pad objects.      Each object ha, Reverse KiCad S-expression string escaping., Return all S-expression blocks that start with `(token ` by tracking     parent (+3 more)

### Community 38 - "Module Group 38"
Cohesion: 0.18
Nodes (12): Changelog v2.1.0-alpha, DynamicSymbolLoader, Custom Footprint Creator Tools, PinLocator Pin Discovery, Intelligent Schematic Wiring System, S-expression File Injection, Wire Graph Connectivity Analysis, WireManager S-expression Engine (+4 more)

### Community 39 - "Module Group 39"
Cohesion: 0.22
Nodes (7): _find_lib_symbols_range(), _normalize_lcsc(), _process_symbol_block(), Datasheet Manager for KiCAD MCP Server  Enriches KiCAD schematic symbols with da, Scan a .kicad_sch file and fill in missing LCSC datasheet URLs.          For eac, Return the LCSC datasheet URL for a given LCSC number.         No network reques, Return the LCSC product page URL.

### Community 40 - "Module Group 40"
Cohesion: 0.18
Nodes (2): TestOrthogonalRouterHelpers, TestOrthogonalRouterPlanning

### Community 41 - "Module Group 41"
Cohesion: 0.2
Nodes (5): Export Bill of Materials, Export BOM to CSV format, Export BOM to XML format, Export BOM to HTML format, Export BOM to JSON format

### Community 42 - "Module Group 42"
Cohesion: 0.22
Nodes (2): getRegistryStats(), getRoutedToolNames()

### Community 43 - "Module Group 43"
Cohesion: 0.42
Nodes (8): check_and_launch_kicad(), get_executable_path(), get_process_info(), is_running(), launch(), KiCAD Process Management Utilities  Detects if KiCAD is running and provides a, Check if KiCAD is running and optionally launch it      Args:         project, _windows_list_processes()

### Community 44 - "Module Group 44"
Cohesion: 0.25
Nodes (5): Regression test: no MCP tool name is registered more than once across all TypeSc, Return list of (tool_name, file, line_no) for every server.tool() call., Every tool name must appear exactly once across all TS tool files., Sanity check: src/tools/ directory must be present and contain TS files., TestTsToolRegistry

### Community 45 - "Module Group 45"
Cohesion: 0.33
Nodes (1): Logger

### Community 46 - "Module Group 46"
Cohesion: 0.25
Nodes (9): kicad-skip Cannot Create Symbols from Scratch (constraint), Symbol Injection into lib_symbols via S-Expression, Offscreen Template Instance Creation Strategy, Symbol Library Parsing Cache (library_cache, symbol_cache), kicad-skip clone() API Usage, Template-Based Schematic Component Approach, kicad-skip Wire API Uncertainty (challenge), S-Expression Manipulation Fallback for Wiring (+1 more)

### Community 47 - "Module Group 47"
Cohesion: 0.36
Nodes (7): convert_to_mcp_format(), download_files(), extract_database(), main(), Download all split archive parts., Extract the split 7z archive to get cache.sqlite3., Convert jlcparts cache.sqlite3 to the MCP server's expected format.

### Community 48 - "Module Group 48"
Cohesion: 0.29
Nodes (4): Place components in a grid pattern and return the list of placed components, Place components in a circular pattern and return the list of placed components, Place a component on the PCB, Place an array of components in a grid or circular pattern

### Community 49 - "Module Group 49"
Cohesion: 0.25
Nodes (4): Align components horizontally and optionally distribute them, Align components vertically and optionally distribute them, Align components to the specified edge of the board, Align multiple components along a line or distribute them evenly

### Community 50 - "Module Group 50"
Cohesion: 0.25
Nodes (4): Modify properties of an existing trace          Allows changing trace width, l, Calculate distance from point to track segment, Calculate distance between two points, Delete a trace from the PCB

### Community 51 - "Module Group 51"
Cohesion: 0.43
Nodes (7): _make_temp_schematic(), Tests for DynamicSymbolLoader placement behavior., test_add_component_places_fields_outside_resistor_body(), test_create_component_instance_can_preserve_explicit_coordinates(), test_create_component_instance_snaps_to_grid_by_default(), test_create_component_instance_uses_actual_project_name_in_instances(), test_power_symbols_are_marked_as_non_board_items()

### Community 52 - "Module Group 52"
Cohesion: 0.29
Nodes (3): Export 3D model files using kicad-cli (KiCAD 9.0 compatible), Find kicad-cli executable in system PATH or common locations          Returns:, DEV MODE: Copy the MCP server log for the current session into the project folde

### Community 53 - "Module Group 53"
Cohesion: 0.29
Nodes (0): 

### Community 54 - "Module Group 54"
Cohesion: 0.6
Nodes (5): Write-Error-Custom(), Write-Info(), Write-Step(), Write-Success(), Write-Warning-Custom()

### Community 55 - "Module Group 55"
Cohesion: 0.33
Nodes (3): Run Design Rule Check using kicad-cli, Find kicad-cli executable, Get list of DRC violations          Note: This command internally uses run_drc

### Community 56 - "Module Group 56"
Cohesion: 0.33
Nodes (3): Search for parts with filters          Args:             query: Free-text sea, Get detailed information for specific LCSC part          Args:             lc, Find alternative parts similar to the given LCSC number          Prioritizes:

### Community 57 - "Module Group 57"
Cohesion: 0.33
Nodes (3): List all footprints in a library          Args:             library_nickname:, Search for footprints matching a pattern          Args:             pattern:, List all footprints in a specific library

### Community 58 - "Module Group 58"
Cohesion: 0.4
Nodes (2): list_available_libraries(), search_symbols()

### Community 59 - "Module Group 59"
Cohesion: 0.73
Nodes (5): _call_interface(), _interface_python(), main(), _python_env(), _repo_root()

### Community 60 - "Module Group 60"
Cohesion: 0.33
Nodes (1): KiCADServer

### Community 61 - "Module Group 61"
Cohesion: 0.4
Nodes (3): _FakeSchematic, Test configuration for python/tests.  Sets up sys.modules stubs for heavy KiCAD, Minimal stand-in for skip.Schematic used in PinLocator cache.

### Community 62 - "Module Group 62"
Cohesion: 0.8
Nodes (4): _make_temp_schematic(), test_connect_to_net_attaches_wire_to_actual_pin_location(), test_connect_to_net_respects_rotated_pin_coordinates(), _wire_touches_pin()

### Community 63 - "Module Group 63"
Cohesion: 0.6
Nodes (3): main(), parseCommandLineArgs(), setupGracefulShutdown()

### Community 64 - "Module Group 64"
Cohesion: 0.4
Nodes (5): KiCAD Bundled Python (Windows), Cross-Platform Support (Linux/Windows/macOS), Linux Compatibility Audit, Platform Guide Documentation, Windows Troubleshooting Guide

### Community 65 - "Module Group 65"
Cohesion: 0.5
Nodes (5): JLCPCB Parts Integration, JLCPCB Local SQLite Database, JLCSearch Public API Client, LCSC Datasheet Enrichment, Requests HTTP Library

### Community 66 - "Module Group 66"
Cohesion: 0.4
Nodes (5): STDIO Transport Architecture Decision, Claude Code CLI Configuration, Claude Desktop Configuration, Cline VSCode Extension Configuration, MCP Server Environment Variables

### Community 67 - "Module Group 67"
Cohesion: 0.5
Nodes (2): Find a symbol by specification          Supports multiple formats:         - "Li, Get information about a specific symbol

### Community 68 - "Module Group 68"
Cohesion: 0.5
Nodes (2): Get list of available library nicknames, List all available symbol libraries

### Community 69 - "Module Group 69"
Cohesion: 0.5
Nodes (2): Initialize parts database manager          Args:             db_path: Path to, Initialize SQLite database with schema

### Community 70 - "Module Group 70"
Cohesion: 0.5
Nodes (2): Determine if part is Basic, Extended, or Preferred, Import parts into database from JLCPCB API response          Args:

### Community 71 - "Module Group 71"
Cohesion: 0.5
Nodes (1): Library management for KiCAD footprints  Handles parsing fp-lib-table files, d

### Community 72 - "Module Group 72"
Cohesion: 0.5
Nodes (2): Find a footprint by specification          Supports multiple formats:, Get information about a specific footprint

### Community 73 - "Module Group 73"
Cohesion: 0.67
Nodes (2): _symbol(), test_auto_place_missing_footprints_uses_deterministic_grid_and_skips_missing_props()

### Community 74 - "Module Group 74"
Cohesion: 0.5
Nodes (0): 

### Community 75 - "Module Group 75"
Cohesion: 0.67
Nodes (0): 

### Community 76 - "Module Group 76"
Cohesion: 0.67
Nodes (0): 

### Community 77 - "Module Group 77"
Cohesion: 1.0
Nodes (3): Freerouting Autorouter Integration, Specctra DSN/SES Format, MCP Tool: autoroute (Freerouting)

### Community 78 - "Module Group 78"
Cohesion: 0.67
Nodes (3): Build and Test Session (Oct 2025, archived), PlatformHelper Utility (XDG spec, cross-platform paths), KiCAD Python Path Discovery

### Community 79 - "Module Group 79"
Cohesion: 1.0
Nodes (1): Get filesystem path for a library nickname

### Community 80 - "Module Group 80"
Cohesion: 1.0
Nodes (1): Search for symbols by query

### Community 81 - "Module Group 81"
Cohesion: 1.0
Nodes (1): Initialize with optional board instance

### Community 82 - "Module Group 82"
Cohesion: 1.0
Nodes (1): Add a new net to the PCB

### Community 83 - "Module Group 83"
Cohesion: 1.0
Nodes (1): Query traces by net, layer, or bounding box

### Community 84 - "Module Group 84"
Cohesion: 1.0
Nodes (1): Create a new net class with specified properties

### Community 85 - "Module Group 85"
Cohesion: 1.0
Nodes (1): Get a list of all nets in the PCB

### Community 86 - "Module Group 86"
Cohesion: 1.0
Nodes (1): Copy routing pattern from source components to target components          This

### Community 87 - "Module Group 87"
Cohesion: 1.0
Nodes (1): Add a copper pour (zone) to the PCB

### Community 88 - "Module Group 88"
Cohesion: 1.0
Nodes (1): Edit an existing pad in a .kicad_mod file.          Parameters         ---------

### Community 89 - "Module Group 89"
Cohesion: 1.0
Nodes (1): List all .pretty libraries and their footprints.

### Community 90 - "Module Group 90"
Cohesion: 1.0
Nodes (1): Initialize JLCPCB API client          Args:             app_id: JLCPCB App ID

### Community 91 - "Module Group 91"
Cohesion: 1.0
Nodes (1): Get detailed information for a specific LCSC part number          Note: This u

### Community 92 - "Module Group 92"
Cohesion: 1.0
Nodes (1): List all symbols in a .kicad_sym file.

### Community 93 - "Module Group 93"
Cohesion: 1.0
Nodes (1): Initialize JLCSearch API client

### Community 94 - "Module Group 94"
Cohesion: 1.0
Nodes (1): Initialize with optional board instance

### Community 95 - "Module Group 95"
Cohesion: 1.0
Nodes (1): Set design rules for the PCB

### Community 96 - "Module Group 96"
Cohesion: 1.0
Nodes (1): Get current design rules - KiCAD 9.0 compatible

### Community 97 - "Module Group 97"
Cohesion: 1.0
Nodes (1): Import parts into database from JLCSearch API response          Args:

### Community 98 - "Module Group 98"
Cohesion: 1.0
Nodes (1): Get statistics about the database

### Community 99 - "Module Group 99"
Cohesion: 1.0
Nodes (1): JLCPCB Parts Database Manager  Manages local SQLite database of JLCPCB parts f

### Community 100 - "Module Group 100"
Cohesion: 1.0
Nodes (1): Map JLCPCB package name to KiCAD footprint(s)          Args:             pack

### Community 101 - "Module Group 101"
Cohesion: 1.0
Nodes (1): Close database connection

### Community 102 - "Module Group 102"
Cohesion: 1.0
Nodes (1): Get list of available library nicknames

### Community 103 - "Module Group 103"
Cohesion: 1.0
Nodes (1): List all available footprint libraries

### Community 104 - "Module Group 104"
Cohesion: 1.0
Nodes (1): Get filesystem path for a library nickname

### Community 105 - "Module Group 105"
Cohesion: 1.0
Nodes (1): Get information about a specific footprint          Args:             library

### Community 106 - "Module Group 106"
Cohesion: 1.0
Nodes (1): Search for footprints by pattern

### Community 107 - "Module Group 107"
Cohesion: 1.0
Nodes (1): Initialize with optional board instance

### Community 108 - "Module Group 108"
Cohesion: 1.0
Nodes (1): Import a Specctra SES file into the board.

### Community 109 - "Module Group 109"
Cohesion: 1.0
Nodes (1): Export the board to Specctra DSN format only.

### Community 110 - "Module Group 110"
Cohesion: 1.0
Nodes (0): 

### Community 111 - "Module Group 111"
Cohesion: 1.0
Nodes (0): 

### Community 112 - "Module Group 112"
Cohesion: 1.0
Nodes (0): 

### Community 113 - "Module Group 113"
Cohesion: 1.0
Nodes (0): 

### Community 114 - "Module Group 114"
Cohesion: 1.0
Nodes (0): 

### Community 115 - "Module Group 115"
Cohesion: 1.0
Nodes (2): Dynamic Library Loading Plan (archived), Dynamic Symbol Loading Status (complete, prod-ready)

### Community 116 - "Module Group 116"
Cohesion: 1.0
Nodes (0): 

### Community 117 - "Module Group 117"
Cohesion: 1.0
Nodes (0): 

### Community 118 - "Module Group 118"
Cohesion: 1.0
Nodes (1): Check if running on Windows

### Community 119 - "Module Group 119"
Cohesion: 1.0
Nodes (1): Check if running on Linux

### Community 120 - "Module Group 120"
Cohesion: 1.0
Nodes (1): Check if running on macOS

### Community 121 - "Module Group 121"
Cohesion: 1.0
Nodes (1): Get human-readable platform name

### Community 122 - "Module Group 122"
Cohesion: 1.0
Nodes (1): Get potential KiCAD Python dist-packages paths for current platform          R

### Community 123 - "Module Group 123"
Cohesion: 1.0
Nodes (1): Get the first valid KiCAD Python path          Returns:             Path to K

### Community 124 - "Module Group 124"
Cohesion: 1.0
Nodes (1): Get platform-appropriate KiCAD symbol library search paths          Returns:

### Community 125 - "Module Group 125"
Cohesion: 1.0
Nodes (1): r"""         Get appropriate configuration directory for current platform

### Community 126 - "Module Group 126"
Cohesion: 1.0
Nodes (1): Get appropriate log directory for current platform          Returns:

### Community 127 - "Module Group 127"
Cohesion: 1.0
Nodes (1): r"""         Get appropriate cache directory for current platform          Fo

### Community 128 - "Module Group 128"
Cohesion: 1.0
Nodes (1): Create all necessary directories if they don't exist

### Community 129 - "Module Group 129"
Cohesion: 1.0
Nodes (1): Get path to current Python executable

### Community 130 - "Module Group 130"
Cohesion: 1.0
Nodes (1): Add KiCAD Python paths to sys.path          Returns:             True if at l

### Community 131 - "Module Group 131"
Cohesion: 1.0
Nodes (1): List running processes on Windows using Toolhelp API.

### Community 132 - "Module Group 132"
Cohesion: 1.0
Nodes (1): Check if KiCAD is currently running          Returns:             True if KiC

### Community 133 - "Module Group 133"
Cohesion: 1.0
Nodes (1): Get path to KiCAD executable          Returns:             Path to pcbnew/kic

### Community 134 - "Module Group 134"
Cohesion: 1.0
Nodes (1): Launch KiCAD PCB Editor          Args:             project_path: Optional pat

### Community 135 - "Module Group 135"
Cohesion: 1.0
Nodes (1): Get information about running KiCAD processes          Returns:             L

### Community 136 - "Module Group 136"
Cohesion: 1.0
Nodes (1): Create a new empty schematic from template

### Community 137 - "Module Group 137"
Cohesion: 1.0
Nodes (1): Load an existing schematic

### Community 138 - "Module Group 138"
Cohesion: 1.0
Nodes (1): Save a schematic to file

### Community 139 - "Module Group 139"
Cohesion: 1.0
Nodes (1): Extract metadata from schematic

### Community 140 - "Module Group 140"
Cohesion: 1.0
Nodes (1): Add a wire to the schematic using S-expression manipulation          Args:

### Community 141 - "Module Group 141"
Cohesion: 1.0
Nodes (1): Add a multi-segment wire (polyline) to the schematic          Args:

### Community 142 - "Module Group 142"
Cohesion: 1.0
Nodes (1): Add a net label to the schematic          Args:             schematic_path: P

### Community 143 - "Module Group 143"
Cohesion: 1.0
Nodes (1): Parse a wire S-expression item in a single pass.         Returns ((x1,y1), (x2,

### Community 144 - "Module Group 144"
Cohesion: 1.0
Nodes (1): Return True if (px, py) lies strictly between (x1,y1) and (x2,y2)         on a

### Community 145 - "Module Group 145"
Cohesion: 1.0
Nodes (1): Split any wire segment that passes through *position* as a strict         midpo

### Community 146 - "Module Group 146"
Cohesion: 1.0
Nodes (1): Add a junction (connection dot) to the schematic.          Mirrors KiCAD's Add

### Community 147 - "Module Group 147"
Cohesion: 1.0
Nodes (1): Add a no-connect flag to the schematic          Args:             schematic_p

### Community 148 - "Module Group 148"
Cohesion: 1.0
Nodes (1): Delete a wire from the schematic matching given start/end coordinates.

### Community 149 - "Module Group 149"
Cohesion: 1.0
Nodes (1): Delete a net label from the schematic by name (and optionally position).

### Community 150 - "Module Group 150"
Cohesion: 1.0
Nodes (1): Create an orthogonal (right-angle) path between two points          Args:

### Community 151 - "Module Group 151"
Cohesion: 1.0
Nodes (1): Convert a KiCad bounding box object to a normalized mm rectangle.

### Community 152 - "Module Group 152"
Cohesion: 1.0
Nodes (1): Return the union of rects, or None for an empty list.

### Community 153 - "Module Group 153"
Cohesion: 1.0
Nodes (1): Generate a 32-character random nonce

### Community 154 - "Module Group 154"
Cohesion: 1.0
Nodes (1): Search for components matching criteria (basic implementation)

### Community 155 - "Module Group 155"
Cohesion: 1.0
Nodes (1): List all available symbol libraries

### Community 156 - "Module Group 156"
Cohesion: 1.0
Nodes (1): List all symbols in a library

### Community 157 - "Module Group 157"
Cohesion: 1.0
Nodes (1): Get detailed information about a symbol

### Community 158 - "Module Group 158"
Cohesion: 1.0
Nodes (1): Search for symbols matching criteria

### Community 159 - "Module Group 159"
Cohesion: 1.0
Nodes (1): Get a recommended default symbol for a given component type

### Community 160 - "Module Group 160"
Cohesion: 1.0
Nodes (1): Normalize LCSC number to standard format 'C123456'.          Accepts: 'C123456',

### Community 161 - "Module Group 161"
Cohesion: 1.0
Nodes (1): Find the line range of the (lib_symbols ...) section.         Returns (start, en

### Community 162 - "Module Group 162"
Cohesion: 1.0
Nodes (1): Extract LCSC and Datasheet info from a placed symbol block.          Returns dic

### Community 163 - "Module Group 163"
Cohesion: 1.0
Nodes (1): Connect to KiCAD          Returns:             True if connection successful,

### Community 164 - "Module Group 164"
Cohesion: 1.0
Nodes (1): Disconnect from KiCAD and clean up resources

### Community 165 - "Module Group 165"
Cohesion: 1.0
Nodes (1): Check if currently connected to KiCAD          Returns:             True if c

### Community 166 - "Module Group 166"
Cohesion: 1.0
Nodes (1): Get KiCAD version          Returns:             Version string (e.g., "9.0.0"

### Community 167 - "Module Group 167"
Cohesion: 1.0
Nodes (1): Create a new KiCAD project          Args:             path: Directory path fo

### Community 168 - "Module Group 168"
Cohesion: 1.0
Nodes (1): Open an existing KiCAD project          Args:             path: Path to .kica

### Community 169 - "Module Group 169"
Cohesion: 1.0
Nodes (1): Save the current project          Args:             path: Optional new path t

### Community 170 - "Module Group 170"
Cohesion: 1.0
Nodes (1): Close the current project

### Community 171 - "Module Group 171"
Cohesion: 1.0
Nodes (1): Get board API for current project          Returns:             BoardAPI inst

### Community 172 - "Module Group 172"
Cohesion: 1.0
Nodes (1): Set board size          Args:             width: Board width             hei

### Community 173 - "Module Group 173"
Cohesion: 1.0
Nodes (1): Get current board size          Returns:             Dictionary with width, h

### Community 174 - "Module Group 174"
Cohesion: 1.0
Nodes (1): Add a layer to the board          Args:             layer_name: Name of the l

### Community 175 - "Module Group 175"
Cohesion: 1.0
Nodes (1): List all components on the board          Returns:             List of compon

### Community 176 - "Module Group 176"
Cohesion: 1.0
Nodes (1): Place a component on the board          Args:             reference: Componen

### Community 177 - "Module Group 177"
Cohesion: 1.0
Nodes (1): Pillow Image Processing Library

### Community 178 - "Module Group 178"
Cohesion: 1.0
Nodes (1): Pydantic Data Validation

### Community 179 - "Module Group 179"
Cohesion: 1.0
Nodes (1): python-dotenv Env Management

### Community 180 - "Module Group 180"
Cohesion: 1.0
Nodes (1): Colorlog Logging Library

### Community 181 - "Module Group 181"
Cohesion: 1.0
Nodes (1): Pytest Testing Framework

### Community 182 - "Module Group 182"
Cohesion: 1.0
Nodes (1): Black Code Formatter

### Community 183 - "Module Group 183"
Cohesion: 1.0
Nodes (1): MyPy Type Checker

### Community 184 - "Module Group 184"
Cohesion: 1.0
Nodes (1): Changelog v2.2.1-alpha

### Community 185 - "Module Group 185"
Cohesion: 1.0
Nodes (1): Changelog v2.2.0-alpha

### Community 186 - "Module Group 186"
Cohesion: 1.0
Nodes (1): Changelog v1.0.0

### Community 187 - "Module Group 187"
Cohesion: 1.0
Nodes (1): KiCAD UI Auto-Launch Feature

### Community 188 - "Module Group 188"
Cohesion: 1.0
Nodes (1): Visual Feedback Guide

### Community 189 - "Module Group 189"
Cohesion: 1.0
Nodes (1): UI Auto-Launch Guide

### Community 190 - "Module Group 190"
Cohesion: 1.0
Nodes (1): v1.0.0 Core Foundation Milestone

### Community 191 - "Module Group 191"
Cohesion: 1.0
Nodes (1): Planned Design Patterns and Templates

### Community 192 - "Module Group 192"
Cohesion: 1.0
Nodes (1): Schematic Wiring Implementation Plan (archived)

## Knowledge Gaps
- **424 isolated node(s):** `Download all split archive parts.`, `Extract the split 7z archive to get cache.sqlite3.`, `Convert jlcparts cache.sqlite3 to the MCP server's expected format.`, `Add a component to a schematic using text-based injection (no sexpdata)`, `Get a rasterised image of the schematic (SVG export → optional PNG conversion)` (+419 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **Thin community `Module Group 79`** (2 nodes): `Get filesystem path for a library nickname`, `.get_library_path()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 80`** (2 nodes): `Search for symbols by query`, `.search_symbols()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 81`** (2 nodes): `Initialize with optional board instance`, `.__init__()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 82`** (2 nodes): `Add a new net to the PCB`, `.add_net()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 83`** (2 nodes): `Query traces by net, layer, or bounding box`, `.query_traces()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 84`** (2 nodes): `Create a new net class with specified properties`, `.create_netclass()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 85`** (2 nodes): `Get a list of all nets in the PCB`, `.get_nets_list()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 86`** (2 nodes): `Copy routing pattern from source components to target components          This`, `.copy_routing_pattern()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 87`** (2 nodes): `Add a copper pour (zone) to the PCB`, `.add_copper_pour()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 88`** (2 nodes): `.edit_footprint_pad()`, `Edit an existing pad in a .kicad_mod file.          Parameters         ---------`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 89`** (2 nodes): `.list_footprint_libraries()`, `List all .pretty libraries and their footprints.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 90`** (2 nodes): `.__init__()`, `Initialize JLCPCB API client          Args:             app_id: JLCPCB App ID`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 91`** (2 nodes): `.get_part_by_lcsc()`, `Get detailed information for a specific LCSC part number          Note: This u`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 92`** (2 nodes): `List all symbols in a .kicad_sym file.`, `.list_symbols()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 93`** (2 nodes): `.__init__()`, `Initialize JLCSearch API client`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 94`** (2 nodes): `.__init__()`, `Initialize with optional board instance`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 95`** (2 nodes): `.set_design_rules()`, `Set design rules for the PCB`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 96`** (2 nodes): `.get_design_rules()`, `Get current design rules - KiCAD 9.0 compatible`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 97`** (2 nodes): `.import_jlcsearch_parts()`, `Import parts into database from JLCSearch API response          Args:`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 98`** (2 nodes): `.get_database_stats()`, `Get statistics about the database`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 99`** (2 nodes): `jlcpcb_parts.py`, `JLCPCB Parts Database Manager  Manages local SQLite database of JLCPCB parts f`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 100`** (2 nodes): `.map_package_to_footprint()`, `Map JLCPCB package name to KiCAD footprint(s)          Args:             pack`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 101`** (2 nodes): `.close()`, `Close database connection`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 102`** (2 nodes): `.list_libraries()`, `Get list of available library nicknames`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 103`** (2 nodes): `.list_libraries()`, `List all available footprint libraries`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 104`** (2 nodes): `.get_library_path()`, `Get filesystem path for a library nickname`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 105`** (2 nodes): `.get_footprint_info()`, `Get information about a specific footprint          Args:             library`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 106`** (2 nodes): `.search_footprints()`, `Search for footprints by pattern`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 107`** (2 nodes): `.__init__()`, `Initialize with optional board instance`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 108`** (2 nodes): `.import_ses()`, `Import a Specctra SES file into the board.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 109`** (2 nodes): `.export_dsn()`, `Export the board to Specctra DSN format only.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 110`** (2 nodes): `config.ts`, `loadConfig()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 111`** (2 nodes): `design.ts`, `registerDesignPrompts()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 112`** (2 nodes): `datasheet.ts`, `registerDatasheetTools()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 113`** (2 nodes): `jlcpcb-api.ts`, `registerJLCPCBApiTools()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 114`** (2 nodes): `ui.ts`, `registerUITools()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 115`** (2 nodes): `Dynamic Library Loading Plan (archived)`, `Dynamic Symbol Loading Status (complete, prod-ready)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 116`** (1 nodes): `eslint.config.js`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 117`** (1 nodes): `test-router.js`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 118`** (1 nodes): `Check if running on Windows`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 119`** (1 nodes): `Check if running on Linux`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 120`** (1 nodes): `Check if running on macOS`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 121`** (1 nodes): `Get human-readable platform name`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 122`** (1 nodes): `Get potential KiCAD Python dist-packages paths for current platform          R`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 123`** (1 nodes): `Get the first valid KiCAD Python path          Returns:             Path to K`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 124`** (1 nodes): `Get platform-appropriate KiCAD symbol library search paths          Returns:`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 125`** (1 nodes): `r"""         Get appropriate configuration directory for current platform`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 126`** (1 nodes): `Get appropriate log directory for current platform          Returns:`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 127`** (1 nodes): `r"""         Get appropriate cache directory for current platform          Fo`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 128`** (1 nodes): `Create all necessary directories if they don't exist`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 129`** (1 nodes): `Get path to current Python executable`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 130`** (1 nodes): `Add KiCAD Python paths to sys.path          Returns:             True if at l`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 131`** (1 nodes): `List running processes on Windows using Toolhelp API.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 132`** (1 nodes): `Check if KiCAD is currently running          Returns:             True if KiC`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 133`** (1 nodes): `Get path to KiCAD executable          Returns:             Path to pcbnew/kic`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 134`** (1 nodes): `Launch KiCAD PCB Editor          Args:             project_path: Optional pat`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 135`** (1 nodes): `Get information about running KiCAD processes          Returns:             L`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 136`** (1 nodes): `Create a new empty schematic from template`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 137`** (1 nodes): `Load an existing schematic`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 138`** (1 nodes): `Save a schematic to file`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 139`** (1 nodes): `Extract metadata from schematic`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 140`** (1 nodes): `Add a wire to the schematic using S-expression manipulation          Args:`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 141`** (1 nodes): `Add a multi-segment wire (polyline) to the schematic          Args:`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 142`** (1 nodes): `Add a net label to the schematic          Args:             schematic_path: P`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 143`** (1 nodes): `Parse a wire S-expression item in a single pass.         Returns ((x1,y1), (x2,`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 144`** (1 nodes): `Return True if (px, py) lies strictly between (x1,y1) and (x2,y2)         on a`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 145`** (1 nodes): `Split any wire segment that passes through *position* as a strict         midpo`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 146`** (1 nodes): `Add a junction (connection dot) to the schematic.          Mirrors KiCAD's Add`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 147`** (1 nodes): `Add a no-connect flag to the schematic          Args:             schematic_p`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 148`** (1 nodes): `Delete a wire from the schematic matching given start/end coordinates.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 149`** (1 nodes): `Delete a net label from the schematic by name (and optionally position).`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 150`** (1 nodes): `Create an orthogonal (right-angle) path between two points          Args:`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 151`** (1 nodes): `Convert a KiCad bounding box object to a normalized mm rectangle.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 152`** (1 nodes): `Return the union of rects, or None for an empty list.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 153`** (1 nodes): `Generate a 32-character random nonce`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 154`** (1 nodes): `Search for components matching criteria (basic implementation)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 155`** (1 nodes): `List all available symbol libraries`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 156`** (1 nodes): `List all symbols in a library`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 157`** (1 nodes): `Get detailed information about a symbol`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 158`** (1 nodes): `Search for symbols matching criteria`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 159`** (1 nodes): `Get a recommended default symbol for a given component type`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 160`** (1 nodes): `Normalize LCSC number to standard format 'C123456'.          Accepts: 'C123456',`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 161`** (1 nodes): `Find the line range of the (lib_symbols ...) section.         Returns (start, en`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 162`** (1 nodes): `Extract LCSC and Datasheet info from a placed symbol block.          Returns dic`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 163`** (1 nodes): `Connect to KiCAD          Returns:             True if connection successful,`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 164`** (1 nodes): `Disconnect from KiCAD and clean up resources`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 165`** (1 nodes): `Check if currently connected to KiCAD          Returns:             True if c`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 166`** (1 nodes): `Get KiCAD version          Returns:             Version string (e.g., "9.0.0"`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 167`** (1 nodes): `Create a new KiCAD project          Args:             path: Directory path fo`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 168`** (1 nodes): `Open an existing KiCAD project          Args:             path: Path to .kica`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 169`** (1 nodes): `Save the current project          Args:             path: Optional new path t`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 170`** (1 nodes): `Close the current project`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 171`** (1 nodes): `Get board API for current project          Returns:             BoardAPI inst`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 172`** (1 nodes): `Set board size          Args:             width: Board width             hei`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 173`** (1 nodes): `Get current board size          Returns:             Dictionary with width, h`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 174`** (1 nodes): `Add a layer to the board          Args:             layer_name: Name of the l`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 175`** (1 nodes): `List all components on the board          Returns:             List of compon`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 176`** (1 nodes): `Place a component on the board          Args:             reference: Componen`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 177`** (1 nodes): `Pillow Image Processing Library`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 178`** (1 nodes): `Pydantic Data Validation`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 179`** (1 nodes): `python-dotenv Env Management`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 180`** (1 nodes): `Colorlog Logging Library`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 181`** (1 nodes): `Pytest Testing Framework`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 182`** (1 nodes): `Black Code Formatter`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 183`** (1 nodes): `MyPy Type Checker`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 184`** (1 nodes): `Changelog v2.2.1-alpha`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 185`** (1 nodes): `Changelog v2.2.0-alpha`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 186`** (1 nodes): `Changelog v1.0.0`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 187`** (1 nodes): `KiCAD UI Auto-Launch Feature`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 188`** (1 nodes): `Visual Feedback Guide`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 189`** (1 nodes): `UI Auto-Launch Guide`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 190`** (1 nodes): `v1.0.0 Core Foundation Milestone`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 191`** (1 nodes): `Planned Design Patterns and Templates`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module Group 192`** (1 nodes): `Schematic Wiring Implementation Plan (archived)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `KiCADInterface` connect `KiCAD Interface Dispatcher` to `Schematic Connection Engine`, `Board & Component Commands`, `Wire Junction Tests`, `Wire Preservation Tests`, `Wire Junction Rationale`, `Wire Connectivity Tests`?**
  _High betweenness centrality (0.248) - this node is a cross-community bridge._
- **Why does `PinLocator` connect `Schematic Connection Engine` to `KiCAD Interface Dispatcher`, `Board & Component Commands`, `Module Group 30`?**
  _High betweenness centrality (0.148) - this node is a cross-community bridge._
- **Why does `IPCBackend` connect `Board & Component Commands` to `IPC Backend Tests`, `KiCAD Interface Dispatcher`, `Backend API Abstraction`?**
  _High betweenness centrality (0.096) - this node is a cross-community bridge._
- **Are the 164 inferred relationships involving `KiCADInterface` (e.g. with `KiCADProcessManager` and `PlatformHelper`) actually correct?**
  _`KiCADInterface` has 164 INFERRED edges - model-reasoned connections that need verification._
- **Are the 204 inferred relationships involving `PinLocator` (e.g. with `KiCADInterface` and `Main interface class to handle KiCAD operations`) actually correct?**
  _`PinLocator` has 204 INFERRED edges - model-reasoned connections that need verification._
- **Are the 176 inferred relationships involving `WireManager` (e.g. with `KiCADInterface` and `Main interface class to handle KiCAD operations`) actually correct?**
  _`WireManager` has 176 INFERRED edges - model-reasoned connections that need verification._
- **Are the 149 inferred relationships involving `ConnectionManager` (e.g. with `KiCADInterface` and `Main interface class to handle KiCAD operations`) actually correct?**
  _`ConnectionManager` has 149 INFERRED edges - model-reasoned connections that need verification._