"""Manufacturing controls in the Home Builder sidebar."""

import bpy


class HOME_BUILDER_PT_manufacturing(bpy.types.Panel):
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Home Builder"
    bl_label = "Manufacturing"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        settings = context.scene.manufacturing
        layout.prop(settings, "drawing_output_directory")
        row = layout.row(align=True)
        row.scale_y = 1.2
        row.operator("manufacturing.export_drawings", icon="EXPORT")
        row.operator(
            "manufacturing.open_drawings_folder",
            text="",
            icon="FILE_FOLDER",
        )
        layout.prop(settings, "open_output_directory")
        layout.label(
            text="Creates an indexed PDF plus panel SVG and DXF files.",
            icon="INFO",
        )


classes = (HOME_BUILDER_PT_manufacturing,)
register, unregister = bpy.utils.register_classes_factory(classes)
