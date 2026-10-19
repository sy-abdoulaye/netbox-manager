from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from typing import Optional, Annotated

class SiteCreate(BaseModel):
    name: Annotated[str, StringConstraints(min_length=1, max_length=100)]
    slug: Annotated[str, StringConstraints(pattern=r'^[-a-zA-Z0-9_]+$', min_length=1)]
    status: Optional[str] = Field("active", pattern="^(active|planned|retired)$")
    time_zone: Optional[str] = "Europe/Paris"
    comments: Optional[str] = None

    model_config = ConfigDict(
        extra='allow',
    )