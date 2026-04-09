"""JLCPCB and datasheet handler methods, extracted from kicad_interface.py."""

import json
import logging
import os
from pathlib import Path

from commands.datasheet_manager import DatasheetManager

logger = logging.getLogger("kicad_interface")


class JLCPCBHandlers:
    """Handler methods for JLCPCB parts database and datasheet operations."""

    def __init__(self, jlcpcb_parts, jlcsearch_client):
        self.jlcpcb_parts = jlcpcb_parts
        self.jlcsearch_client = jlcsearch_client

    def download_jlcpcb_database(self, params):
        """Download JLCPCB parts database from JLCSearch API"""
        try:
            force = params.get("force", False)

            # Check if database exists
            stats = self.jlcpcb_parts.get_database_stats()
            if stats["total_parts"] > 0 and not force:
                return {
                    "success": False,
                    "message": "Database already exists. Use force=true to re-download.",
                    "stats": stats,
                }

            logger.info("Downloading JLCPCB parts database from JLCSearch...")

            # Download parts from JLCSearch public API (no auth required)
            parts = self.jlcsearch_client.download_all_components(
                callback=lambda total, msg: logger.info(f"{msg}")
            )

            # Import into database
            logger.info(f"Importing {len(parts)} parts into database...")
            self.jlcpcb_parts.import_jlcsearch_parts(
                parts, progress_callback=lambda curr, total, msg: logger.info(msg)
            )

            # Get final stats
            stats = self.jlcpcb_parts.get_database_stats()

            # Calculate database size
            db_size_mb = os.path.getsize(self.jlcpcb_parts.db_path) / (1024 * 1024)

            return {
                "success": True,
                "total_parts": stats["total_parts"],
                "basic_parts": stats["basic_parts"],
                "extended_parts": stats["extended_parts"],
                "db_size_mb": round(db_size_mb, 2),
                "db_path": stats["db_path"],
            }

        except Exception as e:
            logger.error(f"Error downloading JLCPCB database: {e}", exc_info=True)
            return {
                "success": False,
                "message": f"Failed to download database: {str(e)}",
            }

    def search_jlcpcb_parts(self, params):
        """Search JLCPCB parts database"""
        try:
            query = params.get("query")
            category = params.get("category")
            package = params.get("package")
            library_type = params.get("library_type", "All")
            manufacturer = params.get("manufacturer")
            in_stock = params.get("in_stock", True)
            limit = params.get("limit", 20)

            # Adjust library_type filter
            if library_type == "All":
                library_type = None

            parts = self.jlcpcb_parts.search_parts(
                query=query,
                category=category,
                package=package,
                library_type=library_type,
                manufacturer=manufacturer,
                in_stock=in_stock,
                limit=limit,
            )

            # Add price breaks and footprints to each part
            for part in parts:
                if part.get("price_json"):
                    try:
                        part["price_breaks"] = json.loads(part["price_json"])
                    except:
                        part["price_breaks"] = []

            return {"success": True, "parts": parts, "count": len(parts)}

        except Exception as e:
            logger.error(f"Error searching JLCPCB parts: {e}", exc_info=True)
            return {"success": False, "message": f"Search failed: {str(e)}"}

    def get_jlcpcb_part(self, params):
        """Get detailed information for a specific JLCPCB part"""
        try:
            lcsc_number = params.get("lcsc_number")
            if not lcsc_number:
                return {"success": False, "message": "Missing lcsc_number parameter"}

            part = self.jlcpcb_parts.get_part_info(lcsc_number)
            if not part:
                return {"success": False, "message": f"Part not found: {lcsc_number}"}

            # Get suggested KiCAD footprints
            footprints = self.jlcpcb_parts.map_package_to_footprint(part.get("package", ""))

            return {"success": True, "part": part, "footprints": footprints}

        except Exception as e:
            logger.error(f"Error getting JLCPCB part: {e}", exc_info=True)
            return {"success": False, "message": f"Failed to get part info: {str(e)}"}

    def get_jlcpcb_database_stats(self, params):
        """Get statistics about JLCPCB database"""
        try:
            stats = self.jlcpcb_parts.get_database_stats()
            return {"success": True, "stats": stats}

        except Exception as e:
            logger.error(f"Error getting database stats: {e}", exc_info=True)
            return {"success": False, "message": f"Failed to get stats: {str(e)}"}

    def suggest_jlcpcb_alternatives(self, params):
        """Suggest alternative JLCPCB parts"""
        try:
            lcsc_number = params.get("lcsc_number")
            limit = params.get("limit", 5)

            if not lcsc_number:
                return {"success": False, "message": "Missing lcsc_number parameter"}

            # Get original part for price comparison
            original_part = self.jlcpcb_parts.get_part_info(lcsc_number)
            reference_price = None
            if original_part and original_part.get("price_breaks"):
                try:
                    reference_price = float(original_part["price_breaks"][0].get("price", 0))
                except:
                    pass

            alternatives = self.jlcpcb_parts.suggest_alternatives(lcsc_number, limit)

            # Add price breaks to alternatives
            for part in alternatives:
                if part.get("price_json"):
                    try:
                        part["price_breaks"] = json.loads(part["price_json"])
                    except:
                        part["price_breaks"] = []

            return {
                "success": True,
                "alternatives": alternatives,
                "reference_price": reference_price,
            }

        except Exception as e:
            logger.error(f"Error suggesting alternatives: {e}", exc_info=True)
            return {
                "success": False,
                "message": f"Failed to suggest alternatives: {str(e)}",
            }

    def enrich_datasheets(self, params):
        """Enrich schematic Datasheet fields from LCSC numbers"""
        try:
            schematic_path = params.get("schematic_path")
            if not schematic_path:
                return {"success": False, "message": "Missing schematic_path parameter"}
            dry_run = params.get("dry_run", False)
            manager = DatasheetManager()
            return manager.enrich_schematic(Path(schematic_path), dry_run=dry_run)
        except Exception as e:
            logger.error(f"Error enriching datasheets: {e}", exc_info=True)
            return {
                "success": False,
                "message": f"Failed to enrich datasheets: {str(e)}",
            }

    def get_datasheet_url(self, params):
        """Return LCSC datasheet and product URLs for a part number"""
        try:
            lcsc = params.get("lcsc", "")
            if not lcsc:
                return {"success": False, "message": "Missing lcsc parameter"}
            manager = DatasheetManager()
            datasheet_url = manager.get_datasheet_url(lcsc)
            product_url = manager.get_product_url(lcsc)
            if not datasheet_url:
                return {"success": False, "message": f"Invalid LCSC number: {lcsc}"}
            norm = manager._normalize_lcsc(lcsc)
            return {
                "success": True,
                "lcsc": norm,
                "datasheet_url": datasheet_url,
                "product_url": product_url,
            }
        except Exception as e:
            logger.error(f"Error getting datasheet URL: {e}", exc_info=True)
            return {
                "success": False,
                "message": f"Failed to get datasheet URL: {str(e)}",
            }
