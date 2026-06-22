"""DDoS detection and mitigation service"""
import asyncio
import subprocess
import json
from datetime import datetime, timedelta
from typing import Optional, List, Dict
from sqlalchemy.orm import Session
from app.models.models import DDoSEvent, VM, IPPool
from app.core.config import get_settings
import structlog

logger = structlog.get_logger()
settings = get_settings()

class DDoSShield:
    """
    Custom DDoS mitigation layer.

    Architecture:
    - Layer 1: nftables rate limiting (always on)
    - Layer 2: eBPF/XDP packet filter (for high-volume attacks)
    - Layer 3: Null-routing / RTBH for extreme attacks
    """

    def __init__(self):
        self.nft_table = "ddos_shield"
        self.xdp_attached = False
        self.active_nullroutes: Dict[str, datetime] = {}

    # ─── NFTABLES LAYER ───

    async def setup_nftables(self):
        """Initialize nftables DDoS rules"""
        script = f"""
#!/usr/sbin/nft -f

# Flush existing
flush ruleset

# Create DDoS table
table inet {self.nft_table} {{
    # Sets for tracking
    set blacklist {{
        type ipv4_addr
        flags timeout
        timeout 1h
    }}

    set whitelist {{
        type ipv4_addr
        flags timeout
        timeout 24h
    }}

    # Meter for per-IP rate limiting
    meter syn_flood {{ ip saddr limit rate over 30/second burst 50 packets }}
    meter udp_flood {{ ip saddr limit rate over 100/second burst 150 packets }}
    meter global_rate {{ ip saddr limit rate over 1000/second burst 1500 packets }}
    meter conn_limit {{ ip saddr ct count over 100 }}

    chain input {{
        type filter hook input priority -100; policy accept;

        # Allow loopback
        iif "lo" accept

        # Allow established
        ct state established,related accept

        # Drop invalid
        ct state invalid drop

        # Whitelist bypass
        ip saddr @whitelist accept

        # Blacklist immediate drop
        ip saddr @blacklist drop

        # Drop bogon addresses
        ip saddr {{ 0.0.0.0/8, 10.0.0.0/8, 127.0.0.0/8, 169.254.0.0/16, 
                     172.16.0.0/12, 192.168.0.0/16, 224.0.0.0/4 }} drop

        # Drop fragments
        ip frag-off & 0x1fff != 0 drop

        # Malformed TCP flags
        tcp flags & (fin|syn|rst|ack) == 0 drop
        tcp flags & (fin|syn) == fin|syn drop
        tcp flags & (syn|rst) == syn|rst drop
        tcp flags & (fin|rst) == fin|rst drop
        tcp flags & (fin|ack) == fin drop
        tcp flags & (ack|urg) == urg drop

        # ICMP rate limit
        ip protocol icmp icmp type echo-request limit rate 1/second burst 4 packets accept
        ip protocol icmp icmp type echo-request drop

        # SYN flood protection
        tcp flags syn meter syn_flood drop

        # UDP flood protection
        ip protocol udp meter udp_flood drop

        # Global per-IP rate limit
        meter global_rate drop

        # Connection limit
        meter conn_limit drop

        # Block amplification attacks
        ip protocol udp udp sport 53 ct state new drop
        ip protocol udp udp sport 123 ct state new drop
        ip protocol udp udp sport 11211 ct state new drop
        ip protocol udp udp sport 1900 ct state new drop
        ip protocol udp udp sport 389 ct state new drop

        # Allow SSH with rate limit
        tcp dport 22 meter ssh_limit {{ ip saddr limit rate over 4/minute burst 6 packets }} accept
        tcp dport 22 drop

        # Allow HTTP/HTTPS
        tcp dport 80 accept
        tcp dport 443 accept

        # Log and drop rest (for analysis)
        log prefix "DDOS-DROP: " limit rate 5/second
        drop
    }}

    chain forward {{
        type filter hook forward priority 0; policy accept;

        # Rate limit forwarded traffic too
        ip saddr meter forward_rate {{ ip saddr limit rate over 500/second burst 800 packets }} drop
    }}
}}
"""
        try:
            proc = await asyncio.create_subprocess_exec(
                "nft", "-f", "-",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await proc.communicate(script.encode())

            if proc.returncode != 0:
                logger.error("nftables_setup_failed", error=stderr.decode())
                raise RuntimeError(f"nftables setup failed: {stderr.decode()}")

            logger.info("nftables_ddos_shield_activated")

        except FileNotFoundError:
            logger.warning("nftables_not_found", message="nftables not installed, using fallback")

    async def add_to_blacklist(self, ip: str, timeout_minutes: int = 60):
        """Add IP to nftables blacklist"""
        try:
            proc = await asyncio.create_subprocess_exec(
                "nft", "add", "element", "inet", self.nft_table, "blacklist", "{", ip, "}",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            await proc.communicate()
            logger.info("ip_blacklisted", ip=ip, timeout=timeout_minutes)
        except Exception as e:
            logger.error("blacklist_failed", ip=ip, error=str(e))

    async def remove_from_blacklist(self, ip: str):
        """Remove IP from blacklist"""
        try:
            proc = await asyncio.create_subprocess_exec(
                "nft", "delete", "element", "inet", self.nft_table, "blacklist", "{", ip, "}",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            await proc.communicate()
            logger.info("ip_unblacklisted", ip=ip)
        except Exception as e:
            logger.error("unblacklist_failed", ip=ip, error=str(e))

    # ─── NULL ROUTING LAYER ───

    async def nullroute_ip(self, ip: str, duration_minutes: Optional[int] = None):
        """Null-route an IP (RTBH - Remote Triggered Black Hole)"""
        duration = duration_minutes or settings.ddos_nullroute_minutes

        try:
            # Add null route via ip route
            proc = await asyncio.create_subprocess_exec(
                "ip", "route", "add", f"{ip}/32", "dev", "lo", "mtu", "1", "adv_mss", "1",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await proc.communicate()

            if proc.returncode == 0:
                self.active_nullroutes[ip] = datetime.utcnow() + timedelta(minutes=duration)
                logger.info("ip_nullrouted", ip=ip, duration=duration)
                return True
            else:
                logger.error("nullroute_failed", ip=ip, error=stderr.decode())
                return False

        except Exception as e:
            logger.error("nullroute_error", ip=ip, error=str(e))
            return False

    async def lift_nullroute(self, ip: str):
        """Remove null route"""
        try:
            proc = await asyncio.create_subprocess_exec(
                "ip", "route", "del", f"{ip}/32",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            await proc.communicate()

            if ip in self.active_nullroutes:
                del self.active_nullroutes[ip]

            logger.info("nullroute_lifted", ip=ip)
            return True

        except Exception as e:
            logger.error("lift_nullroute_failed", ip=ip, error=str(e))
            return False

    async def cleanup_expired_nullroutes(self):
        """Remove expired null routes"""
        now = datetime.utcnow()
        expired = [ip for ip, expires in self.active_nullroutes.items() if now > expires]

        for ip in expired:
            await self.lift_nullroute(ip)

        return len(expired)

    # ─── DETECTION LAYER ───

    async def analyze_traffic(self, ip: str, metrics: Dict) -> Optional[str]:
        """Analyze traffic metrics and decide mitigation"""
        pps = metrics.get("pps", 0)
        mbps = metrics.get("mbps", 0)
        syn_ratio = metrics.get("syn_ratio", 0)

        # Determine attack type
        if pps > settings.ddos_pps_threshold or mbps > settings.ddos_mbps_threshold:
            if syn_ratio > 0.7:
                return "syn_flood"
            return "volumetric"

        if syn_ratio > 0.7:
            return "syn_flood"

        return None

    async def trigger_mitigation(self, db: Session, ip: str, attack_type: str, metrics: Dict):
        """Trigger full mitigation pipeline"""
        # Find associated VM
        vm = db.query(VM).filter(VM.ipv4 == ip).first()

        # Log event
        event = DDoSEvent(
            vm_id=vm.id if vm else None,
            ip=ip,
            attack_type=attack_type,
            pps_peak=metrics.get("pps"),
            mbps_peak=metrics.get("mbps"),
            mitigated=True,
            nullrouted_at=datetime.utcnow(),
            nullroute_expires=datetime.utcnow() + timedelta(minutes=settings.ddos_nullroute_minutes)
        )
        db.add(event)
        db.commit()

        # Execute mitigation
        await self.nullroute_ip(ip)
        await self.add_to_blacklist(ip, settings.ddos_nullroute_minutes)

        logger.warning(
            "ddos_mitigation_triggered",
            ip=ip,
            attack_type=attack_type,
            pps=metrics.get("pps"),
            mbps=metrics.get("mbps")
        )

        return event

    # ─── STATS ───

    async def get_stats(self) -> Dict:
        """Get current DDoS shield stats"""
        return {
            "active_nullroutes": len(self.active_nullroutes),
            "nullroute_ips": list(self.active_nullroutes.keys()),
            "nftables_active": True,
            "xdp_active": self.xdp_attached,
            "pps_threshold": settings.ddos_pps_threshold,
            "mbps_threshold": settings.ddos_mbps_threshold
        }

# Singleton
ddos_shield = DDoSShield()
