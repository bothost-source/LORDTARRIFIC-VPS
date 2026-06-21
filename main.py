"""VPS Platform - Main FastAPI Application"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager

from app.core.config import get_settings
from app.core.database import engine, Base
from app.routers import auth, vms, plans, ddos, dashboard
from app.services.expiry_worker import expiry_worker_instance
from app.services.ddos_shield import ddos_shield
import structlog

logger = structlog.get_logger()
settings = get_settings()

# Create tables
Base.metadata.create_all(bind=engine)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events"""
    # Startup
    logger.info("vps_platform_starting", app_name=settings.app_name)

    # Setup DDoS shield
    await ddos_shield.setup_nftables()

    # Start expiry worker scheduler
    expiry_worker_instance.start_scheduler()

    yield

    # Shutdown
    logger.info("vps_platform_shutting_down")

app = FastAPI(
    title=settings.app_name,
    description="Custom VPS hosting platform with DDoS protection",
    version="1.0.0",
    lifespan=lifespan
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(auth.router, prefix="/api")
app.include_router(vms.router, prefix="/api")
app.include_router(plans.router, prefix="/api")
app.include_router(ddos.router, prefix="/api/admin")
app.include_router(dashboard.router, prefix="/api")

@app.get("/health")
async def health_check():
    return {"status": "healthy", "version": "1.0.0"}

@app.get("/")
async def root():
    return {
        "name": settings.app_name,
        "version": "1.0.0",
        "docs": "/docs"
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=settings.debug)
