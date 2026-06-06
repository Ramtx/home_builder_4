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
        box = layout.box()
        box.label(text="Cut List and Hardware", icon="SPREADSHEET")
        row = box.row()
        row.scale_y = 1.2
        row.operator(
            "home_builder.export_manufacturing_cut_list",
            text="Export Manufacturing Reports",
            icon="EXPORT",
        )


classes = (HOME_BUILDER_PT_manufacturing,)

register, unregister = bpy.utils.register_classes_factory(classes)
