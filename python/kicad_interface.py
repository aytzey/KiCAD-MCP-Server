#!/usr/bin/env python3
"""
KiCAD Python Interface Script for Model Context Protocol

This script handles communication between the MCP TypeScript server
and KiCAD's Python API (pcbnew). It receives commands via stdin as
JSON and returns responses via stdout also as JSON.
"""

import json
import logging
import os
import sys
import traceback
from typing import Any, Dict, List, Optional

from resources.resource_definitions import RESOURCE_DEFINITIONS, handle_resource_read

# Import tool schemas and resource definitions
from schemas.tool_schemas import TOOL_SCHEMAS

# Configure logging
log_dir = os.path.join(os.path.expanduser("~"), ".kicad-mcp", "logs")
os.makedirs(log_dir, exist_ok=True)
log_file = os.path.join(log_dir, "kicad_interface.log")

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(log_file)],
)
logger = logging.getLogger("kicad_interface")

# Log Python environment details
logger.info(f"Python version: {sys.version}")
logger.info(f"Python executable: {sys.executable}")
logger.info(f"Platform: {sys.platform}")
logger.info(f"Working directory: {os.getcwd()}")

# Windows-specific diagnostics
if sys.platform == "win32":
    logger.info("=== Windows Environment Diagnostics ===")
    logger.info(f"PYTHONPATH: {os.environ.get('PYTHONPATH', 'NOT SET')}")
    logger.info(f"PATH: {os.environ.get('PATH', 'NOT SET')[:200]}...")  # Truncate PATH

    # Check for common KiCAD installations
    common_kicad_paths = [r"C:\Program Files\KiCad", r"C:\Program Files (x86)\KiCad"]

    found_kicad = False
    for base_path in common_kicad_paths:
        if os.path.exists(base_path):
            logger.info(f"Found KiCAD installation at: {base_path}")
            # List versions
            try:
                versions = [
                    d for d in os.listdir(base_path) if os.path.isdir(os.path.join(base_path, d))
                ]
                logger.info(f"  Versions found: {', '.join(versions)}")
                for version in versions:
                    python_path = os.path.join(
                        base_path, version, "lib", "python3", "dist-packages"
                    )
                    if os.path.exists(python_path):
                        logger.info(f"  ✓ Python path exists: {python_path}")
                        found_kicad = True
                    else:
                        logger.warning(f"  ✗ Python path missing: {python_path}")
            except Exception as e:
                logger.warning(f"  Could not list versions: {e}")

    if not found_kicad:
        logger.warning("No KiCAD installations found in standard locations!")
        logger.warning(
            "Please ensure KiCAD 9.0+ is installed from https://www.kicad.org/download/windows/"
        )

    logger.info("========================================")

# Add utils directory to path for imports
utils_dir = os.path.join(os.path.dirname(__file__))
if utils_dir not in sys.path:
    sys.path.insert(0, utils_dir)

from utils.kicad_process import KiCADProcessManager, check_and_launch_kicad

# Import platform helper and add KiCAD paths
from utils.platform_helper import PlatformHelper

logger.info(f"Detecting KiCAD Python paths for {PlatformHelper.get_platform_name()}...")
paths_added = PlatformHelper.add_kicad_to_python_path()

if paths_added:
    logger.info("Successfully added KiCAD Python paths to sys.path")
else:
    logger.warning("No KiCAD Python paths found - attempting to import pcbnew from system path")

logger.info(f"Current Python path: {sys.path}")

# Check if auto-launch is enabled
AUTO_LAUNCH_KICAD = os.environ.get("KICAD_AUTO_LAUNCH", "false").lower() == "true"
if AUTO_LAUNCH_KICAD:
    logger.info("KiCAD auto-launch enabled")

# Check which backend to use
# KICAD_BACKEND can be: 'auto', 'ipc', or 'swig'
KICAD_BACKEND = os.environ.get("KICAD_BACKEND", "auto").lower()
logger.info(f"KiCAD backend preference: {KICAD_BACKEND}")

# Try to use IPC backend first if available and preferred
USE_IPC_BACKEND = False
ipc_backend = None

if KICAD_BACKEND in ("auto", "ipc"):
    try:
        logger.info("Checking IPC backend availability...")
        from kicad_api.ipc_backend import IPCBackend

        # Try to connect to running KiCAD
        ipc_backend = IPCBackend()
        if ipc_backend.connect():
            USE_IPC_BACKEND = True
            logger.info(f"✓ Using IPC backend - real-time UI sync enabled!")
            logger.info(f"  KiCAD version: {ipc_backend.get_version()}")
        else:
            logger.info("IPC backend available but KiCAD not running with IPC enabled")
            ipc_backend = None
    except ImportError:
        logger.info("IPC backend not available (kicad-python not installed)")
    except Exception as e:
        logger.info(f"IPC backend connection failed: {e}")
        ipc_backend = None

# Fall back to SWIG backend if IPC not available
if not USE_IPC_BACKEND and KICAD_BACKEND != "ipc":
    # Import KiCAD's Python API (SWIG)
    try:
        logger.info("Attempting to import pcbnew module (SWIG backend)...")
        import pcbnew  # type: ignore

        logger.info(f"Successfully imported pcbnew module from: {pcbnew.__file__}")
        logger.info(f"pcbnew version: {pcbnew.GetBuildVersion()}")
        logger.warning("Using SWIG backend - changes require manual reload in KiCAD UI")
    except ImportError as e:
        logger.error(f"Failed to import pcbnew module: {e}")
        logger.error(f"Current sys.path: {sys.path}")

        # Platform-specific help message
        help_message = ""
        if sys.platform == "win32":
            help_message = """
Windows Troubleshooting:
1. Verify KiCAD is installed: C:\\Program Files\\KiCad\\9.0
2. Check PYTHONPATH environment variable points to:
   C:\\Program Files\\KiCad\\9.0\\lib\\python3\\dist-packages
3. Test with: "C:\\Program Files\\KiCad\\9.0\\bin\\python.exe" -c "import pcbnew"
4. Log file location: %USERPROFILE%\\.kicad-mcp\\logs\\kicad_interface.log
5. Run setup-windows.ps1 for automatic configuration
"""
        elif sys.platform == "darwin":
            help_message = """
macOS Troubleshooting:
1. Verify KiCAD is installed: /Applications/KiCad/KiCad.app
2. Check PYTHONPATH points to KiCAD's Python packages
3. Run: python3 -c "import pcbnew" to test
"""
        else:  # Linux
            help_message = """
Linux Troubleshooting:
1. Verify KiCAD is installed: apt list --installed | grep kicad
2. Check: /usr/lib/kicad/lib/python3/dist-packages exists
3. Test: python3 -c "import pcbnew"
"""

        logger.error(help_message)

        error_response = {
            "success": False,
            "message": "Failed to import pcbnew module - KiCAD Python API not found",
            "errorDetails": f"Error: {str(e)}\n\n{help_message}\n\nPython sys.path:\n{chr(10).join(sys.path)}",
        }
        print(json.dumps(error_response))
        sys.exit(1)
    except Exception as e:
        logger.error(f"Unexpected error importing pcbnew: {e}")
        logger.error(traceback.format_exc())
        error_response = {
            "success": False,
            "message": "Error importing pcbnew module",
            "errorDetails": str(e),
        }
        print(json.dumps(error_response))
        sys.exit(1)

# If IPC-only mode requested but not available, exit with error
elif KICAD_BACKEND == "ipc" and not USE_IPC_BACKEND:
    error_response = {
        "success": False,
        "message": "IPC backend requested but not available",
        "errorDetails": "KiCAD must be running with IPC API enabled. Enable at: Preferences > Plugins > Enable IPC API Server",
    }
    print(json.dumps(error_response))
    sys.exit(1)

# Import command handlers
try:
    logger.info("Importing command handlers...")
    from commands.board import BoardCommands
    from commands.component import ComponentCommands
    from commands.component_schematic import ComponentManager
    from commands.connection_schematic import ConnectionManager
    from commands.datasheet_manager import DatasheetManager
    from commands.design_rules import DesignRuleCommands
    from commands.export import ExportCommands
    from commands.footprint import FootprintCreator
    from commands.autoroute_cfha import AutorouteCFHACommands
    from commands.freerouting import FreeroutingCommands
    from commands.jlcpcb import JLCPCBClient, test_jlcpcb_connection
    from commands.jlcpcb_parts import JLCPCBPartsManager
    from commands.library import (
        LibraryCommands,
    )
    from commands.library import LibraryManager as FootprintLibraryManager
    from commands.library_schematic import LibraryManager as SchematicLibraryManager
    from commands.library_symbol import SymbolLibraryCommands, SymbolLibraryManager
    from commands.project import ProjectCommands
    from commands.routing import RoutingCommands
    from commands.schematic import SchematicManager
    from commands.symbol_creator import SymbolCreator

    # Import extracted handler classes
    from commands.schematic_handlers import SchematicHandlers
    from commands.footprint_handlers import FootprintHandlers
    from commands.symbol_handlers import SymbolHandlers
    from commands.jlcpcb_handlers import JLCPCBHandlers
    from commands.ipc_handlers import IPCHandlers
    from commands.misc_handlers import MiscHandlers

    logger.info("Successfully imported all command handlers")
except ImportError as e:
    logger.error(f"Failed to import command handlers: {e}")
    error_response = {
        "success": False,
        "message": "Failed to import command handlers",
        "errorDetails": str(e),
    }
    print(json.dumps(error_response))
    sys.exit(1)


class KiCADInterface:
    """Main interface class to handle KiCAD operations"""

    def __init__(self):
        """Initialize the interface and command handlers"""
        self.board = None
        self.project_filename = None
        self.use_ipc = USE_IPC_BACKEND
        self.ipc_backend = ipc_backend
        self.ipc_board_api = None

        if self.use_ipc:
            logger.info("Initializing with IPC backend (real-time UI sync enabled)")
            try:
                self.ipc_board_api = self.ipc_backend.get_board()
                logger.info("✓ Got IPC board API")
            except Exception as e:
                logger.warning(f"Could not get IPC board API: {e}")
        else:
            logger.info("Initializing with SWIG backend")

        logger.info("Initializing command handlers...")

        # Initialize footprint library manager
        self.footprint_library = FootprintLibraryManager()

        # Initialize domain command handlers
        self.project_commands = ProjectCommands(self.board)
        self.board_commands = BoardCommands(self.board)
        self.component_commands = ComponentCommands(self.board, self.footprint_library)
        self.routing_commands = RoutingCommands(self.board)
        self.freerouting_commands = FreeroutingCommands(self.board)
        self.design_rule_commands = DesignRuleCommands(self.board)
        self.autoroute_cfha_commands = AutorouteCFHACommands(
            self.board,
            self.routing_commands,
            self.freerouting_commands,
            self.design_rule_commands,
            self.ipc_board_api,
        )
        self.export_commands = ExportCommands(self.board)
        self.library_commands = LibraryCommands(self.footprint_library)
        self._current_project_path: Optional[Path] = None  # set when boardPath is known

        # Initialize symbol library manager (for searching local KiCad symbol libraries)
        self.symbol_library_commands = SymbolLibraryCommands()

        # Initialize JLCPCB API integration
        self.jlcpcb_client = JLCPCBClient()  # Official API (requires auth)
        from commands.jlcsearch import JLCSearchClient

        self.jlcsearch_client = JLCSearchClient()  # Public API (no auth required)
        self.jlcpcb_parts = JLCPCBPartsManager()

        # Initialize extracted handler classes
        self.schematic_handlers = SchematicHandlers(
            design_rule_commands=self.design_rule_commands,
        )
        self.footprint_handlers = FootprintHandlers()
        self.symbol_handlers = SymbolHandlers()
        self.jlcpcb_handlers = JLCPCBHandlers(
            jlcpcb_parts=self.jlcpcb_parts,
            jlcsearch_client=self.jlcsearch_client,
        )
        self.ipc_handlers = IPCHandlers(
            ipc_board_api=self.ipc_board_api,
            ipc_backend=self.ipc_backend,
            use_ipc=self.use_ipc,
        )
        self.misc_handlers = MiscHandlers()

        # Command routing dictionary
        self.command_routes = {
            # Project commands
            "create_project": self.project_commands.create_project,
            "open_project": self.project_commands.open_project,
            "save_project": self.project_commands.save_project,
            "snapshot_project": self._handle_snapshot_project,
            "get_project_info": self.project_commands.get_project_info,
            # Board commands
            "set_board_size": self.board_commands.set_board_size,
            "add_layer": self.board_commands.add_layer,
            "set_active_layer": self.board_commands.set_active_layer,
            "get_board_info": self.board_commands.get_board_info,
            "get_layer_list": self.board_commands.get_layer_list,
            "get_board_2d_view": self.board_commands.get_board_2d_view,
            "get_board_extents": self.board_commands.get_board_extents,
            "add_board_outline": self.board_commands.add_board_outline,
            "add_mounting_hole": self.board_commands.add_mounting_hole,
            "add_text": self.board_commands.add_text,
            "add_board_text": self.board_commands.add_text,  # Alias for TypeScript tool
            # Component commands
            "route_pad_to_pad": self.routing_commands.route_pad_to_pad,
            "place_component": self._handle_place_component,
            "move_component": self.component_commands.move_component,
            "rotate_component": self.component_commands.rotate_component,
            "delete_component": self.component_commands.delete_component,
            "edit_component": self.component_commands.edit_component,
            "get_component_properties": self.component_commands.get_component_properties,
            "get_component_list": self.component_commands.get_component_list,
            "find_component": self.component_commands.find_component,
            "get_component_pads": self.component_commands.get_component_pads,
            "get_pad_position": self.component_commands.get_pad_position,
            "place_component_array": self.component_commands.place_component_array,
            "align_components": self.component_commands.align_components,
            "duplicate_component": self.component_commands.duplicate_component,
            # Routing commands
            "add_net": self.routing_commands.add_net,
            "route_trace": self.routing_commands.route_trace,
            "add_via": self.routing_commands.add_via,
            "delete_trace": self.routing_commands.delete_trace,
            "query_traces": self.routing_commands.query_traces,
            "modify_trace": self.routing_commands.modify_trace,
            "copy_routing_pattern": self.routing_commands.copy_routing_pattern,
            "get_nets_list": self.routing_commands.get_nets_list,
            "create_netclass": self.routing_commands.create_netclass,
            "add_copper_pour": self.routing_commands.add_copper_pour,
            "route_differential_pair": self.routing_commands.route_differential_pair,
            "refill_zones": self._handle_refill_zones,
            # Hybrid autorouting commands
            "analyze_board_routing_context": self._handle_analyze_board_routing_context,
            "extract_routing_intents": self._handle_extract_routing_intents,
            "generate_routing_constraints": self._handle_generate_routing_constraints,
            "generate_kicad_dru": self._handle_generate_kicad_dru,
            "route_critical_nets": self._handle_route_critical_nets,
            "run_freerouting": self._handle_run_freerouting,
            "post_tune_routes": self._handle_post_tune_routes,
            "verify_routing_qor": self._handle_verify_routing_qor,
            # Design rule commands
            "set_design_rules": self.design_rule_commands.set_design_rules,
            "get_design_rules": self.design_rule_commands.get_design_rules,
            "run_drc": self.design_rule_commands.run_drc,
            "get_drc_violations": self.design_rule_commands.get_drc_violations,
            # Export commands
            "export_gerber": self.export_commands.export_gerber,
            "export_pdf": self.export_commands.export_pdf,
            "export_svg": self.export_commands.export_svg,
            "export_3d": self.export_commands.export_3d,
            "export_bom": self.export_commands.export_bom,
            # Library commands (footprint management)
            "list_libraries": self.library_commands.list_libraries,
            "search_footprints": self.library_commands.search_footprints,
            "list_library_footprints": self.library_commands.list_library_footprints,
            "get_footprint_info": self.library_commands.get_footprint_info,
            # Symbol library commands (local KiCad symbol library search)
            "list_symbol_libraries": self.symbol_library_commands.list_symbol_libraries,
            "search_symbols": self.symbol_library_commands.search_symbols,
            "list_library_symbols": self.symbol_library_commands.list_library_symbols,
            "get_symbol_info": self.symbol_library_commands.get_symbol_info,
            # JLCPCB API commands → JLCPCBHandlers
            "download_jlcpcb_database": self.jlcpcb_handlers.download_jlcpcb_database,
            "search_jlcpcb_parts": self.jlcpcb_handlers.search_jlcpcb_parts,
            "get_jlcpcb_part": self.jlcpcb_handlers.get_jlcpcb_part,
            "get_jlcpcb_database_stats": self.jlcpcb_handlers.get_jlcpcb_database_stats,
            "suggest_jlcpcb_alternatives": self.jlcpcb_handlers.suggest_jlcpcb_alternatives,
            # Datasheet commands → JLCPCBHandlers
            "enrich_datasheets": self.jlcpcb_handlers.enrich_datasheets,
            "get_datasheet_url": self.jlcpcb_handlers.get_datasheet_url,
            # Schematic commands → SchematicHandlers
            "create_schematic": self.schematic_handlers.create_schematic,
            "load_schematic": self.schematic_handlers.load_schematic,
            "add_schematic_component": self.schematic_handlers.add_schematic_component,
            "delete_schematic_component": self.schematic_handlers.delete_schematic_component,
            "edit_schematic_component": self.schematic_handlers.edit_schematic_component,
            "get_schematic_component": self.schematic_handlers.get_schematic_component,
            "add_schematic_wire": self.schematic_handlers.add_schematic_wire,
            "add_schematic_net_label": self.schematic_handlers.add_schematic_net_label,
            "add_schematic_junction": self.schematic_handlers.add_schematic_junction,
            "connect_to_net": self.schematic_handlers.connect_to_net,
            "connect_passthrough": self.schematic_handlers.connect_passthrough,
            "get_schematic_pin_locations": self.schematic_handlers.get_schematic_pin_locations,
            "get_net_connections": self.schematic_handlers.get_net_connections,
            "get_wire_connections": self.schematic_handlers.get_wire_connections,
            "run_erc": self.schematic_handlers.run_erc,
            "generate_netlist": self.schematic_handlers.generate_netlist,
            "sync_schematic_to_board": self._handle_sync_schematic_to_board,
            "list_schematic_libraries": self.schematic_handlers.list_schematic_libraries,
            "get_schematic_view": self.schematic_handlers.get_schematic_view,
            "list_schematic_components": self.schematic_handlers.list_schematic_components,
            "list_schematic_nets": self.schematic_handlers.list_schematic_nets,
            "list_schematic_wires": self.schematic_handlers.list_schematic_wires,
            "list_schematic_labels": self.schematic_handlers.list_schematic_labels,
            "move_schematic_component": self.schematic_handlers.move_schematic_component,
            "rotate_schematic_component": self.schematic_handlers.rotate_schematic_component,
            "annotate_schematic": self.schematic_handlers.annotate_schematic,
            "delete_schematic_wire": self.schematic_handlers.delete_schematic_wire,
            "delete_schematic_net_label": self.schematic_handlers.delete_schematic_net_label,
            "export_schematic_pdf": self.schematic_handlers.export_schematic_pdf,
            "export_schematic_svg": self.schematic_handlers.export_schematic_svg,
            # Schematic analysis tools → SchematicHandlers
            "get_schematic_view_region": self.schematic_handlers.get_schematic_view_region,
            "find_overlapping_elements": self.schematic_handlers.find_overlapping_elements,
            "get_elements_in_region": self.schematic_handlers.get_elements_in_region,
            "find_wires_crossing_symbols": self.schematic_handlers.find_wires_crossing_symbols,
            # Misc commands → MiscHandlers
            "import_svg_logo": self._handle_import_svg_logo,
            "check_kicad_ui": self.misc_handlers.check_kicad_ui,
            "launch_kicad_ui": self.misc_handlers.launch_kicad_ui,
            # IPC-specific commands → IPCHandlers
            "get_backend_info": self.ipc_handlers.get_backend_info,
            "ipc_add_track": self.ipc_handlers.handle_ipc_add_track,
            "ipc_add_via": self.ipc_handlers.handle_ipc_add_via,
            "ipc_add_text": self.ipc_handlers.handle_ipc_add_text,
            "ipc_list_components": self.ipc_handlers.handle_ipc_list_components,
            "ipc_get_tracks": self.ipc_handlers.handle_ipc_get_tracks,
            "ipc_get_vias": self.ipc_handlers.handle_ipc_get_vias,
            "ipc_save_board": self.ipc_handlers.handle_ipc_save_board,
            # Footprint commands → FootprintHandlers
            "create_footprint": self.footprint_handlers.create_footprint,
            "edit_footprint_pad": self.footprint_handlers.edit_footprint_pad,
            "list_footprint_libraries": self.footprint_handlers.list_footprint_libraries,
            "register_footprint_library": self.footprint_handlers.register_footprint_library,
            # Symbol creator commands → SymbolHandlers
            "create_symbol": self.symbol_handlers.create_symbol,
            "delete_symbol": self.symbol_handlers.delete_symbol,
            "list_symbols_in_library": self.symbol_handlers.list_symbols_in_library,
            "register_symbol_library": self.symbol_handlers.register_symbol_library,
            # Freerouting autoroute commands
            "autoroute": self._handle_autoroute_default,
            "autoroute_cfha": self._handle_autoroute_cfha,
            "export_dsn": self.freerouting_commands.export_dsn,
            "import_ses": self.freerouting_commands.import_ses,
            "check_freerouting": self.freerouting_commands.check_freerouting,
        }

        logger.info(f"KiCAD interface initialized (backend: {'IPC' if self.use_ipc else 'SWIG'})")

    # Commands that can be handled via IPC for real-time updates
    # Method names reference IPCHandlers class (looked up via getattr on self.ipc_handlers)
    IPC_CAPABLE_COMMANDS = {
        # Routing commands
        "route_trace": "ipc_route_trace",
        "add_via": "ipc_add_via",
        "add_net": "ipc_add_net",
        "delete_trace": "ipc_delete_trace",
        "get_nets_list": "ipc_get_nets_list",
        # Zone commands
        "add_copper_pour": "ipc_add_copper_pour",
        "refill_zones": "ipc_refill_zones",
        # Board commands
        "add_text": "ipc_add_text",
        "add_board_text": "ipc_add_text",
        "set_board_size": "ipc_set_board_size",
        "get_board_info": "ipc_get_board_info",
        "add_board_outline": "ipc_add_board_outline",
        "add_mounting_hole": "ipc_add_mounting_hole",
        "get_layer_list": "ipc_get_layer_list",
        # Component commands
        "place_component": "ipc_place_component",
        "move_component": "ipc_move_component",
        "rotate_component": "ipc_rotate_component",
        "delete_component": "ipc_delete_component",
        "get_component_list": "ipc_get_component_list",
        "get_component_properties": "ipc_get_component_properties",
        # Save command
        "save_project": "ipc_save_project",
    }

    def handle_command(self, command: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Route command to appropriate handler, preferring IPC when available"""
        logger.info(f"Handling command: {command}")
        logger.debug(f"Command parameters: {params}")

        try:
            # Check if we can use IPC for this command (real-time UI sync)
            if self.use_ipc and self.ipc_board_api and command in self.IPC_CAPABLE_COMMANDS:
                ipc_handler_name = self.IPC_CAPABLE_COMMANDS[command]
                ipc_handler = getattr(self.ipc_handlers, ipc_handler_name, None)

                if ipc_handler:
                    logger.info(f"Using IPC backend for {command} (real-time sync)")
                    result = ipc_handler(params)

                    # Add indicator that IPC was used
                    if isinstance(result, dict):
                        result["_backend"] = "ipc"
                        result["_realtime"] = True

                    logger.debug(f"IPC command result: {result}")
                    return result

            # Fall back to SWIG-based handler
            if self.use_ipc and command in self.IPC_CAPABLE_COMMANDS:
                logger.warning(
                    f"IPC handler not available for {command}, falling back to SWIG (deprecated)"
                )

            # Get the handler for the command
            handler = self.command_routes.get(command)

            if handler:
                # Execute the command
                result = handler(params)
                logger.debug(f"Command result: {result}")

                # Add backend indicator
                if isinstance(result, dict):
                    result["_backend"] = "swig"
                    result["_realtime"] = False

                # Update board reference if command was successful
                if result.get("success", False):
                    if command == "create_project" or command == "open_project":
                        logger.info("Updating board reference...")
                        # Get board from the project commands handler
                        self.board = self.project_commands.board
                        self._update_command_handlers()
                    elif command in self._BOARD_MUTATING_COMMANDS:
                        # Auto-save after every board mutation via SWIG.
                        # Prevents data loss if Claude hits context limit before
                        # an explicit save_project call.
                        self._auto_save_board()

                return result
            else:
                logger.error(f"Unknown command: {command}")
                return {
                    "success": False,
                    "message": f"Unknown command: {command}",
                    "errorDetails": "The specified command is not supported",
                }

        except Exception as e:
            # Get the full traceback
            traceback_str = traceback.format_exc()
            logger.error(f"Error handling command {command}: {str(e)}\n{traceback_str}")
            return {
                "success": False,
                "message": f"Error handling command: {command}",
                "errorDetails": f"{str(e)}\n{traceback_str}",
            }

    # Board-mutating commands that trigger auto-save on SWIG path
    _BOARD_MUTATING_COMMANDS = {
        "place_component",
        "move_component",
        "rotate_component",
        "delete_component",
        "route_trace",
        "route_pad_to_pad",
        "add_via",
        "delete_trace",
        "add_net",
        "add_board_outline",
        "add_mounting_hole",
        "add_text",
        "add_board_text",
        "add_copper_pour",
        "refill_zones",
        "route_critical_nets",
        "run_freerouting",
        "post_tune_routes",
        "autoroute",
        "autoroute_cfha",
        "import_svg_logo",
        "sync_schematic_to_board",
        "connect_passthrough",
    }

    def _auto_save_board(self):
        """Save board to disk after SWIG mutations.
        Called automatically after every board-mutating SWIG command so that
        data is not lost if Claude hits the context limit before save_project.
        """
        try:
            if self.board:
                board_path = self.board.GetFileName()
                if board_path:
                    pcbnew.SaveBoard(board_path, self.board)
                    logger.debug(f"Auto-saved board to: {board_path}")
        except Exception as e:
            logger.warning(f"Auto-save failed: {e}")

    def _ensure_handlers(self):
        """Lazily initialize handler classes when __init__ was bypassed (e.g. __new__ in tests)."""
        d = self.__dict__
        if "schematic_handlers" not in d:
            d["schematic_handlers"] = SchematicHandlers(
                design_rule_commands=d.get("design_rule_commands"),
            )
        if "footprint_handlers" not in d:
            d["footprint_handlers"] = FootprintHandlers()
        if "symbol_handlers" not in d:
            d["symbol_handlers"] = SymbolHandlers()
        if "jlcpcb_handlers" not in d:
            d["jlcpcb_handlers"] = JLCPCBHandlers(
                jlcpcb_parts=d.get("jlcpcb_parts"),
                jlcsearch_client=d.get("jlcsearch_client"),
            )
        if "ipc_handlers" not in d:
            d["ipc_handlers"] = IPCHandlers(
                ipc_board_api=d.get("ipc_board_api"),
                ipc_backend=d.get("ipc_backend"),
                use_ipc=d.get("use_ipc", False),
            )
        if "misc_handlers" not in d:
            d["misc_handlers"] = MiscHandlers()

    def _update_command_handlers(self):
        """Update board reference in all command handlers"""
        logger.debug("Updating board reference in command handlers")
        self.project_commands.board = self.board
        self.board_commands.board = self.board
        self.component_commands.board = self.board
        self.routing_commands.board = self.board
        self.design_rule_commands.board = self.board
        self.export_commands.board = self.board
        self.freerouting_commands.board = self.board
        self.autoroute_cfha_commands.set_board(self.board)
        self.autoroute_cfha_commands.set_ipc_board_api(self.ipc_board_api)

    def _reload_board_if_needed(self, board_path: Optional[str]):
        """Reload the active board if a command targets a different file."""
        from pathlib import Path

        if not board_path:
            return None

        target = str(Path(board_path).resolve())
        current = str(Path(self.board.GetFileName()).resolve()) if self.board and self.board.GetFileName() else ""
        if target == current:
            return None

        logger.info(f"Reloading board from boardPath for hybrid routing command: {board_path}")
        try:
            self.board = pcbnew.LoadBoard(board_path)
            self._update_command_handlers()
            return None
        except Exception as e:
            logger.error(f"Failed to reload board from boardPath: {e}")
            return {
                "success": False,
                "message": f"Could not load board from boardPath: {board_path}",
                "errorDetails": str(e),
            }

    def _handle_cfha_command(self, params, method_name: str):
        reload_error = self._reload_board_if_needed(params.get("boardPath"))
        if reload_error:
            return reload_error
        handler = getattr(self.autoroute_cfha_commands, method_name)
        return handler(params)

    def _handle_analyze_board_routing_context(self, params):
        return self._handle_cfha_command(params, "analyze_board_routing_context")

    def _handle_extract_routing_intents(self, params):
        return self._handle_cfha_command(params, "extract_routing_intents")

    def _handle_generate_routing_constraints(self, params):
        return self._handle_cfha_command(params, "generate_routing_constraints")

    def _handle_generate_kicad_dru(self, params):
        return self._handle_cfha_command(params, "generate_kicad_dru")

    def _handle_route_critical_nets(self, params):
        return self._handle_cfha_command(params, "route_critical_nets")

    def _handle_run_freerouting(self, params):
        return self._handle_cfha_command(params, "run_freerouting")

    def _handle_post_tune_routes(self, params):
        return self._handle_cfha_command(params, "post_tune_routes")

    def _handle_verify_routing_qor(self, params):
        return self._handle_cfha_command(params, "verify_routing_qor")

    def _handle_autoroute_cfha(self, params):
        return self._handle_cfha_command(params, "autoroute_cfha")

    def _handle_autoroute_default(self, params):
        return self._handle_cfha_command(params, "autoroute_default")

    # Handler classes used by delegation stubs and command_routes.
    # Accessed via __getattr__ for lazy init when __init__ is bypassed (e.g. tests using __new__).
    _HANDLER_ATTRS = frozenset({
        "schematic_handlers", "footprint_handlers", "symbol_handlers",
        "jlcpcb_handlers", "ipc_handlers", "misc_handlers",
    })

    def __getattr__(self, name):
        if name in KiCADInterface._HANDLER_ATTRS:
            self._ensure_handlers()
            return object.__getattribute__(self, name)
        raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'")

    # ---- Delegation stubs (backward compat) ----

    def _handle_create_schematic(self, params):
        return self.schematic_handlers.create_schematic(params)

    def _handle_load_schematic(self, params):
        return self.schematic_handlers.load_schematic(params)

    def _handle_place_component(self, params):
        """Place a component on the PCB, with project-local fp-lib-table support.
        If boardPath is given and differs from the currently loaded board, the
        board is reloaded from boardPath before placing — prevents silent failures
        when Claude provides a boardPath that was not yet loaded.
        """
        from pathlib import Path

        board_path = params.get("boardPath")
        if board_path:
            board_path_norm = str(Path(board_path).resolve())
            current_board_file = str(Path(self.board.GetFileName()).resolve()) if self.board else ""
            if board_path_norm != current_board_file:
                logger.info(f"boardPath differs from current board — reloading: {board_path}")
                try:
                    self.board = pcbnew.LoadBoard(board_path)
                    self._update_command_handlers()
                    logger.info("Board reloaded from boardPath")
                except Exception as e:
                    logger.error(f"Failed to reload board from boardPath: {e}")
                    return {
                        "success": False,
                        "message": f"Could not load board from boardPath: {board_path}",
                        "errorDetails": str(e),
                    }

            project_path = Path(board_path).parent
            if project_path != getattr(self, "_current_project_path", None):
                self._current_project_path = project_path
                local_lib = FootprintLibraryManager(project_path=project_path)
                self.component_commands = ComponentCommands(self.board, local_lib)
                logger.info(f"Reloaded FootprintLibraryManager with project_path={project_path}")

        return self.component_commands.place_component(params)

    def _handle_add_schematic_component(self, params):
        return self.schematic_handlers.add_schematic_component(params)

    def _handle_delete_schematic_component(self, params):
        return self.schematic_handlers.delete_schematic_component(params)

    def _handle_edit_schematic_component(self, params):
        return self.schematic_handlers.edit_schematic_component(params)

    def _handle_get_schematic_component(self, params):
        return self.schematic_handlers.get_schematic_component(params)

    def _handle_add_schematic_wire(self, params):
        return self.schematic_handlers.add_schematic_wire(params)

    def _handle_add_schematic_junction(self, params):
        return self.schematic_handlers.add_schematic_junction(params)

    def _handle_list_schematic_libraries(self, params):
        return self.schematic_handlers.list_schematic_libraries(params)

    def _handle_find_unconnected_pins(self, params):
        return self.schematic_handlers.find_unconnected_pins(params)

    def _handle_check_wire_collisions(self, params):
        return self.schematic_handlers.check_wire_collisions(params)

    def _handle_create_footprint(self, params):
        return self.footprint_handlers.create_footprint(params)

    def _handle_edit_footprint_pad(self, params):
        return self.footprint_handlers.edit_footprint_pad(params)

    def _handle_list_footprint_libraries(self, params):
        return self.footprint_handlers.list_footprint_libraries(params)

    def _handle_register_footprint_library(self, params):
        return self.footprint_handlers.register_footprint_library(params)

    def _handle_create_symbol(self, params):
        return self.symbol_handlers.create_symbol(params)

    def _handle_delete_symbol(self, params):
        return self.symbol_handlers.delete_symbol(params)

    def _handle_list_symbols_in_library(self, params):
        return self.symbol_handlers.list_symbols_in_library(params)

    def _handle_register_symbol_library(self, params):
        return self.symbol_handlers.register_symbol_library(params)

    def _handle_export_schematic_pdf(self, params):
        return self.schematic_handlers.export_schematic_pdf(params)

    def _handle_add_schematic_net_label(self, params):
        return self.schematic_handlers.add_schematic_net_label(params)

    def _handle_connect_to_net(self, params):
        return self.schematic_handlers.connect_to_net(params)

    def _handle_connect_passthrough(self, params):
        return self.schematic_handlers.connect_passthrough(params)

    def _handle_get_schematic_pin_locations(self, params):
        return self.schematic_handlers.get_schematic_pin_locations(params)

    def _handle_get_schematic_view(self, params):
        return self.schematic_handlers.get_schematic_view(params)

    def _handle_list_schematic_components(self, params):
        return self.schematic_handlers.list_schematic_components(params)

    def _handle_list_schematic_nets(self, params):
        return self.schematic_handlers.list_schematic_nets(params)

    def _handle_list_schematic_wires(self, params):
        return self.schematic_handlers.list_schematic_wires(params)

    def _handle_list_schematic_labels(self, params):
        return self.schematic_handlers.list_schematic_labels(params)

    def _handle_move_schematic_component(self, params):
        return self.schematic_handlers.move_schematic_component(params)

    def _handle_rotate_schematic_component(self, params):
        return self.schematic_handlers.rotate_schematic_component(params)

    def _handle_annotate_schematic(self, params):
        return self.schematic_handlers.annotate_schematic(params)

    def _handle_delete_schematic_wire(self, params):
        return self.schematic_handlers.delete_schematic_wire(params)

    def _handle_delete_schematic_net_label(self, params):
        return self.schematic_handlers.delete_schematic_net_label(params)

    def _handle_export_schematic_svg(self, params):
        return self.schematic_handlers.export_schematic_svg(params)

    def _handle_get_net_connections(self, params):
        return self.schematic_handlers.get_net_connections(params)

    def _handle_get_wire_connections(self, params):
        return self.schematic_handlers.get_wire_connections(params)

    def _handle_run_erc(self, params):
        return self.schematic_handlers.run_erc(params)

    def _handle_generate_netlist(self, params):
        return self.schematic_handlers.generate_netlist(params)

    def _should_auto_place_missing_footprints(
        self, params: Dict[str, Any], existing_footprint_count: int
    ) -> bool:
        """Default to auto-placement only for blank boards unless explicitly overridden."""
        if "autoPlaceMissingFootprints" in params and params.get("autoPlaceMissingFootprints") is not None:
            return bool(params.get("autoPlaceMissingFootprints"))
        return existing_footprint_count == 0

    def _collect_schematic_footprint_components(self, schematic) -> List[Dict[str, str]]:
        """Extract placeable schematic components with stable ordering."""
        components: List[Dict[str, str]] = []
        for symbol in getattr(schematic, "symbol", []):
            properties = getattr(symbol, "property", None)
            if not properties or not hasattr(properties, "Reference"):
                continue

            reference = properties.Reference.value
            if not reference or reference.startswith("_TEMPLATE"):
                continue

            components.append(
                {
                    "reference": reference,
                    "value": properties.Value.value if hasattr(properties, "Value") else "",
                    "footprint": properties.Footprint.value if hasattr(properties, "Footprint") else "",
                }
            )

        components.sort(key=lambda item: item["reference"])
        return components

    def _build_auto_place_plan(
        self,
        schematic_components: List[Dict[str, str]],
        existing_refs: set,
        params: Dict[str, Any],
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Build a deterministic grid placement plan for schematic components missing on the PCB."""
        start_x = float(params.get("placementStartXmm", 25.0))
        start_y = float(params.get("placementStartYmm", 25.0))
        pitch_x = float(params.get("placementPitchXmm", 20.0))
        pitch_y = float(params.get("placementPitchYmm", 15.0))
        columns = max(1, int(params.get("placementColumns", 6)))

        placements: List[Dict[str, Any]] = []
        skipped: List[Dict[str, str]] = []

        for component in schematic_components:
            reference = component["reference"]
            if reference in existing_refs:
                continue

            footprint = component.get("footprint", "")
            if not footprint:
                skipped.append(
                    {
                        "reference": reference,
                        "reason": "missing Footprint property in schematic",
                    }
                )
                continue

            slot = len(placements)
            column = slot % columns
            row = slot // columns
            placements.append(
                {
                    "reference": reference,
                    "value": component.get("value", ""),
                    "footprint": footprint,
                    "position": {
                        "x": round(start_x + column * pitch_x, 4),
                        "y": round(start_y + row * pitch_y, 4),
                        "unit": "mm",
                    },
                    "rotation": 0,
                    "layer": "F.Cu",
                }
            )

        return {"placements": placements, "skipped": skipped}

    def _auto_place_missing_footprints(self, schematic, board_path: str, board, params: Dict[str, Any]):
        """Place schematic footprints that are missing from the PCB so sync can assign nets."""
        existing_refs = {fp.GetReference() for fp in board.GetFootprints()}
        schematic_components = self._collect_schematic_footprint_components(schematic)
        plan = self._build_auto_place_plan(schematic_components, existing_refs, params)

        placed: List[Dict[str, Any]] = []
        errors: List[Dict[str, str]] = []

        for placement in plan["placements"]:
            result = self._handle_place_component(
                {
                    "boardPath": board_path,
                    "componentId": placement["footprint"],
                    "footprint": placement["footprint"],
                    "reference": placement["reference"],
                    "value": placement["value"],
                    "position": placement["position"],
                    "rotation": placement["rotation"],
                    "layer": placement["layer"],
                }
            )
            if result.get("success"):
                placed.append(placement)
            else:
                errors.append(
                    {
                        "reference": placement["reference"],
                        "footprint": placement["footprint"],
                        "message": result.get("errorDetails") or result.get("message", "Unknown error"),
                    }
                )

        return {
            "placed": placed,
            "skipped": plan["skipped"],
            "errors": errors,
        }

    def _handle_sync_schematic_to_board(self, params):
        """Sync schematic netlist to PCB board (equivalent to KiCAD F8 'Update PCB from Schematic').
        Reads net connections from the schematic and assigns them to the matching pads in the PCB.
        """
        logger.info("Syncing schematic to board")
        try:
            from pathlib import Path

            schematic_path = params.get("schematicPath")
            board_path = params.get("boardPath")

            # Determine board to work with
            board = None
            if board_path:
                board = pcbnew.LoadBoard(board_path)
            elif self.board:
                board = self.board
                board_path = board.GetFileName() if not board_path else board_path
            else:
                return {
                    "success": False,
                    "message": "No board loaded. Use open_project first or provide boardPath.",
                }

            if not board_path:
                board_path = board.GetFileName()

            self.board = board
            self._update_command_handlers()

            # Determine schematic path if not provided
            if not schematic_path:
                sch = Path(board_path).with_suffix(".kicad_sch")
                if sch.exists():
                    schematic_path = str(sch)
                else:
                    project_dir = Path(board_path).parent
                    sch_files = list(project_dir.glob("*.kicad_sch"))
                    if sch_files:
                        schematic_path = str(sch_files[0])

            if not schematic_path or not Path(schematic_path).exists():
                return {
                    "success": False,
                    "message": f"Schematic not found. Provide schematicPath. Tried: {schematic_path}",
                }

            # Generate netlist from schematic
            schematic = SchematicManager.load_schematic(schematic_path)
            if not schematic:
                return {"success": False, "message": "Failed to load schematic"}

            netlist = ConnectionManager.generate_netlist(schematic, schematic_path=schematic_path)
            if not netlist.get("nets"):
                fallback = self._handle_list_schematic_nets({"schematicPath": schematic_path})
                if fallback.get("success"):
                    netlist["nets"] = fallback.get("nets", [])

            existing_footprint_count = sum(1 for _ in board.GetFootprints())
            auto_place_enabled = self._should_auto_place_missing_footprints(
                params, existing_footprint_count
            )
            auto_place_result = {"placed": [], "skipped": [], "errors": []}
            if auto_place_enabled:
                auto_place_result = self._auto_place_missing_footprints(
                    schematic, board_path, board, params
                )

            # Build (reference, pad_number) -> net_name map
            pad_net_map = {}  # {(ref, pin_str): net_name}
            net_names = set()
            for net_entry in netlist.get("nets", []):
                net_name = net_entry["name"]
                net_names.add(net_name)
                for conn in net_entry.get("connections", []):
                    ref = conn.get("component", "")
                    pin = str(conn.get("pin", ""))
                    if ref and pin and pin != "unknown":
                        pad_net_map[(ref, pin)] = net_name

            # Add all nets to board
            netinfo = board.GetNetInfo()
            nets_by_name = netinfo.NetsByName()
            added_nets = []
            for net_name in net_names:
                if not nets_by_name.has_key(net_name):
                    net_item = pcbnew.NETINFO_ITEM(board, net_name)
                    board.Add(net_item)
                    added_nets.append(net_name)

            # Refresh nets map after additions
            netinfo = board.GetNetInfo()
            nets_by_name = netinfo.NetsByName()

            # Assign nets to pads
            assigned_pads = 0
            unmatched = []
            for fp in board.GetFootprints():
                ref = fp.GetReference()
                for pad in fp.Pads():
                    pad_num = pad.GetNumber()
                    key = (ref, str(pad_num))
                    if key in pad_net_map:
                        net_name = pad_net_map[key]
                        if nets_by_name.has_key(net_name):
                            pad.SetNet(nets_by_name[net_name])
                            assigned_pads += 1
                    else:
                        unmatched.append(f"{ref}/{pad_num}")

            board.Save(board_path)

            logger.info(
                "sync_schematic_to_board: %s nets added, %s pads assigned, %s footprints auto-placed",
                len(added_nets),
                assigned_pads,
                len(auto_place_result["placed"]),
            )
            return {
                "success": True,
                "message": (
                    "PCB nets synced from schematic: "
                    f"{len(added_nets)} nets added, "
                    f"{assigned_pads} pads assigned, "
                    f"{len(auto_place_result['placed'])} footprints auto-placed"
                ),
                "nets_added": added_nets,
                "nets_total": len(net_names),
                "pads_assigned": assigned_pads,
                "unmatched_pads_sample": unmatched[:10],
                "auto_place_triggered": auto_place_enabled,
                "auto_placed_references": [item["reference"] for item in auto_place_result["placed"]],
                "auto_place_skipped": auto_place_result["skipped"],
                "auto_place_errors": auto_place_result["errors"],
            }

        except Exception as e:
            logger.error(f"Error in sync_schematic_to_board: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_get_schematic_view_region(self, params):
        return self.schematic_handlers.get_schematic_view_region(params)

    def _handle_find_overlapping_elements(self, params):
        return self.schematic_handlers.find_overlapping_elements(params)

    def _handle_get_elements_in_region(self, params):
        return self.schematic_handlers.get_elements_in_region(params)

    def _handle_find_wires_crossing_symbols(self, params):
        return self.schematic_handlers.find_wires_crossing_symbols(params)

    def _handle_import_svg_logo(self, params):
        result = self.misc_handlers.import_svg_logo(params, board=self.board)
        if result.get("success") and self.board:
            self._update_command_handlers()
        return result

    def _handle_snapshot_project(self, params):
        return self.misc_handlers.snapshot_project(params, board=self.board)

    def _handle_check_kicad_ui(self, params):
        return self.misc_handlers.check_kicad_ui(params)

    def _handle_launch_kicad_ui(self, params):
        return self.misc_handlers.launch_kicad_ui(params)

    def _handle_refill_zones(self, params):
        result = self.misc_handlers.refill_zones(params, board=self.board)
        if result.get("success") and result.get("_board_reloaded"):
            import pcbnew
            board_path = self.board.GetFileName() if self.board else None
            if board_path:
                self.board = pcbnew.LoadBoard(board_path)
                self._update_command_handlers()
        return result

    def _ipc_route_trace(self, params):
        return self.ipc_handlers.ipc_route_trace(params)

    def _ipc_add_via(self, params):
        return self.ipc_handlers.ipc_add_via(params)

    def _ipc_add_net(self, params):
        return self.ipc_handlers.ipc_add_net(params)

    def _ipc_add_copper_pour(self, params):
        return self.ipc_handlers.ipc_add_copper_pour(params)

    def _ipc_refill_zones(self, params):
        return self.ipc_handlers.ipc_refill_zones(params)

    def _ipc_add_text(self, params):
        return self.ipc_handlers.ipc_add_text(params)

    def _ipc_set_board_size(self, params):
        return self.ipc_handlers.ipc_set_board_size(params)

    def _ipc_get_board_info(self, params):
        return self.ipc_handlers.ipc_get_board_info(params)

    def _ipc_place_component(self, params):
        return self.ipc_handlers.ipc_place_component(params)

    def _ipc_move_component(self, params):
        return self.ipc_handlers.ipc_move_component(params)

    def _ipc_delete_component(self, params):
        return self.ipc_handlers.ipc_delete_component(params)

    def _ipc_get_component_list(self, params):
        return self.ipc_handlers.ipc_get_component_list(params)

    def _ipc_save_project(self, params):
        return self.ipc_handlers.ipc_save_project(params)

    def _ipc_delete_trace(self, params):
        return self.ipc_handlers.ipc_delete_trace(params)

    def _ipc_get_nets_list(self, params):
        return self.ipc_handlers.ipc_get_nets_list(params)

    def _ipc_add_board_outline(self, params):
        return self.ipc_handlers.ipc_add_board_outline(params)

    def _ipc_add_mounting_hole(self, params):
        return self.ipc_handlers.ipc_add_mounting_hole(params)

    def _ipc_get_layer_list(self, params):
        return self.ipc_handlers.ipc_get_layer_list(params)

    def _ipc_rotate_component(self, params):
        return self.ipc_handlers.ipc_rotate_component(params)

    def _ipc_get_component_properties(self, params):
        return self.ipc_handlers.ipc_get_component_properties(params)

    def _handle_get_backend_info(self, params):
        return self.ipc_handlers.get_backend_info(params)

    def _handle_ipc_add_track(self, params):
        return self.ipc_handlers.handle_ipc_add_track(params)

    def _handle_ipc_add_via(self, params):
        return self.ipc_handlers.handle_ipc_add_via(params)

    def _handle_ipc_add_text(self, params):
        return self.ipc_handlers.handle_ipc_add_text(params)

    def _handle_ipc_list_components(self, params):
        return self.ipc_handlers.handle_ipc_list_components(params)

    def _handle_ipc_get_tracks(self, params):
        return self.ipc_handlers.handle_ipc_get_tracks(params)

    def _handle_ipc_get_vias(self, params):
        return self.ipc_handlers.handle_ipc_get_vias(params)

    def _handle_ipc_save_board(self, params):
        return self.ipc_handlers.handle_ipc_save_board(params)

    def _handle_download_jlcpcb_database(self, params):
        return self.jlcpcb_handlers.download_jlcpcb_database(params)

    def _handle_search_jlcpcb_parts(self, params):
        return self.jlcpcb_handlers.search_jlcpcb_parts(params)

    def _handle_get_jlcpcb_part(self, params):
        return self.jlcpcb_handlers.get_jlcpcb_part(params)

    def _handle_get_jlcpcb_database_stats(self, params):
        return self.jlcpcb_handlers.get_jlcpcb_database_stats(params)

    def _handle_suggest_jlcpcb_alternatives(self, params):
        return self.jlcpcb_handlers.suggest_jlcpcb_alternatives(params)

    def _handle_enrich_datasheets(self, params):
        return self.jlcpcb_handlers.enrich_datasheets(params)

    def _handle_get_datasheet_url(self, params):
        return self.jlcpcb_handlers.get_datasheet_url(params)

def _write_response(response_fd, response):
    """Write a JSON response to the original stdout fd.

    All response output goes through this function so that stray C-level
    writes from pcbnew (warnings, diagnostics) never corrupt the JSON
    framing seen by the TypeScript host.
    """
    payload = json.dumps(response) + "\n"
    os.write(response_fd, payload.encode("utf-8"))


def main():
    """Main entry point"""
    # --- Redirect stdout so pcbnew C++ noise never reaches the TS host ---
    # Save the real stdout fd for our exclusive JSON response channel.
    _response_fd = os.dup(1)
    # Point fd 1 (C-level stdout) at stderr so that any printf / std::cout
    # output from pcbnew or other C extensions is visible in logs but does
    # NOT corrupt the JSON stream the TypeScript side is parsing.
    os.dup2(2, 1)
    # Also redirect Python-level stdout to stderr for the same reason.
    sys.stdout = sys.stderr

    logger.info("Starting KiCAD interface...")
    interface = KiCADInterface()

    try:
        logger.info("Processing commands from stdin...")
        # Process commands from stdin
        for line in sys.stdin:
            try:
                # Parse command
                logger.debug(f"Received input: {line.strip()}")
                command_data = json.loads(line)

                # Check if this is JSON-RPC 2.0 format
                if "jsonrpc" in command_data and command_data["jsonrpc"] == "2.0":
                    logger.info("Detected JSON-RPC 2.0 format message")
                    method = command_data.get("method")
                    params = command_data.get("params", {})
                    request_id = command_data.get("id")

                    # Handle MCP protocol methods
                    if method == "initialize":
                        logger.info("Handling MCP initialize")
                        response = {
                            "jsonrpc": "2.0",
                            "id": request_id,
                            "result": {
                                "protocolVersion": "2025-06-18",
                                "capabilities": {
                                    "tools": {"listChanged": True},
                                    "resources": {
                                        "subscribe": False,
                                        "listChanged": True,
                                    },
                                },
                                "serverInfo": {
                                    "name": "kicad-mcp-server",
                                    "title": "KiCAD PCB Design Assistant",
                                    "version": "2.1.0-alpha",
                                },
                                "instructions": "AI-assisted PCB design with KiCAD. Use tools to create projects, design boards, place components, route traces, and export manufacturing files.",
                            },
                        }
                    elif method == "tools/list":
                        logger.info("Handling MCP tools/list")
                        # Return list of available tools with proper schemas
                        tools = []
                        for cmd_name in interface.command_routes.keys():
                            # Get schema from TOOL_SCHEMAS if available
                            if cmd_name in TOOL_SCHEMAS:
                                tool_def = TOOL_SCHEMAS[cmd_name].copy()
                                tools.append(tool_def)
                            else:
                                # Fallback for tools without schemas
                                logger.warning(f"No schema defined for tool: {cmd_name}")
                                tools.append(
                                    {
                                        "name": cmd_name,
                                        "description": f"KiCAD command: {cmd_name}",
                                        "inputSchema": {
                                            "type": "object",
                                            "properties": {},
                                        },
                                    }
                                )

                        logger.info(f"Returning {len(tools)} tools")
                        response = {
                            "jsonrpc": "2.0",
                            "id": request_id,
                            "result": {"tools": tools},
                        }
                    elif method == "tools/call":
                        logger.info("Handling MCP tools/call")
                        tool_name = params.get("name")
                        tool_params = params.get("arguments", {})

                        # Execute the command
                        result = interface.handle_command(tool_name, tool_params)

                        response = {
                            "jsonrpc": "2.0",
                            "id": request_id,
                            "result": {"content": [{"type": "text", "text": json.dumps(result)}]},
                        }
                    elif method == "resources/list":
                        logger.info("Handling MCP resources/list")
                        # Return list of available resources
                        response = {
                            "jsonrpc": "2.0",
                            "id": request_id,
                            "result": {"resources": RESOURCE_DEFINITIONS},
                        }
                    elif method == "resources/read":
                        logger.info("Handling MCP resources/read")
                        resource_uri = params.get("uri")

                        if not resource_uri:
                            response = {
                                "jsonrpc": "2.0",
                                "id": request_id,
                                "error": {
                                    "code": -32602,
                                    "message": "Missing required parameter: uri",
                                },
                            }
                        else:
                            # Read the resource
                            resource_data = handle_resource_read(resource_uri, interface)

                            response = {
                                "jsonrpc": "2.0",
                                "id": request_id,
                                "result": resource_data,
                            }
                    else:
                        logger.error(f"Unknown JSON-RPC method: {method}")
                        response = {
                            "jsonrpc": "2.0",
                            "id": request_id,
                            "error": {
                                "code": -32601,
                                "message": f"Method not found: {method}",
                            },
                        }
                else:
                    # Handle legacy custom format
                    logger.info("Detected custom format message")
                    command = command_data.get("command")
                    params = command_data.get("params", {})

                    if not command:
                        logger.error("Missing command field")
                        response = {
                            "success": False,
                            "message": "Missing command",
                            "errorDetails": "The command field is required",
                        }
                    else:
                        # Handle command
                        response = interface.handle_command(command, params)

                # Send response via the clean fd (immune to pcbnew stdout noise)
                logger.debug(f"Sending response: {response}")
                _write_response(_response_fd, response)

            except json.JSONDecodeError as e:
                logger.error(f"Invalid JSON input: {str(e)}")
                response = {
                    "success": False,
                    "message": "Invalid JSON input",
                    "errorDetails": str(e),
                }
                _write_response(_response_fd, response)

    except KeyboardInterrupt:
        logger.info("KiCAD interface stopped")
        sys.exit(0)

    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}\n{traceback.format_exc()}")
        sys.exit(1)


if __name__ == "__main__":
    main()
