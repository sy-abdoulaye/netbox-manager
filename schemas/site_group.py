"""Pydantic schema for NetBox Site Group validation."""

from typing import Optional
from pydantic import BaseModel, ConfigDict, Field

class SiteGroupCreate(BaseModel):
    """Schema for creating/updating a site group in NetBox."""

    name: str = Field(..., description="Site group name")
    slug: str = Field(..., description="URL-friendly slug")

    # Optional fields
    parent: Optional[str] = Field(None, description="Parent site group slug")
    description: Optional[str] = Field(None, description="Description")
    model_config = ConfigDict(extra='allow')