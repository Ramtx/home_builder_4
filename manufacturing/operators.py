"""Blender operators for manufacturing report export."""

from __future__ import annotations

from pathlib import Path

import bpy

from .cutlist import export_cut_list
from .extractor import extract_scene


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


classes = (HOME_BUILDER_OT_export_manufacturing_cut_list,)

register, unregister = bpy.utils.register_classes_factory(classes)
