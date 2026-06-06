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


def extract_scene(scene=None):
    """Load the Blender extractor lazily so pure-Python imports stay bpy-free."""
    from .extractor import extract_scene as _extract_scene

    return _extract_scene(scene)


__all__ = [
    "SCHEMA_VERSION",
    "Cabinet",
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
    "extract_scene",
    "stable_id",
]
