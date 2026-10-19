from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime

class InventoryItemCreate(BaseModel):
    device: str = Field(..., description="The device this inventory item belongs to")
    name: str = Field(..., description="The name of the inventory item")
    label: Optional[str] = Field(None, description="A user-defined label for the inventory item")
    part_id: Optional[str] = Field(None, description="The part ID or model number of the inventory item")
    serial: Optional[str] = Field(None, description="The serial number of the inventory item")
    asset_tag: Optional[str] = Field(None, description="An asset tag for the inventory item")
    discovered: bool = Field(False, description="Whether the item was discovered automatically")
    description: Optional[str] = Field(None, description="A description of the inventory item")
    manufacturer: Optional[str] = Field(None, description="The manufacturer of the inventory item")
    component_type: Optional[str] = Field(None, description="The type of component this item represents (e.g., 'dcim.interface')")
    component_id: Optional[str] = Field(None, description="The ID of the component this item represents")
    parent: Optional[str] = Field(None, description="The parent inventory item, if applicable")
    tags: List[str] = Field(default_factory=list, description="Tags associated with the inventory item")
    custom_fields: dict = Field(default_factory=dict, description="Custom fields for the inventory item")
    created: Optional[datetime] = Field(None, description="Creation timestamp")
    updated: Optional[datetime] = Field(None, description="Last update timestamp")