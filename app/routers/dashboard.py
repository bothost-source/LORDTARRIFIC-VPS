
"""Dashboard stats endpoints"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.core.database import get_db
from app.models.models import VM, User, Plan, DDoSEvent
from app.models.schemas import DashboardStats, AdminStats
from app.routers.auth import get_current_user, get_current_admin
from datetime import datetime, timedelta

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])

@router.get("/stats", response_model=DashboardStats)
async def get_stats(
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """User dashboard stats"""
    total = db.query(VM).filter(VM.user_id == current_user.id, VM.status != "destroyed").count()
    active = db.query(VM).filter(VM.user_id == current_user.id, VM.status == "running").count()
    suspended = db.query(VM).filter(VM.user_id == current_user.id, VM.status == "suspended").count()

    upcoming = db.query(VM).filter(
        VM.user_id == current_user.id,
        VM.status == "running",
        VM.expires_at <= datetime.utcnow() + timedelta(days=7)
    ).count()

    ddos_24h = db.query(DDoSEvent).filter(
        DDoSEvent.started_at >= datetime.utcnow() - timedelta(hours=24)
    ).count()

    return DashboardStats(
        total_vms=total,
        active_vms=active,
        suspended_vms=suspended,
        total_plans=db.query(Plan).filter(Plan.is_active == True).count(),
        ddos_events_24h=ddos_24h,
        upcoming_expirations=upcoming
    )

@router.get("/admin/stats", response_model=AdminStats)
async def get_admin_stats(
    current_user = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """Admin dashboard stats"""
    total_users = db.query(User).count()
    total_vms = db.query(VM).filter(VM.status != "destroyed").count()
    active_vms = db.query(VM).filter(VM.status == "running").count()
    suspended = db.query(VM).filter(VM.status == "suspended").count()

    ddos_24h = db.query(DDoSEvent).filter(
        DDoSEvent.started_at >= datetime.utcnow() - timedelta(hours=24)
    ).count()

    active_attacks = db.query(DDoSEvent).filter(
        DDoSEvent.ended_at.is_(None)
    ).count()

    upcoming = db.query(VM).filter(
        VM.status == "running",
        VM.expires_at <= datetime.utcnow() + timedelta(days=7)
    ).count()

    return AdminStats(
        total_vms=total_vms,
        active_vms=active_vms,
        suspended_vms=suspended,
        total_plans=db.query(Plan).filter(Plan.is_active == True).count(),
        ddos_events_24h=ddos_24h,
        upcoming_expirations=upcoming,
        total_users=total_users,
        total_revenue=0,  # No billing yet
        active_attacks=active_attacks
    )
