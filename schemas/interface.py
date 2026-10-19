from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from typing import Optional, Annotated
from typing import List

class InterfaceCreate(BaseModel):
    device: str
    name: Annotated[str, StringConstraints(min_length=1)]
    type: str = Field("1000base-t")
    enabled: bool = True
    mac_address: Optional[
        Annotated[str, StringConstraints(pattern=r'^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$')]
    ] = None
    mtu: Optional[int] = Field(None, ge=576, le=9216)

    model_config = ConfigDict(
        extra='allow',
    )