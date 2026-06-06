"""Canonical manufacturing data for Home Builder.

The domain and serialization modules intentionally have no Blender dependency.
Blender integration is available from :mod:`manufacturing.extractor`.
"""

from .model import (
    SCHEMA_VERSION,
    Cabinet,
    EdgeBanding,
    Face,
    GrainDirection,
    HardwareItem,
    IssueSeverity,
    MachiningOperation,
    MachiningType,
    ManufacturingProject,
    Material,
    Part,
    PartCategory,
    StockDefinition,
    Transform,
    ValidationIssue,
    stable_id,
)
from .cutlist import (
    CutListReport,
    ExportedCutList,
    build_cut_list,
    export_cut_list,
)


def extract_scene(scene=None):
    """Load the Blender extractor lazily so pure-Python imports stay bpy-free."""
    from .extractor import extract_scene as _extract_scene

    return _extract_scene(scene)


def register():
    """Register Blender integration without adding bpy to pure-Python imports."""
    from . import operators, ui

    operators.register()
    ui.register()


def unregister():
    from . import operators, ui

    ui.unregister()
    operators.unregister()


__all__ = [
    "SCHEMA_VERSION",
    "Cabinet",
    "CutListReport",
    "EdgeBanding",
    "Face",
    "GrainDirection",
    "HardwareItem",
    "IssueSeverity",
    "MachiningOperation",
    "MachiningType",
    "ManufacturingProject",
    "Material",
    "Part",
    "PartCategory",
    "StockDefinition",
    "Transform",
    "ValidationIssue",
    "ExportedCutList",
    "build_cut_list",
    "export_cut_list",
    "extract_scene",
    "register",
    "stable_id",
    "unregister",
]
