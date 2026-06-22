"""Pydantic schemas for API"""
from pydantic import BaseModel, Field, EmailStr
from typing import Optional, List
from datetime import datetime
from decimal import Decimal
from uuid import UUID

# ─── User Schemas ───
class UserBase(BaseModel):
    email: EmailStr
    username: str = Field(..., min_length=3, max_length=50)

class UserCreate(UserBase):
    password: str = Field(..., min_length=8)

class UserResponse(UserBase):
    id: int
    is_admin: bool
    is_active: bool
    created_at: datetime

    class Config:
        orm_mode = True

class UserLogin(BaseModel):
    username: str
    password: str

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int

# ─── Plan Schemas ───
class PlanBase(BaseModel):
    name: str
    slug: str
    ram_gb: int
    cpu_cores: int
    disk_gb: int
    bandwidth_tb: int = 1
    price_monthly: Decimal

class PlanCreate(PlanBase):
    pass

class PlanResponse(PlanBase):
    id: int
    is_active: bool
    created_at: datetime

    class Config:
        orm_mode = True

# ─── VM Schemas ───
class VMCreate(BaseModel):
    plan_id: int
    hostname: str = Field(..., min_length=1, max_length=100)
    os_template: str = Field(default="ubuntu-22.04")
    duration_days: int = Field(default=30, ge=1, le=365)

class VMResponse(BaseModel):
    id: UUID
    hostname: str
    status: str
    ipv4: Optional[str]
    ipv6: Optional[str]
    mac_address: Optional[str]
    proxmox_node: str
    proxmox_vmid: int
    os_template: str
    created_at: datetime
    expires_at: datetime
    suspended_at: Optional[datetime]
    destroyed_at: Optional[datetime]

    # Nested
    plan: PlanResponse

    # Computed
    days_remaining: int = 0
    is_expired: bool = False
    is_expiring_soon: bool = False  # < 7 days

    class Config:
        orm_mode = True

class VMListResponse(BaseModel):
    vms: List[VMResponse]
    total: int

class VMAction(BaseModel):
    action: str  # start, stop, reboot, destroy

class VMConsoleToken(BaseModel):
    token: str
    websocket_url: str
    expires_at: datetime

# ─── DDoS Schemas ───
class DDoSEventResponse(BaseModel):
    id: int
    ip: str
    attack_type: Optional[str]
    pps_peak: Optional[int]
    mbps_peak: Optional[int]
    mitigated: bool
    nullrouted_at: Optional[datetime]
    nullroute_expires: Optional[datetime]
    started_at: datetime
    ended_at: Optional[datetime]

    class Config:
        orm_mode = True

# ─── Dashboard Stats ───
class DashboardStats(BaseModel):
    total_vms: int
    active_vms: int
    suspended_vms: int
    total_plans: int
    ddos_events_24h: int
    upcoming_expirations: int  # < 7 days

class AdminStats(DashboardStats):
    total_users: int
    total_revenue: Decimal
    active_attacks: int
