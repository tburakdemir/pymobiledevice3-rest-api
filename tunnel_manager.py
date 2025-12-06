import asyncio
import logging
from typing import Dict, Optional, Union
from dataclasses import dataclass, field
import subprocess
import time
from pymobiledevice3.remote.remote_service_discovery import RemoteServiceDiscoveryService
from pymobiledevice3.tunneld.api import async_get_tunneld_devices
from pymobiledevice3.lockdown import LockdownClient, create_using_usbmux
from pymobiledevice3.usbmux import list_devices
from pymobiledevice3.exceptions import PyMobileDevice3Exception
from config import settings

logger = logging.getLogger(__name__)


@dataclass
class TunnelInfo:
    """Information about a device connection (RSD tunnel for iOS 17+ or lockdown for older)."""

    udid: str
    host: str
    port: int
    process: Optional[subprocess.Popen] = None
    rsd: Optional[RemoteServiceDiscoveryService] = None
    lockdown: Optional[LockdownClient] = None
    ios_version: Optional[str] = None
    last_check: float = 0
    restart_count: int = 0
    active: bool = True

    @property
    def is_ios17_or_newer(self) -> bool:
        """Check if device is running iOS 17 or newer."""
        if not self.ios_version:
            # If we have RSD but no lockdown, assume iOS 17+
            return self.rsd is not None and self.lockdown is None
        try:
            major_version = int(self.ios_version.split('.')[0])
            return major_version >= 17
        except (ValueError, IndexError):
            return self.rsd is not None


class TunnelManager:
    """Manages device connections for iOS devices.

    Supports both:
    - RSD tunnels for iOS 17+ devices
    - Lockdown connections for older iOS devices (< iOS 17)
    """

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
        """Discover connected iOS devices (both iOS 17+ via tunneld and older via usbmux)."""
        logger.info("Discovering devices...")

        current_udids = set()

        # First, try to discover iOS 17+ devices via tunneld
        await self._discover_rsd_devices(current_udids)

        # Then, discover older iOS devices via usbmux (that aren't already found via RSD)
        await self._discover_lockdown_devices(current_udids)

        # Remove tunnels for disconnected devices
        async with self._lock:
            disconnected = set(self.tunnels.keys()) - current_udids
            for udid in disconnected:
                logger.info(f"Device {udid} disconnected, removing tunnel")
                tunnel = self.tunnels.pop(udid)
                await self._close_tunnel(tunnel)

    async def _discover_rsd_devices(self, current_udids: set):
        """Discover iOS 17+ devices via tunneld/RSD."""
        try:
            rsd_list = await async_get_tunneld_devices()

            async with self._lock:
                for rsd in rsd_list:
                    try:
                        def get_udid():
                            return rsd.udid

                        udid = await asyncio.to_thread(get_udid)
                        current_udids.add(udid)

                        if udid not in self.tunnels:
                            await self._create_tunnel_from_rsd(rsd, udid)
                        else:
                            tunnel = self.tunnels[udid]
                            if not tunnel.active:
                                tunnel.rsd = rsd
                                tunnel.active = True
                                tunnel.restart_count = 0

                    except Exception as e:
                        logger.error(f"Error processing RSD device: {e}")
                        continue

        except Exception as e:
            logger.debug(f"No iOS 17+ devices via tunneld: {e}")

    async def _discover_lockdown_devices(self, current_udids: set):
        """Discover older iOS devices (< iOS 17) via usbmux/lockdown."""
        try:
            def get_usbmux_devices():
                return list_devices()

            devices = await asyncio.to_thread(get_usbmux_devices)

            async with self._lock:
                for device in devices:
                    try:
                        udid = device.serial

                        # Skip if already discovered via RSD (iOS 17+)
                        if udid in current_udids:
                            continue

                        current_udids.add(udid)

                        if udid not in self.tunnels:
                            await self._create_tunnel_from_lockdown(udid)
                        else:
                            tunnel = self.tunnels[udid]
                            if not tunnel.active and tunnel.lockdown is None:
                                # Try to reconnect via lockdown
                                await self._create_tunnel_from_lockdown(udid)

                    except Exception as e:
                        logger.error(f"Error processing usbmux device {device.serial}: {e}")
                        continue

        except Exception as e:
            logger.debug(f"No older iOS devices via usbmux: {e}")

    async def _create_tunnel_from_rsd(self, rsd: RemoteServiceDiscoveryService, udid: str):
        """Create a new tunnel entry from an existing RSD object (iOS 17+)."""
        logger.info(f"Creating RSD tunnel for device {udid} (iOS 17+)")

        try:
            # Extract connection info from RSD
            address = getattr(rsd.service, 'address', ('localhost', 0))
            host = address[0] if isinstance(address, tuple) else 'localhost'
            port = address[1] if isinstance(address, tuple) else 0

            # Get iOS version from RSD
            def get_ios_version():
                try:
                    return rsd.all_values.get('ProductVersion')
                except Exception:
                    return None

            ios_version = await asyncio.to_thread(get_ios_version)

            tunnel = TunnelInfo(
                udid=udid,
                host=host,
                port=port,
                rsd=rsd,
                ios_version=ios_version,
                last_check=time.time(),
                active=True,
            )

            self.tunnels[udid] = tunnel
            logger.info(f"RSD tunnel created for {udid} at {host}:{port} (iOS {ios_version})")

        except Exception as e:
            logger.error(f"Failed to create RSD tunnel for {udid}: {e}")

    async def _create_tunnel_from_lockdown(self, udid: str):
        """Create a new tunnel entry from lockdown connection (older iOS < 17)."""
        logger.info(f"Creating lockdown connection for device {udid} (older iOS)")

        try:
            def create_lockdown():
                lockdown = create_using_usbmux(serial=udid)
                ios_version = lockdown.product_version
                return lockdown, ios_version

            lockdown, ios_version = await asyncio.to_thread(create_lockdown)

            tunnel = TunnelInfo(
                udid=udid,
                host='localhost',
                port=0,
                lockdown=lockdown,
                ios_version=ios_version,
                last_check=time.time(),
                active=True,
            )

            self.tunnels[udid] = tunnel
            logger.info(f"Lockdown connection created for {udid} (iOS {ios_version})")

        except Exception as e:
            logger.error(f"Failed to create lockdown connection for {udid}: {e}")

    async def _close_tunnel(self, tunnel: TunnelInfo):
        """Close a tunnel and clean up resources."""
        logger.info(f"Closing tunnel for device {tunnel.udid}")

        try:
            if tunnel.rsd:
                await asyncio.to_thread(tunnel.rsd.close)
                tunnel.rsd = None

            if tunnel.lockdown:
                # Lockdown clients don't have a close method, just clear the reference
                tunnel.lockdown = None

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
        """Check if a tunnel/connection is healthy."""
        try:
            # Check RSD connection (iOS 17+)
            if tunnel.rsd:
                def check_rsd():
                    try:
                        _ = tunnel.rsd.udid
                        return True
                    except Exception:
                        return False

                result = await asyncio.to_thread(check_rsd)
                if result:
                    tunnel.last_check = time.time()
                    return True
                return False

            # Check lockdown connection (older iOS)
            if tunnel.lockdown:
                def check_lockdown():
                    try:
                        _ = tunnel.lockdown.udid
                        return True
                    except Exception:
                        return False

                result = await asyncio.to_thread(check_lockdown)
                if result:
                    tunnel.last_check = time.time()
                    return True
                return False

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
