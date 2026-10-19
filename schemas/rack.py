from typing import Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator


class RackCreate(BaseModel):
    """Schema for creating/updating a rack in NetBox."""

    name: str = Field(..., description="Rack name/identifier")
    site: str = Field(..., description="Site name where rack is located")
    status: str = Field(default="active", description="Rack status")
    tenant: Optional[str] = Field(None, description="Tenant name")

    model_config = ConfigDict(extra='allow')