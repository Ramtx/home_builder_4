"""Blender properties for manufacturing nesting exports."""

import bpy


class ManufacturingNestingProperties(bpy.types.PropertyGroup):
    strategy: bpy.props.EnumProperty(
        name="Strategy",
        items=(
            (
                "rectangular_guillotine",
                "Rectangular Guillotine",
                "Panel-saw friendly rectangular placement",
            ),
            (
                "polygon",
                "Polygon",
                "Outline-aware placement for shaped panels",
            ),
        ),
        default="rectangular_guillotine",
    )
    stock_width: bpy.props.FloatProperty(
        name="Stock Length",
        subtype="DISTANCE",
        unit="LENGTH",
        default=2.44,
        min=0.001,
    )
    stock_height: bpy.props.FloatProperty(
        name="Stock Width",
        subtype="DISTANCE",
        unit="LENGTH",
        default=1.22,
        min=0.001,
    )
    stock_quantity: bpy.props.IntProperty(
        name="Stock Quantity",
        description="Zero allows as many new sheets as required",
        default=0,
        min=0,
    )
    stock_is_remnant: bpy.props.BoolProperty(
        name="Stock Is Remnant",
        default=False,
    )
    stock_grain: bpy.props.EnumProperty(
        name="Stock Grain",
        items=(
            ("none", "None", "Stock has no directional grain"),
            ("length", "Length", "Grain follows the stock length"),
            ("width", "Width", "Grain follows the stock width"),
        ),
        default="none",
    )
    rotation_policy: bpy.props.EnumProperty(
        name="Rotation",
        items=(
            (
                "respect_part",
                "Respect Part Settings",
                "Allow 90 degree rotation only when the part and grain permit it",
            ),
            ("never", "Never", "Do not rotate parts"),
        ),
        default="respect_part",
    )
    kerf: bpy.props.FloatProperty(
        name="Kerf",
        subtype="DISTANCE",
        unit="LENGTH",
        default=0.0032,
        min=0.0,
    )
    margin: bpy.props.FloatProperty(
        name="Sheet Margin",
        subtype="DISTANCE",
        unit="LENGTH",
        default=0.01,
        min=0.0,
    )
    spacing: bpy.props.FloatProperty(
        name="Part Spacing",
        subtype="DISTANCE",
        unit="LENGTH",
        default=0.006,
        min=0.0,
    )
    export_directory: bpy.props.StringProperty(
        name="Export Directory",
        subtype="DIR_PATH",
        default="//manufacturing_nesting",
    )
    last_export_path: bpy.props.StringProperty(name="Last Export", default="")
    last_summary: bpy.props.StringProperty(name="Last Result", default="")


classes = (ManufacturingNestingProperties,)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.manufacturing_nesting = bpy.props.PointerProperty(
        type=ManufacturingNestingProperties
    )


def unregister():
    del bpy.types.Scene.manufacturing_nesting
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
