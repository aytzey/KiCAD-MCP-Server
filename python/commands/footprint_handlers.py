import logging

from commands.footprint import FootprintCreator

logger = logging.getLogger("kicad_interface")


class FootprintHandlers:
    def __init__(self):
        pass

    def create_footprint(self, params):
        """Create a new .kicad_mod footprint file in a .pretty library."""
        logger.info(f"create_footprint: {params.get('name')} in {params.get('libraryPath')}")
        try:
            creator = FootprintCreator()
            return creator.create_footprint(
                library_path=params.get("libraryPath", ""),
                name=params.get("name", ""),
                description=params.get("description", ""),
                tags=params.get("tags", ""),
                pads=params.get("pads", []),
                courtyard=params.get("courtyard"),
                silkscreen=params.get("silkscreen"),
                fab_layer=params.get("fabLayer"),
                ref_position=params.get("refPosition"),
                value_position=params.get("valuePosition"),
                overwrite=params.get("overwrite", False),
            )
        except Exception as e:
            logger.error(f"create_footprint error: {e}")
            return {"success": False, "error": str(e)}

    def edit_footprint_pad(self, params):
        """Edit an existing pad in a .kicad_mod file."""
        logger.info(
            f"edit_footprint_pad: pad {params.get('padNumber')} in {params.get('footprintPath')}"
        )
        try:
            creator = FootprintCreator()
            return creator.edit_footprint_pad(
                footprint_path=params.get("footprintPath", ""),
                pad_number=str(params.get("padNumber", "1")),
                size=params.get("size"),
                at=params.get("at"),
                drill=params.get("drill"),
                shape=params.get("shape"),
            )
        except Exception as e:
            logger.error(f"edit_footprint_pad error: {e}")
            return {"success": False, "error": str(e)}

    def list_footprint_libraries(self, params):
        """List .pretty footprint libraries and their contents."""
        logger.info("list_footprint_libraries")
        try:
            creator = FootprintCreator()
            return creator.list_footprint_libraries(search_paths=params.get("searchPaths"))
        except Exception as e:
            logger.error(f"list_footprint_libraries error: {e}")
            return {"success": False, "error": str(e)}

    def register_footprint_library(self, params):
        """Register a .pretty library in KiCAD's fp-lib-table."""
        logger.info(f"register_footprint_library: {params.get('libraryPath')}")
        try:
            creator = FootprintCreator()
            return creator.register_footprint_library(
                library_path=params.get("libraryPath", ""),
                library_name=params.get("libraryName"),
                description=params.get("description", ""),
                scope=params.get("scope", "project"),
                project_path=params.get("projectPath"),
            )
        except Exception as e:
            logger.error(f"register_footprint_library error: {e}")
            return {"success": False, "error": str(e)}
