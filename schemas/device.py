from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from typing import Optional, Annotated

class DeviceCreate(BaseModel):
    name: Annotated[str, StringConstraints(min_length=2)]
    site: str
    role: str
    device_type: str
    status: str = Field("active", pattern="^(active|offline|planned|staged|failed|decommissioning)$")

    model_config = ConfigDict(
        extra='allow',
    )
