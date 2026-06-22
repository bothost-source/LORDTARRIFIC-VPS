"""DDoS monitoring endpoints"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.models.models import DDoSEvent
from app.models.schemas import DDoSEventResponse
from app.services.ddos_shield import ddos_shield
from app.routers.auth import get_current_admin
from typing import List

router = APIRouter(prefix="/ddos", tags=["DDoS Shield"])

@router.get("/events", response_model=List[DDoSEventResponse])
async def list_events(
    limit: int = 50,
    current_user = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """List recent DDoS events"""
    events = db.query(DDoSEvent).order_by(DDoSEvent.started_at.desc()).limit(limit).all()
    return events

@router.get("/stats")
async def get_stats(current_user = Depends(get_current_admin)):
    """Get DDoS shield statistics"""
    return await ddos_shield.get_stats()

@router.post("/detect")
async def detect_attack(
    data: dict,
    current_user = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """Receive attack detection from monitor"""
    ip = data.get("ip")
    attack_type = data.get("type", "volumetric")
    metrics = {
        "pps": data.get("pps", 0),
        "mbps": data.get("mbps", 0)
    }

    event = await ddos_shield.trigger_mitigation(db, ip, attack_type, metrics)
    return {"mitigated": True, "event_id": event.id}

@router.post("/nullroute/{ip}")
async def manual_nullroute(
    ip: str,
    duration: int = 30,
    current_user = Depends(get_current_admin)
):
    """Manually null-route an IP"""
    result = await ddos_shield.nullroute_ip(ip, duration)
    return {"success": result, "ip": ip, "duration": duration}

@router.post("/lift/{ip}")
async def lift_nullroute(
    ip: str,
    current_user = Depends(get_current_admin)
):
    """Lift null-route"""
    result = await ddos_shield.lift_nullroute(ip)
    return {"success": result, "ip": ip}
