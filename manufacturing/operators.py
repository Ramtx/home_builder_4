"""Blender operators for manufacturing drawing packages."""

import os
from pathlib import Path

import bpy

from .drawings import UnsupportedPanelGeometry, export_drawing_package
from .extractor import extract_scene


def _default_output_directory() -> str:
    if bpy.data.filepath:
        return str(Path(bpy.data.filepath).with_suffix("")) + "_manufacturing"
    return str(Path(bpy.app.tempdir) / "home_builder_manufacturing")


class MANUFACTURING_OT_export_drawings(bpy.types.Operator):
    bl_idname = "manufacturing.export_drawings"
    bl_label = "Export Drawing Package"
    bl_description = "Export an indexed PDF and one SVG and DXF per unique panel"

    directory: bpy.props.StringProperty(
        name="Output Directory",
        subtype="DIR_PATH",
    )

    def invoke(self, context, event):
        settings = context.scene.manufacturing
        self.directory = settings.drawing_output_directory or _default_output_directory()
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        directory = bpy.path.abspath(self.directory or _default_output_directory())
        try:
            package = export_drawing_package(extract_scene(context.scene), directory)
        except (OSError, ValueError, UnsupportedPanelGeometry) as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}

        settings = context.scene.manufacturing
        settings.drawing_output_directory = directory
        self.report(
            {"INFO"},
            (
                f"Exported {len(package.panels)} unique panels "
                f"and {package.page_count} PDF pages"
            ),
        )
        if settings.open_output_directory:
            bpy.ops.wm.path_open(filepath=str(package.output_directory))
        return {"FINISHED"}


class MANUFACTURING_OT_open_drawings_folder(bpy.types.Operator):
    bl_idname = "manufacturing.open_drawings_folder"
    bl_label = "Open Drawing Folder"
    bl_description = "Open the configured manufacturing drawing directory"

    @classmethod
    def poll(cls, context):
        directory = bpy.path.abspath(
            context.scene.manufacturing.drawing_output_directory
        )
        return bool(directory and os.path.isdir(directory))

    def execute(self, context):
        directory = bpy.path.abspath(
            context.scene.manufacturing.drawing_output_directory
        )
        bpy.ops.wm.path_open(filepath=directory)
        return {"FINISHED"}


classes = (
    MANUFACTURING_OT_export_drawings,
    MANUFACTURING_OT_open_drawings_folder,
)
register, unregister = bpy.utils.register_classes_factory(classes)
