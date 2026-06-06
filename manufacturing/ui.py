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


class MANUFACTURING_PT_nesting(bpy.types.Panel):
    bl_idname = "MANUFACTURING_PT_nesting"
    bl_label = "Manufacturing"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Home Builder"

    def draw(self, context):
        settings = context.scene.manufacturing_nesting
        layout = self.layout

        box = layout.box()
        box.label(text="Sheet Nesting", icon="MOD_ARRAY")
        box.use_property_split = True
        box.use_property_decorate = False
        box.prop(settings, "strategy")
        box.prop(settings, "rotation_policy")

        stock = box.box()
        stock.label(text="Stock")
        stock.prop(settings, "stock_width")
        stock.prop(settings, "stock_height")
        stock.prop(settings, "stock_quantity")
        stock.prop(settings, "stock_is_remnant")
        stock.prop(settings, "stock_grain")

        cutting = box.box()
        cutting.label(text="Cutting Allowances")
        cutting.prop(settings, "kerf")
        cutting.prop(settings, "margin")
        cutting.prop(settings, "spacing")

        box.prop(settings, "export_directory")
        row = box.row()
        row.scale_y = 1.3
        row.operator("manufacturing.export_nesting", icon="EXPORT")

        if settings.last_summary:
            layout.label(text=settings.last_summary)
        if settings.last_export_path:
            layout.label(text=settings.last_export_path, icon="FILE_FOLDER")


classes = (
    HOME_BUILDER_PT_manufacturing,
    MANUFACTURING_PT_nesting,
)

register, unregister = bpy.utils.register_classes_factory(classes)
