from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from typing import Optional, Annotated


class ConsolePortCreate(BaseModel):
    device: str
    name: Annotated[str, StringConstraints(min_length=1)]
    type: Optional[str]
    speed: Optional[int] = Field(
        None,
        description="Port speed in bps"
    )
    description: Optional[str] = None
    mark_connected: Optional[bool] = False
    label: Optional[str] = None

    model_config = ConfigDict(extra='allow')