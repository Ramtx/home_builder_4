"""Manufacturing export panel."""

import bpy


class VIEW3D_PT_home_builder_manufacturing(bpy.types.Panel):
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Home Builder"
    bl_label = "Manufacturing"

    def draw(self, context):
        layout = self.layout
        settings = context.scene.manufacturing

        notice = layout.box()
        notice.label(text="Neutral interchange package", icon="INFO")
        notice.label(text="Does not create a native .moz project")

        layout.prop(settings, "output_directory")
        layout.prop(settings, "profile_path")
        row = layout.row()
        row.scale_y = 1.4
        row.operator(
            "manufacturing.export_mozaik_package",
            text="Export Complete Package",
            icon="EXPORT",
        )


register, unregister = bpy.utils.register_classes_factory(
    (VIEW3D_PT_home_builder_manufacturing,)
)
