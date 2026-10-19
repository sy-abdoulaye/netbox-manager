from pydantic import BaseModel, ConfigDict, Field, field_validator
from typing import Optional
import ipaddress


class IPAddressCreate(BaseModel):
    address: str
    interface: str
    device: str
    status: Optional[str] = Field("active", pattern="^(active|inactive|reserved|deprecated|dhcp|slaac)$")
    role: Optional[str] = Field(None, pattern="^(loopback|secondary|anycast|vip|vrrp|hsrp|glbp|carp)$")
    tenant: Optional[str] = None
    vrf: Optional[str] = None

    @field_validator('address')
    @classmethod
    def validate_ip_address(cls, v: str) -> str:
        """Validate IP address is in CIDR format."""
        try:
            ipaddress.ip_interface(v)
            return v
        except ValueError:
            raise ValueError(f"Invalid IP address format: {v}. Must be in CIDR format (e.g., 192.168.1.1/24)")

    model_config = ConfigDict(extra='allow')