"""Blender operators for manufacturing package export."""

from __future__ import annotations

from pathlib import Path

import bpy

from .extractor import extract_scene
from .mozaik import export_package, load_profile
from .props import ensure_user_profile


class MANUFACTURING_OT_export_mozaik_package(bpy.types.Operator):
    bl_idname = "manufacturing.export_mozaik_package"
    bl_label = "Export Mozaik-Oriented Package"
    bl_description = (
        "Export neutral DXF, CSV, manifest, and validation files; "
        "this does not create a native Mozaik project"
    )

    def execute(self, context):
        settings = context.scene.manufacturing
        output_value = settings.output_directory.strip()
        if not output_value:
            self.report({"ERROR"}, "Choose a package directory")
            return {"CANCELLED"}

        try:
            output_directory = Path(bpy.path.abspath(output_value))
            profile_value = settings.profile_path.strip()
            profile_path = (
                Path(bpy.path.abspath(profile_value))
                if profile_value
                else ensure_user_profile()
            )
            profile = load_profile(profile_path)
            project = extract_scene(context.scene)
            result = export_package(project, output_directory, profile)
        except (OSError, ValueError, TypeError, KeyError) as error:
            self.report({"ERROR"}, f"Manufacturing export failed: {error}")
            return {"CANCELLED"}

        if not result.ok:
            error_count = sum(
                issue.severity.value == "error" for issue in result.issues
            )
            self.report(
                {"ERROR"},
                f"Package written with {error_count} validation error(s): "
                f"{output_directory}",
            )
            return {"CANCELLED"}

        warning_count = sum(
            issue.severity.value == "warning" for issue in result.issues
        )
        self.report(
            {"INFO"},
            f"Exported {result.panel_count} panel definition(s), "
            f"{warning_count} warning(s): {output_directory}",
        )
        return {"FINISHED"}


register, unregister = bpy.utils.register_classes_factory(
    (MANUFACTURING_OT_export_mozaik_package,)
)
