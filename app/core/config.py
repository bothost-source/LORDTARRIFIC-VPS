"""Application configuration"""
from pydantic import BaseSettings
from functools import lru_cache

class Settings(BaseSettings):
    database_url: str = "postgresql://vps_user:vps_pass@localhost:5432/vps_platform"
    redis_url: str = "redis://localhost:6379/0"
    secret_key: str = "change-me-now"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    proxmox_host: str = "https://localhost:8006"
    proxmox_user: str = "root@pam"
    proxmox_password: str = ""
    proxmox_verify_ssl: bool = False
    ddos_pps_threshold: int = 100000
    ddos_mbps_threshold: int = 500
    ddos_nullroute_minutes: int = 30
    app_name: str = "VPS Platform"
    debug: bool = False
    
    class Config:
        env_file = ".env"

@lru_cache()
def get_settings() -> Settings:
    return Settings()
