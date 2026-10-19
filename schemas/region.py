"""
Pydantic schema for NetBox Region validation.
"""

from typing import Optional
from pydantic import BaseModel, ConfigDict, Field


class RegionCreate(BaseModel):
    """Schema for creating/updating a region in NetBox."""

    name: str = Field(..., description="Region name")
    slug: str = Field(..., description="URL-friendly slug")

    # Optional fields
    parent: Optional[str] = Field(
        None, description="Parent region slug"
    )
    description: Optional[str] = Field(
        None, description="Region description"
    )

    model_config = ConfigDict(extra='allow')