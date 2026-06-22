"""VM management endpoints"""
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status, WebSocket
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.models.models import User
from app.models.schemas import VMCreate, VMResponse, VMListResponse, VMAction, VMConsoleToken
from app.services.vm_service import get_vm_service, VMService
from app.routers.auth import get_current_user, get_current_admin
import structlog

logger = structlog.get_logger()
router = APIRouter(prefix="/vms", tags=["VMs"])

@router.post("", response_model=VMResponse, status_code=status.HTTP_201_CREATED)
async def create_vm(
    vm_data: VMCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a new VM"""
    service = get_vm_service(db)
    try:
        vm = await service.create_vm(current_user.id, vm_data)
        return vm
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("vm_creation_failed", error=str(e), user_id=current_user.id)
        raise HTTPException(status_code=500, detail="Failed to create VM")

@router.get("", response_model=VMListResponse)
async def list_vms(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """List user's VMs"""
    service = get_vm_service(db)
    vms = await service.get_user_vms(current_user.id)
    return {"vms": vms, "total": len(vms)}

@router.get("/{vm_id}", response_model=VMResponse)
async def get_vm(
    vm_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get VM details"""
    service = get_vm_service(db)
    vm = await service.get_vm(vm_id, current_user.id)
    if not vm:
        raise HTTPException(status_code=404, detail="VM not found")
    return vm

@router.post("/{vm_id}/action")
async def vm_action(
    vm_id: UUID,
    action: VMAction,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Perform action on VM: start, stop, reboot, destroy"""
    service = get_vm_service(db)
    try:
        vm = await service.vm_action(vm_id, current_user.id, action.action)
        return {"success": True, "vm": vm}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("vm_action_failed", error=str(e), vm_id=str(vm_id))
        raise HTTPException(status_code=500, detail="Action failed")

@router.post("/{vm_id}/renew")
async def renew_vm(
    vm_id: UUID,
    days: int = 30,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Renew VM expiry (admin only for now)"""
    service = get_vm_service(db)
    try:
        vm = await service.renew_vm(vm_id, current_user.id, days)
        return {"success": True, "vm": vm}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/{vm_id}/console")
async def get_console_token(
    vm_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get WebSocket console token"""
    service = get_vm_service(db)
    vm = await service.get_vm(vm_id, current_user.id)
    if not vm:
        raise HTTPException(status_code=404, detail="VM not found")

    # Generate console token
    from app.services.auth import create_access_token
    from datetime import datetime, timedelta

    token = create_access_token(
        {"sub": str(current_user.id), "vm": str(vm_id), "type": "console"},
        expires_delta=timedelta(minutes=15)
    )

    return VMConsoleToken(
        token=token,
        websocket_url=f"wss://your-domain.com/ws/console/{vm_id}?token={token}",
        expires_at=datetime.utcnow() + timedelta(minutes=15)
    )

# ─── Admin Endpoints ───

@router.get("/admin/all", response_model=VMListResponse)
async def admin_list_all_vms(
    status: str = None,
    current_user: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """Admin: list all VMs"""
    service = get_vm_service(db)
    vms = service.get_all_vms(status)
    for vm in vms:
        service._enrich_vm(vm)
    return {"vms": vms, "total": len(vms)}

@router.get("/admin/expiring")
async def admin_expiring_vms(
    days: int = 7,
    current_user: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """Admin: VMs expiring soon"""
    service = get_vm_service(db)
    vms = service.get_expiring_vms(days)
    return {"vms": vms, "total": len(vms)}

@router.get("/admin/expired")
async def admin_expired_vms(
    current_user: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """Admin: expired VMs (should be suspended)"""
    service = get_vm_service(db)
    vms = service.get_expired_vms()
    return {"vms": vms, "total": len(vms)}
