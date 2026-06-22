"""Proxmox VE API integration"""
import httpx
import json
from typing import Optional, Dict, Any, List
from app.core.config import get_settings
import structlog

logger = structlog.get_logger()
settings = get_settings()

class ProxmoxClient:
    def __init__(self):
        self.base_url = settings.proxmox_host.rstrip("/")
        self.auth = {
            "username": settings.proxmox_user,
            "password": settings.proxmox_password
        }
        self.verify_ssl = settings.proxmox_verify_ssl
        self._ticket: Optional[str] = None
        self._csrf: Optional[str] = None

    async def _get_ticket(self) -> str:
        """Authenticate and get ticket"""
        if self._ticket:
            return self._ticket

        async with httpx.AsyncClient(verify=self.verify_ssl) as client:
            resp = await client.post(
                f"{self.base_url}/api2/json/access/ticket",
                data=self.auth
            )
            resp.raise_for_status()
            data = resp.json()["data"]
            self._ticket = data["ticket"]
            self._csrf = data["CSRFPreventionToken"]
            return self._ticket

    async def _request(self, method: str, endpoint: str, **kwargs) -> Dict[str, Any]:
        """Make authenticated request to Proxmox"""
        ticket = await self._get_ticket()
        headers = {
            "Cookie": f"PVEAuthCookie={ticket}",
            "CSRFPreventionToken": self._csrf or "",
            "Content-Type": "application/json"
        }

        async with httpx.AsyncClient(verify=self.verify_ssl, timeout=60.0) as client:
            url = f"{self.base_url}/api2/json{endpoint}"
            resp = await client.request(method, url, headers=headers, **kwargs)
            resp.raise_for_status()
            return resp.json().get("data", {})

    async def get_nodes(self) -> List[Dict]:
        """List all Proxmox nodes"""
        return await self._request("GET", "/nodes")

    async def get_node_status(self, node: str) -> Dict:
        """Get node status and resources"""
        return await self._request("GET", f"/nodes/{node}/status")

    async def get_vms(self, node: str) -> List[Dict]:
        """List VMs on a node"""
        return await self._request("GET", f"/nodes/{node}/qemu")

    async def create_vm(
        self,
        node: str,
        vmid: int,
        name: str,
        memory: int,  # MB
        cores: int,
        storage: str = "local-lvm",
        disk_size: str = "20G",
        iso: str = "",
        network_bridge: str = "vmbr0",
        macaddr: Optional[str] = None
    ) -> Dict:
        """Create a new VM"""
        payload = {
            "vmid": vmid,
            "name": name,
            "memory": memory,
            "cores": cores,
            "sockets": 1,
            "cpu": "host",
            "net0": f"virtio,bridge={network_bridge}" + (f",macaddr={macaddr}" if macaddr else ""),
            "ostype": "l26",  # Linux 2.6+
            "scsihw": "virtio-scsi-single",
            "scsi0": f"{storage}:{disk_size},cache=writeback",
            "ide2": f"{storage}:cloudinit",
            "boot": "order=scsi0",
            "agent": "enabled=1",
            "ciuser": "root",
            "cipassword": self._generate_password(),
            "ipconfig0": "ip=dhcp"
        }

        if iso:
            payload["ide2"] = f"{storage}:iso/{iso},media=cdrom"

        result = await self._request("POST", f"/nodes/{node}/qemu", data=payload)
        logger.info("vm_created", node=node, vmid=vmid, name=name)
        return result

    async def clone_vm(
        self,
        node: str,
        vmid: int,
        newid: int,
        name: str,
        storage: str = "local-lvm"
    ) -> Dict:
        """Clone from a template VM"""
        payload = {
            "newid": newid,
            "name": name,
            "storage": storage,
            "full": 1
        }
        result = await self._request("POST", f"/nodes/{node}/qemu/{vmid}/clone", data=payload)
        logger.info("vm_cloned", node=node, template=vmid, newid=newid, name=name)
        return result

    async def start_vm(self, node: str, vmid: int) -> Dict:
        return await self._request("POST", f"/nodes/{node}/qemu/{vmid}/status/start")

    async def stop_vm(self, node: str, vmid: int) -> Dict:
        return await self._request("POST", f"/nodes/{node}/qemu/{vmid}/status/stop")

    async def shutdown_vm(self, node: str, vmid: int) -> Dict:
        return await self._request("POST", f"/nodes/{node}/qemu/{vmid}/status/shutdown")

    async def reboot_vm(self, node: str, vmid: int) -> Dict:
        return await self._request("POST", f"/nodes/{node}/qemu/{vmid}/status/reboot")

    async def destroy_vm(self, node: str, vmid: int) -> Dict:
        return await self._request("DELETE", f"/nodes/{node}/qemu/{vmid}")

    async def get_vm_status(self, node: str, vmid: int) -> Dict:
        return await self._request("GET", f"/nodes/{node}/qemu/{vmid}/status/current")

    async def resize_disk(self, node: str, vmid: int, disk: str = "scsi0", size: str = "+10G") -> Dict:
        return await self._request("PUT", f"/nodes/{node}/qemu/{vmid}/resize", data={"disk": disk, "size": size})

    async def set_vm_config(self, node: str, vmid: int, **config) -> Dict:
        return await self._request("PUT", f"/nodes/{node}/qemu/{vmid}/config", data=config)

    async def get_next_vmid(self) -> int:
        """Get next available VMID"""
        result = await self._request("GET", "/cluster/nextid")
        return int(result)

    def _generate_password(self, length: int = 16) -> str:
        import secrets, string
        alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
        return ''.join(secrets.choice(alphabet) for _ in range(length))

# Singleton
proxmox = ProxmoxClient()
