"""
Wave - Database Utilities
Helpers for safe BSON ObjectId conversions and MongoDB query helpers.
"""

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import HTTPException, status


def to_object_id(id_str: str, resource_name: str = "Resource") -> ObjectId:
    """
    Safely convert a string to a BSON ObjectId.
    Raises HTTP 400 Bad Request if the ID format is invalid.
    """
    if not id_str or not ObjectId.is_valid(id_str):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid {resource_name} ID format",
        )
    try:
        return ObjectId(id_str)
    except (InvalidId, TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid {resource_name} ID format",
        )

