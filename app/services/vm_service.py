"""VM management service"""
from datetime import datetime, timedelta
from typing import Optional, List
from uuid import UUID
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.models.models import VM, Plan, IPPool, User
from app.models.schemas import VMCreate, VMResponse
from app.services.proxmox import proxmox
from app.services.auth import get_password_hash
import structlog

logger = structlog.get_logger()

# OS Templates mapping (you need to create these in Proxmox first)
OS_TEMPLATES = {
    "ubuntu-22.04": {"template_vmid": 9000, "description": "Ubuntu 22.04 LTS"},
    "ubuntu-24.04": {"template_vmid": 9001, "description": "Ubuntu 24.04 LTS"},
    "debian-12": {"template_vmid": 9002, "description": "Debian 12"},
    "centos-9": {"template_vmid": 9003, "description": "CentOS Stream 9"},
    "alpine-3.19": {"template_vmid": 9004, "description": "Alpine Linux 3.19"},
    "windows-server-2022": {"template_vmid": 9100, "description": "Windows Server 2022"},
}

class VMService:
    def __init__(self, db: Session):
        self.db = db

    def get_plan(self, plan_id: int) -> Optional[Plan]:
        return self.db.query(Plan).filter(Plan.id == plan_id, Plan.is_active == True).first()

    def get_available_ip(self) -> Optional[IPPool]:
        """Get next available IP from pool"""
        return self.db.query(IPPool).filter(
            IPPool.is_assigned == False
        ).order_by(IPPool.id).first()

    async def create_vm(self, user_id: int, vm_data: VMCreate) -> VM:
        """Create a new VM for user"""
        plan = self.get_plan(vm_data.plan_id)
        if not plan:
            raise ValueError("Invalid or inactive plan")

        # Get available IP
        ip = self.get_available_ip()
        if not ip:
            raise ValueError("No available IP addresses")

        # Get OS template
        os_info = OS_TEMPLATES.get(vm_data.os_template)
        if not os_info:
            raise ValueError(f"Unknown OS template: {vm_data.os_template}")

        # Get next VMID from Proxmox
        next_vmid = await proxmox.get_next_vmid()

        # Pick least loaded node (simple round-robin for now)
        nodes = await proxmox.get_nodes()
        if not nodes:
            raise ValueError("No Proxmox nodes available")

        node = nodes[0]["node"]  # TODO: implement proper scheduling

        # Generate root password
        root_password = self._generate_password()

        # Clone from template
        await proxmox.clone_vm(
            node=node,
            vmid=os_info["template_vmid"],
            newid=next_vmid,
            name=vm_data.hostname
        )

        # Configure VM resources
        await proxmox.set_vm_config(
            node=node,
            vmid=next_vmid,
            memory=plan.ram_gb * 1024,
            cores=plan.cpu_cores,
            cipassword=root_password,
            ipconfig0=f"ip={ip.ip_address}/24,gw={ip.gateway}"
        )

        # Resize disk to plan size
        await proxmox.resize_disk(
            node=node,
            vmid=next_vmid,
            disk="scsi0",
            size=f"{plan.disk_gb}G"
        )

        # Start VM
        await proxmox.start_vm(node=node, vmid=next_vmid)

        # Create DB record
        expires_at = datetime.utcnow() + timedelta(days=vm_data.duration_days)

        vm = VM(
            user_id=user_id,
            plan_id=plan.id,
            proxmox_node=node,
            proxmox_vmid=next_vmid,
            ipv4=ip.ip_address,
            ipv6=None,  # TODO: IPv6 support
            mac_address=None,  # Will be set by Proxmox
            status="running",
            hostname=vm_data.hostname,
            os_template=vm_data.os_template,
            root_password=get_password_hash(root_password),
            expires_at=expires_at
        )

        self.db.add(vm)

        # Mark IP as assigned
        ip.is_assigned = True
        ip.vm_id = vm.id

        self.db.commit()
        self.db.refresh(vm)

        logger.info(
            "vm_provisioned",
            vm_id=str(vm.id),
            user_id=user_id,
            vmid=next_vmid,
            node=node,
            plan=plan.name
        )

        return vm

    async def get_user_vms(self, user_id: int) -> List[VM]:
        """Get all VMs for a user with computed fields"""
        vms = self.db.query(VM).filter(
            VM.user_id == user_id,
            VM.status != "destroyed"
        ).order_by(VM.created_at.desc()).all()

        for vm in vms:
            self._enrich_vm(vm)

        return vms

    async def get_vm(self, vm_id: UUID, user_id: Optional[int] = None) -> Optional[VM]:
        """Get single VM"""
        query = self.db.query(VM).filter(VM.id == vm_id, VM.status != "destroyed")
        if user_id:
            query = query.filter(VM.user_id == user_id)

        vm = query.first()
        if vm:
            self._enrich_vm(vm)
        return vm

    async def vm_action(self, vm_id: UUID, user_id: int, action: str) -> VM:
        """Perform action on VM"""
        vm = await self.get_vm(vm_id, user_id)
        if not vm:
            raise ValueError("VM not found")

        if action == "start":
            if vm.status in ["stopped", "suspended"]:
                await proxmox.start_vm(vm.proxmox_node, vm.proxmox_vmid)
                vm.status = "running"

        elif action == "stop":
            if vm.status == "running":
                await proxmox.stop_vm(vm.proxmox_node, vm.proxmox_vmid)
                vm.status = "stopped"

        elif action == "reboot":
            if vm.status == "running":
                await proxmox.reboot_vm(vm.proxmox_node, vm.proxmox_vmid)

        elif action == "destroy":
            # Stop first
            if vm.status == "running":
                await proxmox.stop_vm(vm.proxmox_node, vm.proxmox_vmid)

            # Destroy
            await proxmox.destroy_vm(vm.proxmox_node, vm.proxmox_vmid)
            vm.status = "destroyed"
            vm.destroyed_at = datetime.utcnow()

            # Release IP
            ip = self.db.query(IPPool).filter(IPPool.vm_id == vm.id).first()
            if ip:
                ip.is_assigned = False
                ip.vm_id = None

        else:
            raise ValueError(f"Unknown action: {action}")

        self.db.commit()
        self.db.refresh(vm)
        self._enrich_vm(vm)

        logger.info("vm_action", vm_id=str(vm.id), action=action, user_id=user_id)
        return vm

    async def renew_vm(self, vm_id: UUID, user_id: int, days: int) -> VM:
        """Renew VM expiry"""
        vm = await self.get_vm(vm_id, user_id)
        if not vm:
            raise ValueError("VM not found")

        # If suspended due to expiry, restart it
        if vm.status == "suspended":
            await proxmox.start_vm(vm.proxmox_node, vm.proxmox_vmid)
            vm.status = "running"
            vm.suspended_at = None

        vm.expires_at = vm.expires_at + timedelta(days=days)
        self.db.commit()
        self.db.refresh(vm)
        self._enrich_vm(vm)

        return vm

    def _enrich_vm(self, vm: VM):
        """Add computed fields to VM object"""
        now = datetime.utcnow()
        delta = vm.expires_at - now
        vm.days_remaining = max(0, delta.days)
        vm.is_expired = now > vm.expires_at
        vm.is_expiring_soon = 0 < vm.days_remaining <= 7

    def _generate_password(self, length: int = 16) -> str:
        import secrets, string
        alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
        return ''.join(secrets.choice(alphabet) for _ in range(length))

    # ─── Admin Methods ───
    def get_all_vms(self, status: Optional[str] = None) -> List[VM]:
        query = self.db.query(VM)
        if status:
            query = query.filter(VM.status == status)
        return query.order_by(VM.created_at.desc()).all()

    def get_expiring_vms(self, days: int = 7) -> List[VM]:
        """Get VMs expiring within N days"""
        cutoff = datetime.utcnow() + timedelta(days=days)
        return self.db.query(VM).filter(
            VM.status == "running",
            VM.expires_at <= cutoff
        ).all()

    def get_expired_vms(self) -> List[VM]:
        """Get VMs that have passed expiry"""
        return self.db.query(VM).filter(
            VM.status == "running",
            VM.expires_at <= datetime.utcnow()
        ).all()

# Factory
def get_vm_service(db: Session) -> VMService:
    return VMService(db)
