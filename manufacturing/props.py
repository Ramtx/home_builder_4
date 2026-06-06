"""Blender properties for manufacturing exports."""

from __future__ import annotations

from pathlib import Path
import shutil

import bpy
from bpy.props import PointerProperty, StringProperty
from bpy.types import PropertyGroup

from .mozaik import DEFAULT_PROFILE_PATH


def ensure_user_profile() -> Path:
    config_directory = Path(
        bpy.utils.user_resource("CONFIG", path="home_builder_4", create=True)
    )
    profile_path = config_directory / "mozaik-profile.json"
    if not profile_path.exists():
        shutil.copyfile(DEFAULT_PROFILE_PATH, profile_path)
    return profile_path


class ManufacturingSceneProperties(PropertyGroup):
    output_directory: StringProperty(
        name="Package Directory",
        description="Directory for the complete neutral manufacturing package",
        default="//manufacturing/mozaik-package",
        subtype="DIR_PATH",
    )
    profile_path: StringProperty(
        name="Mozaik Export Profile",
        description="Editable JSON material, thickness, output, and DXF layer mappings",
        subtype="FILE_PATH",
    )

    @classmethod
    def register(cls):
        bpy.types.Scene.manufacturing = PointerProperty(
            name="Manufacturing",
            description="Manufacturing export settings",
            type=cls,
        )

    @classmethod
    def unregister(cls):
        if hasattr(bpy.types.Scene, "manufacturing"):
            del bpy.types.Scene.manufacturing


_register_classes, _unregister_classes = bpy.utils.register_classes_factory(
    (ManufacturingSceneProperties,)
)


def register():
    _register_classes()
    profile_path = str(ensure_user_profile())
    for scene in bpy.data.scenes:
        if not scene.manufacturing.profile_path:
            scene.manufacturing.profile_path = profile_path


def unregister():
    _unregister_classes()
