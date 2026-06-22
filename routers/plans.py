"""Plan/Tier endpoints"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.models.models import Plan
from app.models.schemas import PlanResponse
from app.routers.auth import get_current_user

router = APIRouter(prefix="/plans", tags=["Plans"])

@router.get("", response_model=list[PlanResponse])
async def list_plans(db: Session = Depends(get_db)):
    """Get all active plans"""
    plans = db.query(Plan).filter(Plan.is_active == True).all()
    return plans

@router.get("/{plan_id}", response_model=PlanResponse)
async def get_plan(plan_id: int, db: Session = Depends(get_db)):
    plan = db.query(Plan).filter(Plan.id == plan_id, Plan.is_active == True).first()
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")
    return plan
