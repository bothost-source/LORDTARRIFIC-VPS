#!/usr/bin/env python3
"""Seed initial plans and admin user"""
import sys
sys.path.insert(0, ".")

from sqlalchemy.orm import Session
from app.core.database import SessionLocal, engine, Base
from app.models.models import Plan, User
from app.services.auth import get_password_hash

# Create tables
Base.metadata.create_all(bind=engine)

db = SessionLocal()

# Seed plans
plans = [
    Plan(name="Nano", slug="nano", ram_gb=1, cpu_cores=1, disk_gb=20, bandwidth_tb=1, price_monthly=5.00),
    Plan(name="Micro", slug="micro", ram_gb=2, cpu_cores=1, disk_gb=40, bandwidth_tb=2, price_monthly=10.00),
    Plan(name="Standard", slug="standard", ram_gb=4, cpu_cores=2, disk_gb=80, bandwidth_tb=3, price_monthly=20.00),
    Plan(name="Pro", slug="pro", ram_gb=8, cpu_cores=4, disk_gb=160, bandwidth_tb=5, price_monthly=40.00),
    Plan(name="Beast", slug="beast", ram_gb=16, cpu_cores=6, disk_gb=320, bandwidth_tb=7, price_monthly=80.00),
    Plan(name="Monster", slug="monster", ram_gb=32, cpu_cores=8, disk_gb=640, bandwidth_tb=10, price_monthly=160.00),
    Plan(name="Titan", slug="titan", ram_gb=64, cpu_cores=16, disk_gb=1280, bandwidth_tb=20, price_monthly=320.00),
]

for plan in plans:
    existing = db.query(Plan).filter(Plan.slug == plan.slug).first()
    if not existing:
        db.add(plan)
        print(f"✅ Added plan: {plan.name} ({plan.ram_gb}GB RAM, {plan.cpu_cores} cores)")

# Seed admin user
admin = db.query(User).filter(User.username == "admin").first()
if not admin:
    admin = User(
        email="admin@vps.local",
        username="admin",
        hashed_password=get_password_hash("admin123"),  # CHANGE THIS!
        is_admin=True,
        is_active=True
    )
    db.add(admin)
    print("✅ Added admin user (username: admin, password: admin123)")
    print("⚠️  CHANGE THE ADMIN PASSWORD IMMEDIATELY!")

db.commit()
db.close()
print("\n🎉 Seeding complete!")
