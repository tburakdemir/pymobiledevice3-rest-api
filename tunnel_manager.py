import asyncio
import logging
from typing import Dict, Optional
from dataclasses import dataclass
import subprocess
import time
from pymobiledevice3.remote.remote_service_discovery import RemoteServiceDiscoveryService
from pymobiledevice3.tunneld import get_tunneld_devices
from pymobiledevice3.exceptions import PyMobileDevice3Exception
from config import settings

logger = logging.getLogger(__name__)


@dataclass
class TunnelInfo:
    """Information about an RSD tunnel."""

    udid: str
    host: str
    port: int
    process: Optional[subprocess.Popen] = None
    rsd: Optional[RemoteServiceDiscoveryService] = None
    last_check: float = 0
    restart_count: int = 0
    active: bool = True


class TunnelManager:
    """Manages RSD tunnels for iOS devices."""

    def __init__(self):
        self.tunnels: Dict[str, TunnelInfo] = {}
        self._monitor_task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()
        self._running = False

    async def start(self):
        """Start the tunnel manager and discover devices."""
        logger.info("Starting tunnel manager...")
        self._running = True

        # Start monitoring task
        self._monitor_task = asyncio.create_task(self._monitor_tunnels())

        # Initial device discovery
        await self.discover_devices()

    async def stop(self):
        """Stop the tunnel manager and clean up resources."""
        logger.info("Stopping tunnel manager...")
        self._running = False

        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass

        # Close all tunnels
        async with self._lock:
            for tunnel in list(self.tunnels.values()):
                await self._close_tunnel(tunnel)

    async def discover_devices(self):
        """Discover connected iOS devices and start tunnels."""
        logger.info("Discovering devices...")

        try:
            # Get connected devices via tunneld
            devices = await asyncio.to_thread(get_tunneld_devices)

            async with self._lock:
                current_udids = set()

                for device_info in devices:
                    udid = device_info.udid
                    current_udids.add(udid)

                    if udid not in self.tunnels:
                        # New device found, create tunnel
                        await self._create_tunnel(device_info)
                    else:
                        # Update existing tunnel info
                        tunnel = self.tunnels[udid]
                        tunnel.host = device_info.hostname
                        tunnel.port = device_info.port

                # Remove tunnels for disconnected devices
                disconnected = set(self.tunnels.keys()) - current_udids
                for udid in disconnected:
                    logger.info(f"Device {udid} disconnected, removing tunnel")
                    tunnel = self.tunnels.pop(udid)
                    await self._close_tunnel(tunnel)

        except Exception as e:
            logger.error(f"Error discovering devices: {e}")

    async def _create_tunnel(self, device_info):
        """Create a new RSD tunnel for a device."""
        udid = device_info.udid
        logger.info(f"Creating tunnel for device {udid}")

        try:
            # Create RemoteServiceDiscoveryService
            rsd = RemoteServiceDiscoveryService((device_info.hostname, device_info.port))

            tunnel = TunnelInfo(
                udid=udid,
                host=device_info.hostname,
                port=device_info.port,
                rsd=rsd,
                last_check=time.time(),
                active=True,
            )

            self.tunnels[udid] = tunnel
            logger.info(f"Tunnel created for {udid} at {device_info.hostname}:{device_info.port}")

        except Exception as e:
            logger.error(f"Failed to create tunnel for {udid}: {e}")

    async def _close_tunnel(self, tunnel: TunnelInfo):
        """Close a tunnel and clean up resources."""
        logger.info(f"Closing tunnel for device {tunnel.udid}")

        try:
            if tunnel.rsd:
                await asyncio.to_thread(tunnel.rsd.close)
                tunnel.rsd = None

            if tunnel.process:
                tunnel.process.terminate()
                try:
                    tunnel.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    tunnel.process.kill()
                tunnel.process = None

        except Exception as e:
            logger.error(f"Error closing tunnel for {tunnel.udid}: {e}")

        tunnel.active = False

    async def _monitor_tunnels(self):
        """Monitor tunnels and restart if they crash."""
        while self._running:
            try:
                await asyncio.sleep(settings.tunnel_check_interval)

                async with self._lock:
                    for tunnel in list(self.tunnels.values()):
                        if not await self._check_tunnel_health(tunnel):
                            logger.warning(f"Tunnel for {tunnel.udid} is unhealthy, restarting...")
                            await self._restart_tunnel(tunnel)

                # Periodically rediscover devices
                await self.discover_devices()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in tunnel monitor: {e}")

    async def _check_tunnel_health(self, tunnel: TunnelInfo) -> bool:
        """Check if a tunnel is healthy."""
        try:
            # Check if RSD connection is still active
            if not tunnel.rsd:
                return False

            # Try to get device info to verify connection
            await asyncio.to_thread(lambda: tunnel.rsd.connect())
            tunnel.last_check = time.time()
            return True

        except Exception as e:
            logger.debug(f"Tunnel health check failed for {tunnel.udid}: {e}")
            return False

    async def _restart_tunnel(self, tunnel: TunnelInfo):
        """Restart a crashed tunnel."""
        if tunnel.restart_count >= settings.tunnel_restart_max_attempts:
            logger.error(f"Max restart attempts reached for {tunnel.udid}, giving up")
            tunnel.active = False
            return

        tunnel.restart_count += 1
        logger.info(f"Restarting tunnel for {tunnel.udid} (attempt {tunnel.restart_count})")

        # Close existing tunnel
        await self._close_tunnel(tunnel)

        # Wait before restarting
        await asyncio.sleep(settings.tunnel_restart_delay)

        # Recreate the tunnel
        try:
            rsd = RemoteServiceDiscoveryService((tunnel.host, tunnel.port))
            tunnel.rsd = rsd
            tunnel.active = True
            tunnel.last_check = time.time()
            logger.info(f"Tunnel restarted successfully for {tunnel.udid}")

        except Exception as e:
            logger.error(f"Failed to restart tunnel for {tunnel.udid}: {e}")
            tunnel.active = False

    def get_tunnel(self, udid: str) -> Optional[TunnelInfo]:
        """Get tunnel info for a specific device."""
        return self.tunnels.get(udid)

    def get_all_tunnels(self) -> Dict[str, TunnelInfo]:
        """Get all active tunnels."""
        return {udid: tunnel for udid, tunnel in self.tunnels.items() if tunnel.active}
