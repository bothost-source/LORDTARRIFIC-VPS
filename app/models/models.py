"""SQLAlchemy models"""
from sqlalchemy import Column, Integer, String, DateTime, Boolean, ForeignKey, Text, DECIMAL, BigInteger, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID, INET, MACADDR
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base
import uuid

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    username = Column(String(50), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    is_admin = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    vms = relationship("VM", back_populates="owner")

class Plan(Base):
    __tablename__ = "plans"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(50), nullable=False)
    slug = Column(String(50), unique=True, nullable=False)
    ram_gb = Column(Integer, nullable=False)
    cpu_cores = Column(Integer, nullable=False)
    disk_gb = Column(Integer, nullable=False)
    bandwidth_tb = Column(Integer, default=1)
    price_monthly = Column(DECIMAL(10, 2), nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    vms = relationship("VM", back_populates="plan")

class VM(Base):
    __tablename__ = "vms"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    plan_id = Column(Integer, ForeignKey("plans.id"), nullable=False)

    # Proxmox mapping
    proxmox_node = Column(String(50), nullable=False)
    proxmox_vmid = Column(Integer, nullable=False)

    # Networking
    ipv4 = Column(INET, unique=True)
    ipv6 = Column(INET)
    mac_address = Column(MACADDR)

    # Lifecycle
    status = Column(String(20), default="pending")  # pending, running, stopped, suspended, expired, destroyed
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    expires_at = Column(DateTime(timezone=True), nullable=False)
    suspended_at = Column(DateTime(timezone=True))
    destroyed_at = Column(DateTime(timezone=True))

    # Metadata
    hostname = Column(String(100), nullable=False)
    os_template = Column(String(50), nullable=False)
    root_password = Column(String(255))  # encrypted

    owner = relationship("User", back_populates="vms")
    plan = relationship("Plan", back_populates="vms")
    ddos_events = relationship("DDoSEvent", back_populates="vm")

class DDoSEvent(Base):
    __tablename__ = "ddos_events"

    id = Column(Integer, primary_key=True, index=True)
    vm_id = Column(UUID(as_uuid=True), ForeignKey("vms.id"))
    ip = Column(INET, nullable=False, index=True)
    attack_type = Column(String(50))
    pps_peak = Column(BigInteger)
    mbps_peak = Column(BigInteger)
    mitigated = Column(Boolean, default=False)
    nullrouted_at = Column(DateTime(timezone=True))
    nullroute_expires = Column(DateTime(timezone=True))
    started_at = Column(DateTime(timezone=True), server_default=func.now())
    ended_at = Column(DateTime(timezone=True))

    vm = relationship("VM", back_populates="ddos_events")

class IPPool(Base):
    __tablename__ = "ip_pool"

    id = Column(Integer, primary_key=True, index=True)
    ip_address = Column(INET, unique=True, nullable=False)
    gateway = Column(INET)
    netmask = Column(Integer, default=24)
    is_assigned = Column(Boolean, default=False)
    vm_id = Column(UUID(as_uuid=True), ForeignKey("vms.id"), nullable=True)
    datacenter = Column(String(50), default="default")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
