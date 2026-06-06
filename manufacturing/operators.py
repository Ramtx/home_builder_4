"""Blender operators for manufacturing exports."""

from __future__ import annotations

from pathlib import Path

import bpy

from .cutlist import export_cut_list
from .extractor import extract_scene
from .model import GrainDirection
from .nesting import (
    NestingConfig,
    NestingStrategy,
    RotationPolicy,
    StockSpec,
    export_result,
    optimize,
)


METRES_TO_MM = 1000.0


class HOME_BUILDER_OT_export_manufacturing_cut_list(bpy.types.Operator):
    bl_idname = "home_builder.export_manufacturing_cut_list"
    bl_label = "Export Cut List"
    bl_description = "Export cut-list, material, hardware, HTML, and validation reports"
    bl_options = {"REGISTER"}

    directory: bpy.props.StringProperty(
        name="Export Directory",
        description="Directory that will receive the manufacturing report bundle",
        subtype="DIR_PATH",
    )

    def invoke(self, context, event):
        if not self.directory:
            if bpy.data.filepath:
                blend_path = Path(bpy.data.filepath)
                default_path = blend_path.parent / f"{blend_path.stem}_manufacturing"
            else:
                default_path = Path(bpy.path.abspath("//")) / "manufacturing"
            self.directory = str(default_path)
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        if not self.directory.strip():
            self.report({"ERROR"}, "Select an export directory")
            return {"CANCELLED"}

        destination = Path(bpy.path.abspath(self.directory))
        try:
            project = extract_scene(context.scene)
            exported = export_cut_list(project, destination)
        except Exception as error:  # Blender operators must return a UI result.
            self.report({"ERROR"}, f"Cut-list export failed: {error}")
            return {"CANCELLED"}

        self.report(
            {"INFO"},
            f"Exported {len(exported.paths())} manufacturing reports to {destination}",
        )
        return {"FINISHED"}


class MANUFACTURING_OT_export_nesting(bpy.types.Operator):
    bl_idname = "manufacturing.export_nesting"
    bl_label = "Export Sheet Nesting"
    bl_description = "Extract the manufacturing project and export JSON, CSV, and SVG nests"

    def execute(self, context):
        settings = context.scene.manufacturing_nesting
        if not settings.export_directory.strip():
            self.report({"ERROR"}, "Select an export directory")
            return {"CANCELLED"}
        destination = Path(bpy.path.abspath(settings.export_directory))

        stock = StockSpec(
            id="ui-stock",
            name="Configured stock",
            width_mm=settings.stock_width * METRES_TO_MM,
            height_mm=settings.stock_height * METRES_TO_MM,
            quantity=settings.stock_quantity or None,
            is_remnant=settings.stock_is_remnant,
            grain=GrainDirection(settings.stock_grain),
        )
        config = NestingConfig(
            strategy=NestingStrategy(settings.strategy),
            stock=(stock,),
            kerf_mm=settings.kerf * METRES_TO_MM,
            margin_mm=settings.margin * METRES_TO_MM,
            spacing_mm=settings.spacing * METRES_TO_MM,
            rotation_policy=RotationPolicy(settings.rotation_policy),
        )

        try:
            result = optimize(extract_scene(context.scene), config)
            export_result(result, destination)
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            settings.last_summary = f"Export failed: {error}"
            self.report({"ERROR"}, settings.last_summary)
            return {"CANCELLED"}

        settings.last_export_path = str(destination)
        settings.last_summary = (
            f"{result.placed_part_count} placed, "
            f"{len(result.unplaced_parts)} unplaced, "
            f"{len(result.sheets)} sheets"
        )
        level = {"INFO"} if result.is_valid else {"WARNING"}
        self.report(level, settings.last_summary)
        return {"FINISHED"}


classes = (
    HOME_BUILDER_OT_export_manufacturing_cut_list,
    MANUFACTURING_OT_export_nesting,
)

register, unregister = bpy.utils.register_classes_factory(classes)
