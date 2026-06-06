"""Blender properties for manufacturing drawing export."""

import bpy
from bpy.props import BoolProperty, PointerProperty, StringProperty


class ManufacturingSceneProperties(bpy.types.PropertyGroup):
    drawing_output_directory: StringProperty(
        name="Drawing Package",
        description="Directory for the PDF, SVG, and DXF manufacturing drawings",
        subtype="DIR_PATH",
    )
    open_output_directory: BoolProperty(
        name="Open Folder After Export",
        default=False,
    )

    @classmethod
    def register(cls):
        bpy.types.Scene.manufacturing = PointerProperty(type=cls)

    @classmethod
    def unregister(cls):
        del bpy.types.Scene.manufacturing


classes = (ManufacturingSceneProperties,)
register, unregister = bpy.utils.register_classes_factory(classes)
