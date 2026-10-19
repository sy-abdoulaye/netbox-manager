from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from typing import Optional, Annotated

class DeviceRoleCreate(BaseModel):
    name: Annotated[str, StringConstraints(min_length=1, max_length=100)]
    slug: Annotated[str, StringConstraints(pattern=r'^[-a-zA-Z0-9_]+$')]
    # color: Optional[Annotated[str, StringConstraints(pattern=r'^[0-9a-fA-F]{6}$')]] = "1E90FF"

    model_config = ConfigDict(
        extra='allow',
    )

