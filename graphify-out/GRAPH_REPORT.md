# Graph Report - /home/aytzey/Desktop/Windows150GB/KiCAD-MCP-Server  (2026-04-10)

## Corpus Check
- 160 files · ~210,539 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 2417 nodes · 3925 edges · 159 communities detected
- Extraction: 76% EXTRACTED · 24% INFERRED · 0% AMBIGUOUS · INFERRED: 937 edges (avg confidence: 0.51)
- Token cost: 0 input · 0 output

## God Nodes (most connected - your core abstractions)
1. `KiCADInterface` - 135 edges
2. `PinLocator` - 123 edges
3. `WireManager` - 88 edges
4. `BoardAPI` - 70 edges
5. `KiCADBackend` - 67 edges
6. `APINotAvailableError` - 66 edges
7. `ConnectionManager` - 61 edges
8. `ConnectionError` - 60 edges
9. `SchematicHandlers` - 56 edges
10. `IPCHandlers` - 50 edges

## Surprising Connections (you probably didn't know these)
- `KiCAD IPC API Backend` --semantically_similar_to--> `Visual Feedback / UI Reload Workflow`  [INFERRED] [semantically similar]
  CHANGELOG.md → docs/VISUAL_FEEDBACK.md
- `Tests for KiCAD MCP Server` --uses--> `ComponentCommands`  [INFERRED]
  tests/__init__.py → python/commands/component.py
- `Tests for KiCAD MCP Server` --uses--> `ExportCommands`  [INFERRED]
  tests/__init__.py → python/commands/export.py
- `Tests for KiCAD MCP Server` --uses--> `ProjectCommands`  [INFERRED]
  tests/__init__.py → python/commands/project.py
- `Tests for KiCAD MCP Server` --uses--> `KiCADBackend`  [INFERRED]
  tests/__init__.py → python/kicad_api/base.py

## Hyperedges (group relationships)
- **Schematic Wiring Subsystem (WireManager + PinLocator + DynamicSymbolLoader)** — concept_wire_manager, concept_pin_locator, concept_dynamic_symbol_loader [EXTRACTED 0.95]
- **Dual Backend System (SWIG + IPC with Factory Auto-Detection)** — concept_swig_backend, concept_ipc_backend, concept_backend_factory [EXTRACTED 0.95]
- **FFC/Ribbon Passthrough PCB Workflow** — tool_connect_passthrough, tool_sync_schematic_to_board, tool_route_pad_to_pad, tool_snapshot_project [EXTRACTED 0.95]
- **End-to-End PCB Design Workflow** — pcb_workflow_stage1_project_setup, pcb_workflow_stage2_schematic, pcb_workflow_stage3_layout, pcb_workflow_stage4_verification, pcb_workflow_stage5_manufacturing [EXTRACTED 1.00]
- **Router Pattern: Registry + Router Tools + Direct Tools** — mcp_router_guide_tool_registry, mcp_router_guide_router_tools, mcp_router_guide_direct_tools [EXTRACTED 1.00]
- **kicad-skip Limitation Workaround: Template + Injection + Clone** — archive_dynamic_library_kicad_skip_limitation, archive_schematic_template_approach, archive_dynamic_library_symbol_inject [EXTRACTED 0.95]

## Communities

### Community 0 - "Community 0"
Cohesion: 0.01
Nodes (156): ConnectionManager, Return True if the candidate label point is too close to an existing label., Reject paths that would create wire-wire crossings or overlaps., Return True if any segment passes through another symbol body., Connect a component pin to a named net using a wire stub and label          Ar, Manage connections between components in schematics, Connect all pins of source_ref to matching pins of target_ref via shared net lab, Get or create pin locator instance (+148 more)

### Community 1 - "Community 1"
Cohesion: 0.01
Nodes (144): AutorouteCFHACommands, Constraint-first hybrid autorouting commands., FootprintHandlers, Create a new .kicad_mod footprint file in a .pretty library., Edit an existing pad in a .kicad_mod file., List .pretty footprint libraries and their contents., Register a .pretty library in KiCAD's fp-lib-table., IPCHandlers (+136 more)

### Community 2 - "Community 2"
Cohesion: 0.03
Nodes (118): ABC, APINotAvailableError, BackendError, BoardAPI, ConnectionError, KiCADBackend, Abstract base class for KiCAD API backends  Defines the interface that all KiC, Abstract interface for board operations (+110 more)

### Community 3 - "Community 3"
Cohesion: 0.02
Nodes (10): KiCADInterface, main(), _write_response(), Signal Profile Separation, auto_place_clusters Response, auto_place_rules Response, auto_place_strategy Response, Schematic Creation and Export (5 tools) (+2 more)

### Community 4 - "Community 4"
Cohesion: 0.03
Nodes (62): Board-related command implementations for KiCAD interface  This file is mainta, DesignRuleCommands, Design rules command implementations for KiCAD interface, Get current design rules - KiCAD 9.0 compatible, Handles design rule checking and configuration, Run Design Rule Check using kicad-cli, Initialize with optional board instance, Set design rules for the PCB (+54 more)

### Community 5 - "Community 5"
Cohesion: 0.04
Nodes (51): _make_junction(), _make_lib_symbol_r(), _make_sch_data(), _make_symbol(), _make_wire(), Tests for move_schematic_component with wire preservation (WireDragger).  Unit, Build a minimal sch_data list with lib_symbols and sheet_instances., Device:R at (0, 0) rot=0 — pin 1 is above and pin 2 is below in schematic space. (+43 more)

### Community 6 - "Community 6"
Cohesion: 0.03
Nodes (70): add_component(), ComponentManager, get_dynamic_loader(), get_or_create_template(), Snap schematic placements to the conventional KiCad connection grid., Add a component to the schematic by cloning from template          Args:, Manage components in a schematic, Remove a component from the schematic by reference designator (+62 more)

### Community 7 - "Community 7"
Cohesion: 0.03
Nodes (39): Component-related command implementations for KiCAD interface, Align components horizontally and optionally distribute them, Align components vertically and optionally distribute them, Align components to the specified edge of the board, Move an existing component to a new position, Initialize with optional board instance and library manager, Rotate an existing component, Delete a component from the PCB (+31 more)

### Community 8 - "Community 8"
Cohesion: 0.04
Nodes (39): _build_freerouting_cmd(), _docker_available(), _find_docker(), _find_java(), FreeroutingCommands, _java_version_ok(), Handles Freerouting autoroute operations., Determine how to run Freerouting: direct or docker.          Returns dict with ' (+31 more)

### Community 9 - "Community 9"
Cohesion: 0.06
Nodes (43): add_kicad_to_python_path(), detect_platform(), ensure_directories(), get_cache_dir(), get_config_dir(), get_kicad_library_search_paths(), get_kicad_python_path(), get_kicad_python_paths() (+35 more)

### Community 10 - "Community 10"
Cohesion: 0.06
Nodes (32): BackendAvailability, _best_intent(), compile_kicad_dru(), compute_weighted_qor_score(), _condition_for_nets(), _diff_partner_name(), _distance_mm(), HybridRouteApplier (+24 more)

### Community 11 - "Community 11"
Cohesion: 0.05
Nodes (28): Library management for KiCAD symbols  Handles parsing sym-lib-table files, disco, Parse sym-lib-table file          Format is S-expression (Lisp-like):         (s, Resolve environment variables and paths in library URI          Handles:, Find KiCAD symbol directory, Information about a symbol in a library, Find KiCAD 3rd party library directory (PCM installed libs), Parse a .kicad_sym file to extract symbol metadata          Args:             li, Extract properties from a symbol block (+20 more)

### Community 12 - "Community 12"
Cohesion: 0.06
Nodes (13): _make_point(), _make_schematic(), _make_wire(), Tests for the wire_connectivity module and the get_wire_connections handler., Handler returns error responses for bad or missing parameters., Return a bound _handle_get_wire_connections without full init., Unit tests for the pure-logic functions in wire_connectivity., Verify the get_wire_connections tool schema is present and well-formed. (+5 more)

### Community 13 - "Community 13"
Cohesion: 0.05
Nodes (14): _make_handler_under_test(), Tests for schematic inspection and editing tools added in the schematic_tools br, Return the unbound handler method from kicad_interface by importing only     th, Verify that each new handler returns success=False with an informative     mess, Return a stub that exposes only the handler methods under test., Write *content* to a temp file and return its Path., Unit-level tests for WireManager.delete_wire., Ensure the tolerance kwarg doesn't raise a TypeError. (+6 more)

### Community 14 - "Community 14"
Cohesion: 0.07
Nodes (17): _make_test_schematic(), Tests for get_schematic_component and edit_schematic_component fieldPositions su, Mirrors the regex used in _handle_edit_schematic_component for fieldPositions., Replacing position must not change the field value string., Integration tests: write a real .kicad_sch and call the handler., Lazily import KiCADInterface to avoid pcbnew import at collection time., Integration tests for the new fieldPositions parameter., fieldPositions without value/footprint/newReference should succeed. (+9 more)

### Community 15 - "Community 15"
Cohesion: 0.09
Nodes (37): _aabb_overlap(), _check_wire_overlap(), _compute_pin_positions_direct(), compute_symbol_bbox(), _compute_symbol_bbox_direct(), _distance(), _extract_lib_symbols(), find_overlapping_elements() (+29 more)

### Community 16 - "Community 16"
Cohesion: 0.11
Nodes (31): _build_hanan_grid(), compress_path(), estimate_congestion(), inflate_rect(), manhattan_distance(), manhattan_path_length(), normalize_rect(), pick_escape_point() (+23 more)

### Community 17 - "Community 17"
Cohesion: 0.08
Nodes (30): KiCAD Backend Abstraction Layer (base/ipc/swig/factory), IPC->SWIG Auto-Detect Fallback Decision, IPC API Migration Plan (archived), JLCPCB Package to KiCAD Footprint Mapping, Conditional Tool Registration (Phase 2 plan), Router Implementation Status (archived, Phase 1 complete), Decision: Migrate to IPC API Immediately, SWIG Deprecation Discovery (KiCAD 10 removal) (+22 more)

### Community 18 - "Community 18"
Cohesion: 0.11
Nodes (13): _make_test_schematic(), Regression tests for delete_schematic_component.  Key regression: the handler, Verify that the new content-string pattern finds blocks in both formats., Regression: old line-by-line regex must NOT match the multi-line format., Old regex did work on single-line (inline) format., New content-string pattern must find blocks in multi-line format., New content-string pattern also works on inline format., New pattern must find #PWR030 power symbol in multi-line format. (+5 more)

### Community 19 - "Community 19"
Cohesion: 0.09
Nodes (14): JLCPCBPartsManager, JLCPCB Parts Database Manager  Manages local SQLite database of JLCPCB parts f, Determine if part is Basic, Extended, or Preferred, Import parts into database from JLCSearch API response          Args:, Manages local database of JLCPCB parts      Provides fast parametric search, f, Search for parts with filters          Args:             query: Free-text sea, Initialize parts database manager          Args:             db_path: Path to, Get detailed information for specific LCSC part          Args:             lc (+6 more)

### Community 20 - "Community 20"
Cohesion: 0.1
Nodes (12): ExportCommands, Export command implementations for KiCAD interface, Handles export-related KiCAD operations, Initialize with optional board instance, Export 3D model files using kicad-cli (KiCAD 9.0 compatible), Export Bill of Materials, Export BOM to CSV format, Export BOM to XML format (+4 more)

### Community 21 - "Community 21"
Cohesion: 0.13
Nodes (24): Changelog v2.0.0-alpha, Backend Factory Auto-Detection, KiCAD IPC API Backend, IPC UNIX Socket Connection, kicad_interface.py Main Entry Point, kicad-python (kipy) Library, Model Context Protocol (MCP), Python KiCAD Interface Layer (+16 more)

### Community 22 - "Community 22"
Cohesion: 0.15
Nodes (14): _esc(), _fmt(), _pin_lines(), _polyline_lines(), _property_block(), Symbol Creator for KiCAD MCP Server  Creates and edits .kicad_sym symbol library, Remove a symbol from a .kicad_sym library., List all symbols in a .kicad_sym file. (+6 more)

### Community 23 - "Community 23"
Cohesion: 0.14
Nodes (14): _esc(), _fmt(), FootprintCreator, _new_uuid(), _pad_lines(), Footprint Creator for KiCAD MCP Server  Creates and edits .kicad_mod footprint f, Edit an existing pad in a .kicad_mod file.          Parameters         ---------, Format a float without unnecessary trailing zeros. (+6 more)

### Community 24 - "Community 24"
Cohesion: 0.13
Nodes (13): _generate_nonce(), JLCPCBClient, JLCPCB API client for fetching parts data  Handles authentication and download, Generate the Authorization header for JLCPCB API requests          Args:, Fetch one page of parts from JLCPCB API          Args:             last_key:, Download entire parts library from JLCPCB          Args:             callback, Get detailed information for a specific LCSC part number          Note: This u, Test JLCPCB API connection      Args:         app_id: Optional App ID (uses e (+5 more)

### Community 25 - "Community 25"
Cohesion: 0.11
Nodes (17): _get_board_info(), _get_board_preview(), _get_components(), _get_design_rules(), _get_layers(), _get_nets(), _get_project_info(), handle_resource_read() (+9 more)

### Community 26 - "Community 26"
Cohesion: 0.19
Nodes (17): _apply_transform(), _bounding_box(), _build_gr_poly(), _extract_polygons_from_element(), _get_attr(), _identity(), import_svg_to_pcb(), _mat_mul() (+9 more)

### Community 27 - "Community 27"
Cohesion: 0.15
Nodes (11): JLCSearchClient, JLCSearch API client (public, no authentication required)  Alternative to offi, Search for capacitors          Args:             capacitance: Capacitance val, Get part details by LCSC number          Args:             lcsc_number: LCSC, Download all components from jlcsearch database          Note: tscircuit API h, Client for JLCSearch public API (tscircuit)      Provides access to JLCPCB par, Test JLCSearch API connection      Returns:         True if connection succes, Initialize JLCSearch API client (+3 more)

### Community 28 - "Community 28"
Cohesion: 0.19
Nodes (15): _build_adjacency(), _find_connected_wires(), _find_pins_on_net(), get_wire_connections(), _parse_virtual_connections(), _parse_wires(), Wire Connectivity Analysis for KiCad Schematics  Traces wire networks from a p, BFS from query point. Returns (visited wire indices, net IU points) or (None, No (+7 more)

### Community 29 - "Community 29"
Cohesion: 0.14
Nodes (16): Changelog v2.2.2-alpha, Changelog v2.2.3, KICAD_MCP_DEV Developer Mode, SVG to PCB Polygon Conversion, Routing Tools Reference Documentation, SVG Import Guide, CairoSVG Rendering Library, MCP Tool: connect_passthrough (+8 more)

### Community 30 - "Community 30"
Cohesion: 0.26
Nodes (13): compute_pin_positions(), _coords_match(), drag_wires(), find_symbol(), get_all_stationary_pin_positions(), get_pin_defs(), _make_wire_sexp(), pin_world_xy() (+5 more)

### Community 31 - "Community 31"
Cohesion: 0.23
Nodes (8): add_junction(), add_polyline_wire(), add_wire(), _break_wires_at_point(), _make_wire_sexp(), _parse_wire(), _point_strictly_on_wire(), Wire Manager for KiCad Schematics  Handles wire creation using S-expression ma

### Community 32 - "Community 32"
Cohesion: 0.22
Nodes (4): buildPythonEnv(), defaultPythonPath(), findPythonExecutable(), KiCADMcpServer

### Community 33 - "Community 33"
Cohesion: 0.27
Nodes (10): connect_passthrough(), connect_to_net(), _direction_from_angle(), generate_netlist(), get_net_connections(), get_pin_locator(), _path_crosses_wires(), _path_hits_symbol_bboxes() (+2 more)

### Community 34 - "Community 34"
Cohesion: 0.22
Nodes (9): DatasheetManager, _find_lib_symbols_range(), _normalize_lcsc(), _process_symbol_block(), Datasheet Manager for KiCAD MCP Server  Enriches KiCAD schematic symbols with da, Scan a .kicad_sch file and fill in missing LCSC datasheet URLs.          For eac, Return the LCSC datasheet URL for a given LCSC number.         No network reques, Enriches KiCAD schematics with LCSC datasheet URLs.      Reads .kicad_sch files, (+1 more)

### Community 35 - "Community 35"
Cohesion: 0.23
Nodes (11): _extract_blocks(), _extract_courtyard(), _extract_pads(), parse_kicad_mod(), Parser for KiCad .kicad_mod footprint files.  Extracts the fields that the MCP, Parse all (pad …) blocks and return a list of pad objects.      Each object ha, Reverse KiCad S-expression string escaping., Return all S-expression blocks that start with `(token ` by tracking     parent (+3 more)

### Community 36 - "Community 36"
Cohesion: 0.18
Nodes (12): Changelog v2.1.0-alpha, DynamicSymbolLoader, Custom Footprint Creator Tools, PinLocator Pin Discovery, Intelligent Schematic Wiring System, S-expression File Injection, Wire Graph Connectivity Analysis, WireManager S-expression Engine (+4 more)

### Community 37 - "Community 37"
Cohesion: 0.33
Nodes (10): check_and_launch_kicad(), get_executable_path(), get_process_info(), is_running(), KiCADProcessManager, launch(), KiCAD Process Management Utilities  Detects if KiCAD is running and provides a, Manages KiCAD process detection and launching (+2 more)

### Community 38 - "Community 38"
Cohesion: 0.18
Nodes (2): TestOrthogonalRouterHelpers, TestOrthogonalRouterPlanning

### Community 39 - "Community 39"
Cohesion: 0.22
Nodes (2): getRegistryStats(), getRoutedToolNames()

### Community 40 - "Community 40"
Cohesion: 0.25
Nodes (5): Regression test: no MCP tool name is registered more than once across all TypeSc, Return list of (tool_name, file, line_no) for every server.tool() call., Every tool name must appear exactly once across all TS tool files., Sanity check: src/tools/ directory must be present and contain TS files., TestTsToolRegistry

### Community 41 - "Community 41"
Cohesion: 0.33
Nodes (1): Logger

### Community 42 - "Community 42"
Cohesion: 0.25
Nodes (9): kicad-skip Cannot Create Symbols from Scratch (constraint), Symbol Injection into lib_symbols via S-Expression, Offscreen Template Instance Creation Strategy, Symbol Library Parsing Cache (library_cache, symbol_cache), kicad-skip clone() API Usage, Template-Based Schematic Component Approach, kicad-skip Wire API Uncertainty (challenge), S-Expression Manipulation Fallback for Wiring (+1 more)

### Community 43 - "Community 43"
Cohesion: 0.22
Nodes (0): 

### Community 44 - "Community 44"
Cohesion: 0.36
Nodes (7): convert_to_mcp_format(), download_files(), extract_database(), main(), Download all split archive parts., Extract the split 7z archive to get cache.sqlite3., Convert jlcparts cache.sqlite3 to the MCP server's expected format.

### Community 45 - "Community 45"
Cohesion: 0.29
Nodes (4): LibraryManager, list_available_libraries(), Manage symbol libraries, search_symbols()

### Community 46 - "Community 46"
Cohesion: 0.29
Nodes (8): Basic Parts Preference for Cost Optimization, JLCPCB Parts Integration Plan (archived), JLCPCB SQLite Local Cache Architecture, enrich_datasheets Tool (LCSC URL fill), get_datasheet_url Tool, LCSC Datasheet URL Construction (no API key), Planned Supplier Integration (Digikey/Mouser), v2.1.0-alpha Schematics and JLCPCB Milestone

### Community 47 - "Community 47"
Cohesion: 0.29
Nodes (7): route_pad_to_pad Tool (preferred routing), PCB Workflow Stage 1: Project Setup, PCB Workflow Stage 2: Schematic Design, PCB Workflow Stage 3: PCB Layout, PCB Workflow Stage 4: Verification, PCB Workflow Stage 5: Manufacturing Output, v2.2.x Routing Creators Autorouting Milestone

### Community 48 - "Community 48"
Cohesion: 0.43
Nodes (5): _bbox(), _symbol(), test_auto_place_missing_footprints_uses_deterministic_grid_and_skips_missing_props(), test_build_auto_place_plan_profiles_connectors_to_top_bottom_and_sides(), test_build_auto_place_plan_routing_aware_clusters_components_by_connectivity()

### Community 49 - "Community 49"
Cohesion: 0.6
Nodes (5): Write-Error-Custom(), Write-Info(), Write-Step(), Write-Success(), Write-Warning-Custom()

### Community 50 - "Community 50"
Cohesion: 0.73
Nodes (5): _call_interface(), _interface_python(), main(), _python_env(), _repo_root()

### Community 51 - "Community 51"
Cohesion: 0.33
Nodes (1): KiCADServer

### Community 52 - "Community 52"
Cohesion: 0.4
Nodes (3): _FakeSchematic, Test configuration for python/tests.  Sets up sys.modules stubs for heavy KiCAD, Minimal stand-in for skip.Schematic used in PinLocator cache.

### Community 53 - "Community 53"
Cohesion: 0.8
Nodes (4): _make_temp_schematic(), test_connect_to_net_attaches_wire_to_actual_pin_location(), test_connect_to_net_respects_rotated_pin_coordinates(), _wire_touches_pin()

### Community 54 - "Community 54"
Cohesion: 0.6
Nodes (3): main(), parseCommandLineArgs(), setupGracefulShutdown()

### Community 55 - "Community 55"
Cohesion: 0.5
Nodes (5): JLCPCB Parts Integration, JLCPCB Local SQLite Database, JLCSearch Public API Client, LCSC Datasheet Enrichment, Requests HTTP Library

### Community 56 - "Community 56"
Cohesion: 0.4
Nodes (5): KiCAD Bundled Python (Windows), Cross-Platform Support (Linux/Windows/macOS), Linux Compatibility Audit, Platform Guide Documentation, Windows Troubleshooting Guide

### Community 57 - "Community 57"
Cohesion: 0.4
Nodes (5): STDIO Transport Architecture Decision, Claude Code CLI Configuration, Claude Desktop Configuration, Cline VSCode Extension Configuration, MCP Server Environment Variables

### Community 58 - "Community 58"
Cohesion: 0.4
Nodes (5): Schematic Component Operations (8 tools), connect_passthrough Tool (FFC/ribbon workflow), DynamicSymbolLoader Class, Schematic Net Analysis (4 tools), Schematic Wiring and Connections (8 tools)

### Community 59 - "Community 59"
Cohesion: 0.5
Nodes (0): 

### Community 60 - "Community 60"
Cohesion: 0.67
Nodes (0): 

### Community 61 - "Community 61"
Cohesion: 0.67
Nodes (0): 

### Community 62 - "Community 62"
Cohesion: 1.0
Nodes (3): Freerouting Autorouter Integration, Specctra DSN/SES Format, MCP Tool: autoroute (Freerouting)

### Community 63 - "Community 63"
Cohesion: 0.67
Nodes (3): Build and Test Session (Oct 2025, archived), PlatformHelper Utility (XDG spec, cross-platform paths), KiCAD Python Path Discovery

### Community 64 - "Community 64"
Cohesion: 1.0
Nodes (0): 

### Community 65 - "Community 65"
Cohesion: 1.0
Nodes (0): 

### Community 66 - "Community 66"
Cohesion: 1.0
Nodes (0): 

### Community 67 - "Community 67"
Cohesion: 1.0
Nodes (0): 

### Community 68 - "Community 68"
Cohesion: 1.0
Nodes (0): 

### Community 69 - "Community 69"
Cohesion: 1.0
Nodes (2): Dynamic Library Loading Plan (archived), Dynamic Symbol Loading Status (complete, prod-ready)

### Community 70 - "Community 70"
Cohesion: 1.0
Nodes (1): Comprehensive tool schema definitions for all KiCAD MCP commands  Following MC

### Community 71 - "Community 71"
Cohesion: 1.0
Nodes (0): 

### Community 72 - "Community 72"
Cohesion: 1.0
Nodes (0): 

### Community 73 - "Community 73"
Cohesion: 1.0
Nodes (0): 

### Community 74 - "Community 74"
Cohesion: 1.0
Nodes (0): 

### Community 75 - "Community 75"
Cohesion: 1.0
Nodes (1): Check if running on Windows

### Community 76 - "Community 76"
Cohesion: 1.0
Nodes (1): Check if running on Linux

### Community 77 - "Community 77"
Cohesion: 1.0
Nodes (1): Check if running on macOS

### Community 78 - "Community 78"
Cohesion: 1.0
Nodes (1): Get human-readable platform name

### Community 79 - "Community 79"
Cohesion: 1.0
Nodes (1): Get potential KiCAD Python dist-packages paths for current platform          R

### Community 80 - "Community 80"
Cohesion: 1.0
Nodes (1): Get the first valid KiCAD Python path          Returns:             Path to K

### Community 81 - "Community 81"
Cohesion: 1.0
Nodes (1): Get platform-appropriate KiCAD symbol library search paths          Returns:

### Community 82 - "Community 82"
Cohesion: 1.0
Nodes (1): r"""         Get appropriate configuration directory for current platform

### Community 83 - "Community 83"
Cohesion: 1.0
Nodes (1): Get appropriate log directory for current platform          Returns:

### Community 84 - "Community 84"
Cohesion: 1.0
Nodes (1): r"""         Get appropriate cache directory for current platform          Fo

### Community 85 - "Community 85"
Cohesion: 1.0
Nodes (1): Create all necessary directories if they don't exist

### Community 86 - "Community 86"
Cohesion: 1.0
Nodes (1): Get path to current Python executable

### Community 87 - "Community 87"
Cohesion: 1.0
Nodes (1): Add KiCAD Python paths to sys.path          Returns:             True if at l

### Community 88 - "Community 88"
Cohesion: 1.0
Nodes (1): List running processes on Windows using Toolhelp API.

### Community 89 - "Community 89"
Cohesion: 1.0
Nodes (1): Check if KiCAD is currently running          Returns:             True if KiC

### Community 90 - "Community 90"
Cohesion: 1.0
Nodes (1): Get path to KiCAD executable          Returns:             Path to pcbnew/kic

### Community 91 - "Community 91"
Cohesion: 1.0
Nodes (1): Launch KiCAD PCB Editor          Args:             project_path: Optional pat

### Community 92 - "Community 92"
Cohesion: 1.0
Nodes (1): Get information about running KiCAD processes          Returns:             L

### Community 93 - "Community 93"
Cohesion: 1.0
Nodes (0): 

### Community 94 - "Community 94"
Cohesion: 1.0
Nodes (0): 

### Community 95 - "Community 95"
Cohesion: 1.0
Nodes (0): 

### Community 96 - "Community 96"
Cohesion: 1.0
Nodes (0): 

### Community 97 - "Community 97"
Cohesion: 1.0
Nodes (1): Create a new empty schematic from template

### Community 98 - "Community 98"
Cohesion: 1.0
Nodes (1): Load an existing schematic

### Community 99 - "Community 99"
Cohesion: 1.0
Nodes (1): Save a schematic to file

### Community 100 - "Community 100"
Cohesion: 1.0
Nodes (1): Extract metadata from schematic

### Community 101 - "Community 101"
Cohesion: 1.0
Nodes (1): Add a wire to the schematic using S-expression manipulation          Args:

### Community 102 - "Community 102"
Cohesion: 1.0
Nodes (1): Add a multi-segment wire (polyline) to the schematic          Args:

### Community 103 - "Community 103"
Cohesion: 1.0
Nodes (1): Add a net label to the schematic          Args:             schematic_path: P

### Community 104 - "Community 104"
Cohesion: 1.0
Nodes (1): Parse a wire S-expression item in a single pass.         Returns ((x1,y1), (x2,

### Community 105 - "Community 105"
Cohesion: 1.0
Nodes (1): Return True if (px, py) lies strictly between (x1,y1) and (x2,y2)         on a

### Community 106 - "Community 106"
Cohesion: 1.0
Nodes (1): Split any wire segment that passes through *position* as a strict         midpo

### Community 107 - "Community 107"
Cohesion: 1.0
Nodes (1): Add a junction (connection dot) to the schematic.          Mirrors KiCAD's Add

### Community 108 - "Community 108"
Cohesion: 1.0
Nodes (1): Add a no-connect flag to the schematic          Args:             schematic_p

### Community 109 - "Community 109"
Cohesion: 1.0
Nodes (1): Delete a wire from the schematic matching given start/end coordinates.

### Community 110 - "Community 110"
Cohesion: 1.0
Nodes (1): Delete a net label from the schematic by name (and optionally position).

### Community 111 - "Community 111"
Cohesion: 1.0
Nodes (1): Create an orthogonal (right-angle) path between two points          Args:

### Community 112 - "Community 112"
Cohesion: 1.0
Nodes (1): Generate a 32-character random nonce

### Community 113 - "Community 113"
Cohesion: 1.0
Nodes (1): Search for components matching criteria (basic implementation)

### Community 114 - "Community 114"
Cohesion: 1.0
Nodes (1): List all available symbol libraries

### Community 115 - "Community 115"
Cohesion: 1.0
Nodes (1): List all symbols in a library

### Community 116 - "Community 116"
Cohesion: 1.0
Nodes (1): Get detailed information about a symbol

### Community 117 - "Community 117"
Cohesion: 1.0
Nodes (1): Search for symbols matching criteria

### Community 118 - "Community 118"
Cohesion: 1.0
Nodes (1): Get a recommended default symbol for a given component type

### Community 119 - "Community 119"
Cohesion: 1.0
Nodes (1): Normalize LCSC number to standard format 'C123456'.          Accepts: 'C123456',

### Community 120 - "Community 120"
Cohesion: 1.0
Nodes (1): Find the line range of the (lib_symbols ...) section.         Returns (start, en

### Community 121 - "Community 121"
Cohesion: 1.0
Nodes (1): Extract LCSC and Datasheet info from a placed symbol block.          Returns dic

### Community 122 - "Community 122"
Cohesion: 1.0
Nodes (1): Freerouting autoroute integration for KiCAD MCP Server.  Exports the board to Sp

### Community 123 - "Community 123"
Cohesion: 1.0
Nodes (1): Connect to KiCAD          Returns:             True if connection successful,

### Community 124 - "Community 124"
Cohesion: 1.0
Nodes (1): Disconnect from KiCAD and clean up resources

### Community 125 - "Community 125"
Cohesion: 1.0
Nodes (1): Check if currently connected to KiCAD          Returns:             True if c

### Community 126 - "Community 126"
Cohesion: 1.0
Nodes (1): Get KiCAD version          Returns:             Version string (e.g., "9.0.0"

### Community 127 - "Community 127"
Cohesion: 1.0
Nodes (1): Create a new KiCAD project          Args:             path: Directory path fo

### Community 128 - "Community 128"
Cohesion: 1.0
Nodes (1): Open an existing KiCAD project          Args:             path: Path to .kica

### Community 129 - "Community 129"
Cohesion: 1.0
Nodes (1): Save the current project          Args:             path: Optional new path t

### Community 130 - "Community 130"
Cohesion: 1.0
Nodes (1): Close the current project

### Community 131 - "Community 131"
Cohesion: 1.0
Nodes (1): Get board API for current project          Returns:             BoardAPI inst

### Community 132 - "Community 132"
Cohesion: 1.0
Nodes (1): Set board size          Args:             width: Board width             hei

### Community 133 - "Community 133"
Cohesion: 1.0
Nodes (1): Get current board size          Returns:             Dictionary with width, h

### Community 134 - "Community 134"
Cohesion: 1.0
Nodes (1): Add a layer to the board          Args:             layer_name: Name of the l

### Community 135 - "Community 135"
Cohesion: 1.0
Nodes (1): List all components on the board          Returns:             List of compon

### Community 136 - "Community 136"
Cohesion: 1.0
Nodes (1): Place a component on the board          Args:             reference: Componen

### Community 137 - "Community 137"
Cohesion: 1.0
Nodes (1): Pillow Image Processing Library

### Community 138 - "Community 138"
Cohesion: 1.0
Nodes (1): Pydantic Data Validation

### Community 139 - "Community 139"
Cohesion: 1.0
Nodes (1): python-dotenv Env Management

### Community 140 - "Community 140"
Cohesion: 1.0
Nodes (1): Colorlog Logging Library

### Community 141 - "Community 141"
Cohesion: 1.0
Nodes (1): Pytest Testing Framework

### Community 142 - "Community 142"
Cohesion: 1.0
Nodes (1): Black Code Formatter

### Community 143 - "Community 143"
Cohesion: 1.0
Nodes (1): MyPy Type Checker

### Community 144 - "Community 144"
Cohesion: 1.0
Nodes (1): Changelog v2.2.1-alpha

### Community 145 - "Community 145"
Cohesion: 1.0
Nodes (1): Changelog v2.2.0-alpha

### Community 146 - "Community 146"
Cohesion: 1.0
Nodes (1): Changelog v1.0.0

### Community 147 - "Community 147"
Cohesion: 1.0
Nodes (1): KiCAD UI Auto-Launch Feature

### Community 148 - "Community 148"
Cohesion: 1.0
Nodes (1): Visual Feedback Guide

### Community 149 - "Community 149"
Cohesion: 1.0
Nodes (1): UI Auto-Launch Guide

### Community 150 - "Community 150"
Cohesion: 1.0
Nodes (1): v1.0.0 Core Foundation Milestone

### Community 151 - "Community 151"
Cohesion: 1.0
Nodes (1): Planned Design Patterns and Templates

### Community 152 - "Community 152"
Cohesion: 1.0
Nodes (1): sym-lib-table Parsing (DynamicSymbolLoader)

### Community 153 - "Community 153"
Cohesion: 1.0
Nodes (1): Community Contributors (10+)

### Community 154 - "Community 154"
Cohesion: 1.0
Nodes (1): Schematic Wiring Implementation Plan (archived)

### Community 155 - "Community 155"
Cohesion: 1.0
Nodes (1): Pin Absolute Position Calculation Algorithm

### Community 156 - "Community 156"
Cohesion: 1.0
Nodes (1): Dynamic Loading MCP Integration (100% passing)

### Community 157 - "Community 157"
Cohesion: 1.0
Nodes (1): Convert a KiCad bounding box object to a normalized mm rectangle.

### Community 158 - "Community 158"
Cohesion: 1.0
Nodes (1): Return the union of rects, or None for an empty list.

## Knowledge Gaps
- **554 isolated node(s):** `Download all split archive parts.`, `Extract the split 7z archive to get cache.sqlite3.`, `Convert jlcparts cache.sqlite3 to the MCP server's expected format.`, `Parser for KiCad .kicad_mod footprint files.  Extracts the fields that the MCP`, `Parse a .kicad_mod file and return a dict whose keys match the fields     expec` (+549 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **Thin community `Community 64`** (2 nodes): `config.ts`, `loadConfig()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 65`** (2 nodes): `design.ts`, `registerDesignPrompts()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 66`** (2 nodes): `datasheet.ts`, `registerDatasheetTools()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 67`** (2 nodes): `jlcpcb-api.ts`, `registerJLCPCBApiTools()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 68`** (2 nodes): `ui.ts`, `registerUITools()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 69`** (2 nodes): `Dynamic Library Loading Plan (archived)`, `Dynamic Symbol Loading Status (complete, prod-ready)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 70`** (2 nodes): `tool_schemas.py`, `Comprehensive tool schema definitions for all KiCAD MCP commands  Following MC`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 71`** (2 nodes): `schematic.ts`, `registerSchematicTools()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 72`** (2 nodes): `freerouting.ts`, `registerFreeroutingTools()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 73`** (1 nodes): `eslint.config.js`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 74`** (1 nodes): `test-router.js`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 75`** (1 nodes): `Check if running on Windows`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 76`** (1 nodes): `Check if running on Linux`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 77`** (1 nodes): `Check if running on macOS`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 78`** (1 nodes): `Get human-readable platform name`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 79`** (1 nodes): `Get potential KiCAD Python dist-packages paths for current platform          R`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 80`** (1 nodes): `Get the first valid KiCAD Python path          Returns:             Path to K`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 81`** (1 nodes): `Get platform-appropriate KiCAD symbol library search paths          Returns:`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 82`** (1 nodes): `r"""         Get appropriate configuration directory for current platform`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 83`** (1 nodes): `Get appropriate log directory for current platform          Returns:`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 84`** (1 nodes): `r"""         Get appropriate cache directory for current platform          Fo`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 85`** (1 nodes): `Create all necessary directories if they don't exist`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 86`** (1 nodes): `Get path to current Python executable`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 87`** (1 nodes): `Add KiCAD Python paths to sys.path          Returns:             True if at l`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 88`** (1 nodes): `List running processes on Windows using Toolhelp API.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 89`** (1 nodes): `Check if KiCAD is currently running          Returns:             True if KiC`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 90`** (1 nodes): `Get path to KiCAD executable          Returns:             Path to pcbnew/kic`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 91`** (1 nodes): `Launch KiCAD PCB Editor          Args:             project_path: Optional pat`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 92`** (1 nodes): `Get information about running KiCAD processes          Returns:             L`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 93`** (1 nodes): `create_schematic()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 94`** (1 nodes): `load_schematic()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 95`** (1 nodes): `save_schematic()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 96`** (1 nodes): `get_schematic_metadata()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 97`** (1 nodes): `Create a new empty schematic from template`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 98`** (1 nodes): `Load an existing schematic`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 99`** (1 nodes): `Save a schematic to file`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 100`** (1 nodes): `Extract metadata from schematic`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 101`** (1 nodes): `Add a wire to the schematic using S-expression manipulation          Args:`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 102`** (1 nodes): `Add a multi-segment wire (polyline) to the schematic          Args:`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 103`** (1 nodes): `Add a net label to the schematic          Args:             schematic_path: P`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 104`** (1 nodes): `Parse a wire S-expression item in a single pass.         Returns ((x1,y1), (x2,`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 105`** (1 nodes): `Return True if (px, py) lies strictly between (x1,y1) and (x2,y2)         on a`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 106`** (1 nodes): `Split any wire segment that passes through *position* as a strict         midpo`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 107`** (1 nodes): `Add a junction (connection dot) to the schematic.          Mirrors KiCAD's Add`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 108`** (1 nodes): `Add a no-connect flag to the schematic          Args:             schematic_p`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 109`** (1 nodes): `Delete a wire from the schematic matching given start/end coordinates.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 110`** (1 nodes): `Delete a net label from the schematic by name (and optionally position).`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 111`** (1 nodes): `Create an orthogonal (right-angle) path between two points          Args:`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 112`** (1 nodes): `Generate a 32-character random nonce`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 113`** (1 nodes): `Search for components matching criteria (basic implementation)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 114`** (1 nodes): `List all available symbol libraries`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 115`** (1 nodes): `List all symbols in a library`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 116`** (1 nodes): `Get detailed information about a symbol`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 117`** (1 nodes): `Search for symbols matching criteria`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 118`** (1 nodes): `Get a recommended default symbol for a given component type`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 119`** (1 nodes): `Normalize LCSC number to standard format 'C123456'.          Accepts: 'C123456',`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 120`** (1 nodes): `Find the line range of the (lib_symbols ...) section.         Returns (start, en`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 121`** (1 nodes): `Extract LCSC and Datasheet info from a placed symbol block.          Returns dic`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 122`** (1 nodes): `Freerouting autoroute integration for KiCAD MCP Server.  Exports the board to Sp`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 123`** (1 nodes): `Connect to KiCAD          Returns:             True if connection successful,`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 124`** (1 nodes): `Disconnect from KiCAD and clean up resources`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 125`** (1 nodes): `Check if currently connected to KiCAD          Returns:             True if c`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 126`** (1 nodes): `Get KiCAD version          Returns:             Version string (e.g., "9.0.0"`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 127`** (1 nodes): `Create a new KiCAD project          Args:             path: Directory path fo`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 128`** (1 nodes): `Open an existing KiCAD project          Args:             path: Path to .kica`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 129`** (1 nodes): `Save the current project          Args:             path: Optional new path t`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 130`** (1 nodes): `Close the current project`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 131`** (1 nodes): `Get board API for current project          Returns:             BoardAPI inst`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 132`** (1 nodes): `Set board size          Args:             width: Board width             hei`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 133`** (1 nodes): `Get current board size          Returns:             Dictionary with width, h`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 134`** (1 nodes): `Add a layer to the board          Args:             layer_name: Name of the l`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 135`** (1 nodes): `List all components on the board          Returns:             List of compon`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 136`** (1 nodes): `Place a component on the board          Args:             reference: Componen`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 137`** (1 nodes): `Pillow Image Processing Library`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 138`** (1 nodes): `Pydantic Data Validation`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 139`** (1 nodes): `python-dotenv Env Management`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 140`** (1 nodes): `Colorlog Logging Library`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 141`** (1 nodes): `Pytest Testing Framework`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 142`** (1 nodes): `Black Code Formatter`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 143`** (1 nodes): `MyPy Type Checker`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 144`** (1 nodes): `Changelog v2.2.1-alpha`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 145`** (1 nodes): `Changelog v2.2.0-alpha`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 146`** (1 nodes): `Changelog v1.0.0`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 147`** (1 nodes): `KiCAD UI Auto-Launch Feature`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 148`** (1 nodes): `Visual Feedback Guide`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 149`** (1 nodes): `UI Auto-Launch Guide`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 150`** (1 nodes): `v1.0.0 Core Foundation Milestone`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 151`** (1 nodes): `Planned Design Patterns and Templates`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 152`** (1 nodes): `sym-lib-table Parsing (DynamicSymbolLoader)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 153`** (1 nodes): `Community Contributors (10+)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 154`** (1 nodes): `Schematic Wiring Implementation Plan (archived)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 155`** (1 nodes): `Pin Absolute Position Calculation Algorithm`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 156`** (1 nodes): `Dynamic Loading MCP Integration (100% passing)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 157`** (1 nodes): `Convert a KiCad bounding box object to a normalized mm rectangle.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 158`** (1 nodes): `Return the union of rects, or None for an empty list.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `RoutingCommands` connect `Community 1` to `Community 3`?**
  _High betweenness centrality (0.078) - this node is a cross-community bridge._
- **Why does `PinLocator` connect `Community 0` to `Community 5`, `Community 6`, `Community 15`, `Community 28`, `Community 30`?**
  _High betweenness centrality (0.057) - this node is a cross-community bridge._
- **Why does `Tests for KiCAD MCP Server` connect `Community 4` to `Community 2`, `Community 20`?**
  _High betweenness centrality (0.055) - this node is a cross-community bridge._
- **Are the 8 inferred relationships involving `KiCADInterface` (e.g. with `AutorouteCFHACommands` and `RoutingCommands`) actually correct?**
  _`KiCADInterface` has 8 INFERRED edges - model-reasoned connections that need verification._
- **Are the 114 inferred relationships involving `PinLocator` (e.g. with `Wire Connectivity Analysis for KiCad Schematics  Traces wire networks from a p` and `Convert mm coordinates to KiCad internal units (integer).`) actually correct?**
  _`PinLocator` has 114 INFERRED edges - model-reasoned connections that need verification._
- **Are the 86 inferred relationships involving `WireManager` (e.g. with `ConnectionManager` and `Manage connections between components in schematics`) actually correct?**
  _`WireManager` has 86 INFERRED edges - model-reasoned connections that need verification._
- **Are the 57 inferred relationships involving `BoardAPI` (e.g. with `SWIGBackend` and `SWIGBoardAPI`) actually correct?**
  _`BoardAPI` has 57 INFERRED edges - model-reasoned connections that need verification._