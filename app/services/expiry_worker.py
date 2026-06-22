"""VM expiry background worker"""
import asyncio
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from app.core.database import SessionLocal
from app.models.models import VM
from app.services.proxmox import proxmox
from app.services.vm_service import get_vm_service
import structlog

logger = structlog.get_logger()

# Grace period before destruction (days)
SUSPENSION_GRACE_DAYS = 7

async def process_expirations():
    """Main expiry processing loop - run every minute via cron/APScheduler"""
    db = SessionLocal()
    try:
        vm_service = get_vm_service(db)
        now = datetime.utcnow()

        # ─── 1. Suspend expired VMs ───
        expired_vms = db.query(VM).filter(
            VM.status == "running",
            VM.expires_at <= now
        ).all()

        for vm in expired_vms:
            try:
                logger.info("suspending_expired_vm", vm_id=str(vm.id), vmid=vm.proxmox_vmid)

                # Stop the VM
                await proxmox.stop_vm(vm.proxmox_node, vm.proxmox_vmid)

                vm.status = "suspended"
                vm.suspended_at = now
                db.commit()

                logger.info("vm_suspended", vm_id=str(vm.id))

            except Exception as e:
                logger.error("failed_to_suspend_vm", vm_id=str(vm.id), error=str(e))
                db.rollback()

        # ─── 2. Destroy VMs past grace period ───
        destroy_cutoff = now - timedelta(days=SUSPENSION_GRACE_DAYS)

        to_destroy = db.query(VM).filter(
            VM.status == "suspended",
            VM.suspended_at <= destroy_cutoff
        ).all()

        for vm in to_destroy:
            try:
                logger.info("destroying_grace_expired_vm", vm_id=str(vm.id), vmid=vm.proxmox_vmid)

                # Destroy VM
                await proxmox.destroy_vm(vm.proxmox_node, vm.proxmox_vmid)

                # Release IP
                from app.models.models import IPPool
                ip = db.query(IPPool).filter(IPPool.vm_id == vm.id).first()
                if ip:
                    ip.is_assigned = False
                    ip.vm_id = None

                vm.status = "destroyed"
                vm.destroyed_at = now
                db.commit()

                logger.info("vm_destroyed", vm_id=str(vm.id))

            except Exception as e:
                logger.error("failed_to_destroy_vm", vm_id=str(vm.id), error=str(e))
                db.rollback()

        # ─── 3. Warn users of upcoming expiry (< 3 days) ───
        warn_cutoff = now + timedelta(days=3)
        warning_vms = db.query(VM).filter(
            VM.status == "running",
            VM.expires_at <= warn_cutoff,
            VM.expires_at > now
        ).all()

        for vm in warning_vms:
            # TODO: Send email/notification
            logger.info("vm_expiry_warning", vm_id=str(vm.id), days_remaining=(vm.expires_at - now).days)

        return {
            "suspended": len(expired_vms),
            "destroyed": len(to_destroy),
            "warnings": len(warning_vms)
        }

    finally:
        db.close()


# For APScheduler integration
class ExpiryWorker:
    def __init__(self):
        self.running = False

    async def run_once(self):
        if self.running:
            return
        self.running = True
        try:
            result = await process_expirations()
            logger.info("expiry_worker_completed", result=result)
            return result
        finally:
            self.running = False

    def start_scheduler(self):
        """Start background scheduler - call from FastAPI startup"""
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        from apscheduler.triggers.interval import IntervalTrigger

        scheduler = AsyncIOScheduler()
        scheduler.add_job(
            self.run_once,
            trigger=IntervalTrigger(minutes=1),
            id="expiry_worker",
            replace_existing=True
        )
        scheduler.start()
        logger.info("expiry_scheduler_started")
        return scheduler

expiry_worker_instance = ExpiryWorker()
