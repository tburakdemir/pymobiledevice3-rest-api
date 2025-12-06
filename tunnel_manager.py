import asyncio
import logging
from typing import Dict, Optional
from dataclasses import dataclass
import subprocess
import time
from pymobiledevice3.remote.remote_service_discovery import RemoteServiceDiscoveryService
from pymobiledevice3.tunneld.api import async_get_tunneld_devices
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
            # Get connected devices via tunneld - returns list of RSD objects
            rsd_list = await async_get_tunneld_devices()

            async with self._lock:
                current_udids = set()

                for rsd in rsd_list:
                    try:
                        # Get device UDID from the RSD - RSD has udid property directly
                        def get_udid():
                            return rsd.udid

                        udid = await asyncio.to_thread(get_udid)
                        current_udids.add(udid)

                        if udid not in self.tunnels:
                            # New device found, create tunnel
                            await self._create_tunnel_from_rsd(rsd, udid)
                        else:
                            # Update existing tunnel with new RSD if needed
                            tunnel = self.tunnels[udid]
                            if not tunnel.active:
                                tunnel.rsd = rsd
                                tunnel.active = True
                                tunnel.restart_count = 0

                    except Exception as e:
                        logger.error(f"Error processing RSD device: {e}")
                        continue

                # Remove tunnels for disconnected devices
                disconnected = set(self.tunnels.keys()) - current_udids
                for udid in disconnected:
                    logger.info(f"Device {udid} disconnected, removing tunnel")
                    tunnel = self.tunnels.pop(udid)
                    await self._close_tunnel(tunnel)

        except Exception as e:
            logger.error(f"Error discovering devices: {e}")
            logger.info("Make sure tunneld is running: sudo python3 -m pymobiledevice3 remote tunneld")

    async def _create_tunnel_from_rsd(self, rsd: RemoteServiceDiscoveryService, udid: str):
        """Create a new tunnel entry from an existing RSD object."""
        logger.info(f"Creating tunnel for device {udid}")

        try:
            # Extract connection info from RSD
            # RSD address is a tuple (host, port)
            address = getattr(rsd.service, 'address', ('localhost', 0))
            host = address[0] if isinstance(address, tuple) else 'localhost'
            port = address[1] if isinstance(address, tuple) else 0

            tunnel = TunnelInfo(
                udid=udid,
                host=host,
                port=port,
                rsd=rsd,
                last_check=time.time(),
                active=True,
            )

            self.tunnels[udid] = tunnel
            logger.info(f"Tunnel created for {udid} at {host}:{port}")

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

            # Try to ping the device by getting basic info from RSD
            def check_connection():
                try:
                    # RSD has udid property directly
                    _ = tunnel.rsd.udid
                    return True
                except:
                    return False

            result = await asyncio.to_thread(check_connection)
            if result:
                tunnel.last_check = time.time()
                return True
            return False

        except Exception as e:
            logger.debug(f"Tunnel health check failed for {tunnel.udid}: {e}")
            return False

    async def _restart_tunnel(self, tunnel: TunnelInfo):
        """Restart a crashed tunnel by rediscovering devices."""
        if tunnel.restart_count >= settings.tunnel_restart_max_attempts:
            logger.error(f"Max restart attempts reached for {tunnel.udid}, giving up")
            tunnel.active = False
            return

        tunnel.restart_count += 1
        logger.info(f"Restarting tunnel for {tunnel.udid} (attempt {tunnel.restart_count})")

        # Mark as inactive but don't remove
        tunnel.active = False

        # Wait before attempting rediscovery
        await asyncio.sleep(settings.tunnel_restart_delay)

        # Trigger device rediscovery which will recreate the tunnel
        # The discover_devices method will find the device again and update the tunnel
        logger.info(f"Triggering device rediscovery for {tunnel.udid}")

    def get_tunnel(self, udid: str) -> Optional[TunnelInfo]:
        """Get tunnel info for a specific device."""
        return self.tunnels.get(udid)

    def get_all_tunnels(self) -> Dict[str, TunnelInfo]:
        """Get all active tunnels."""
        return {udid: tunnel for udid, tunnel in self.tunnels.items() if tunnel.active}
