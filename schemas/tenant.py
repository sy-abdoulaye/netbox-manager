"""
Pydantic schema for NetBox Tenant validation.
"""

from typing import Optional
from pydantic import BaseModel, ConfigDict, Field


class TenantCreate(BaseModel):
    """Schema for creating/updating a tenant in NetBox."""

    name: str = Field(..., description="Tenant name")
    slug: str = Field(..., description="URL-friendly slug")

    # Optional fields
    group: Optional[str] = Field(
        None, description="Tenant group slug"
    )
    description: Optional[str] = Field(
        None, description="Tenant description"
    )
    comments: Optional[str] = Field(
        None, description="Additional comments"
    )
    model_config = ConfigDict(extra='allow')