from pydantic import BaseModel, ConfigDict, StringConstraints
from typing import Optional, Annotated

class DeviceTypeCreate(BaseModel):
    manufacturer: str
    model: Annotated[str, StringConstraints(min_length=1)]
    slug: Annotated[str, StringConstraints(pattern=r'^[-a-zA-Z0-9_]+$')]
    u_height: Optional[int] = 1
    is_full_depth: Optional[bool] = True

    model_config = ConfigDict(
        extra='allow',
    )
