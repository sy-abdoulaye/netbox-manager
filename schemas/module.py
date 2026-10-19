from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from typing import Optional, Annotated


class ModuleCreate(BaseModel):
    """Schema for creating/updating a module (installed in a bay) in NetBox."""

    device: str = Field(..., description="Device name where bay is located")
    module_bay: str = Field(..., description="Module bay name")
    module_type: str = Field(..., description="Module type model name")

    # Optional fields
    model_config = ConfigDict(
        extra='allow',
    )
