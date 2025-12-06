import logging
import asyncio
from typing import Optional, Dict
from tenacity import retry, stop_after_attempt, wait_exponential
from pymobiledevice3.services.dvt.dvt_secure_socket_proxy import DvtSecureSocketProxyService
from pymobiledevice3.services.dvt.instruments.process_control import ProcessControl
from pymobiledevice3.services.dvt.instruments.sysmontap import Sysmontap
from pymobiledevice3.services.simulate_location import DtSimulateLocation
from models import DeviceInfo, DeviceStatistics
from tunnel_manager import TunnelManager
from config import settings

logger = logging.getLogger(__name__)


class DeviceManager:
    """Manages iOS device operations."""

    def __init__(self, tunnel_manager: TunnelManager):
        self.tunnel_manager = tunnel_manager

    @retry(
        stop=stop_after_attempt(settings.max_retries),
        wait=wait_exponential(multiplier=settings.retry_delay, min=1, max=10),
        reraise=True,
    )
    async def get_device_info(self, udid: str) -> DeviceInfo:
        """Get detailed information about a device."""
        tunnel = self.tunnel_manager.get_tunnel(udid)
        if not tunnel or not tunnel.active:
            raise ValueError(f"Device {udid} not found or tunnel inactive")

        try:
            # Get device information from RSD (run in thread as it's blocking)
            def get_info():
                # RSD has all_values property directly
                return tunnel.rsd.all_values

            device_values = await asyncio.to_thread(get_info)

            return DeviceInfo(
                udid=udid,
                name=device_values.get("DeviceName"),
                product_type=device_values.get("ProductType"),
                product_version=device_values.get("ProductVersion"),
                rsd_host=tunnel.host,
                rsd_port=tunnel.port,
                tunnel_active=tunnel.active,
            )

        except Exception as e:
            logger.error(f"Error getting device info for {udid}: {e}")
            raise

    async def get_all_devices(self) -> Dict[str, DeviceInfo]:
        """Get information about all connected devices."""
        devices = {}

        for udid, tunnel in self.tunnel_manager.get_all_tunnels().items():
            try:
                device_info = await self.get_device_info(udid)
                devices[udid] = device_info
            except Exception as e:
                logger.error(f"Error getting info for device {udid}: {e}")
                # Include basic info even if detailed fetch fails
                devices[udid] = DeviceInfo(
                    udid=udid,
                    rsd_host=tunnel.host,
                    rsd_port=tunnel.port,
                    tunnel_active=tunnel.active,
                )

        return devices

    @retry(
        stop=stop_after_attempt(settings.max_retries),
        wait=wait_exponential(multiplier=settings.retry_delay, min=1, max=10),
        reraise=True,
    )
    async def get_device_statistics(
        self, udid: str, bundle_id: Optional[str] = None
    ) -> DeviceStatistics:
        """Get CPU and memory statistics for a device."""
        tunnel = self.tunnel_manager.get_tunnel(udid)
        if not tunnel or not tunnel.active:
            raise ValueError(f"Device {udid} not found or tunnel inactive")

        try:
            # Get system statistics using Sysmontap (run in thread as it's blocking)
            def get_stats():
                # Create DVT secure socket proxy for DVT instruments
                dvt = DvtSecureSocketProxyService(tunnel.rsd)
                dvt.perform_handshake()

                with Sysmontap(dvt) as sysmontap:
                    # Use raw iterator to get both system and process data
                    # The first sample doesn't have reliable values,
                    # so we need to skip it and use the second sample
                    raw_iter = iter(sysmontap)

                    # Skip first sample (uninitialized values)
                    next(raw_iter)

                    # Get second sample with accurate data
                    row = next(raw_iter)

                    # Extract system-level CPU usage (0-100%)
                    system_cpu_usage = 0.0
                    if "SystemCPUUsage" in row:
                        system_cpu = row["SystemCPUUsage"]
                        # SystemCPUUsage contains 'CPU_TotalLoad' which is 0-100%
                        system_cpu_usage = system_cpu.get("CPU_TotalLoad", 0.0)

                    # Calculate total memory and app-specific stats from processes
                    total_memory_mb = 0.0
                    app_cpu_usage = None
                    app_memory_mb = None

                    if "Processes" in row:
                        processes = row["Processes"]
                        for _pid, process_info in processes.items():
                            # Convert process_info tuple to dict using attribute names
                            process = dict(
                                zip(
                                    sysmontap.process_attributes_cls.__dataclass_fields__.keys(),
                                    process_info,
                                )
                            )

                            # Use physFootprint for physical memory usage
                            memory_bytes = process.get("physFootprint") or 0
                            total_memory_mb += memory_bytes / (1024 * 1024)

                            # If bundle_id is specified, get app-specific stats
                            if bundle_id and process.get("name") == bundle_id:
                                app_cpu_usage = process.get("cpuUsage") or 0.0
                                app_memory_mb = memory_bytes / (1024 * 1024)

                    return system_cpu_usage, total_memory_mb, app_cpu_usage, app_memory_mb

            cpu_usage, total_memory_mb, app_cpu_usage, app_memory_mb = await asyncio.to_thread(get_stats)

            return DeviceStatistics(
                cpuUsage=round(cpu_usage, 2),
                totalMemoryUsage=round(total_memory_mb, 2),
                appCpuUsage=round(app_cpu_usage, 2) if app_cpu_usage is not None else None,
                appMemoryUsage=round(app_memory_mb, 2) if app_memory_mb is not None else None,
            )

        except Exception as e:
            logger.error(f"Error getting statistics for {udid}: {e}")
            raise

    @retry(
        stop=stop_after_attempt(settings.max_retries),
        wait=wait_exponential(multiplier=settings.retry_delay, min=1, max=10),
        reraise=True,
    )
    async def launch_app(self, udid: str, bundle_id: str) -> bool:
        """Launch an app on a device."""
        tunnel = self.tunnel_manager.get_tunnel(udid)
        if not tunnel or not tunnel.active:
            raise ValueError(f"Device {udid} not found or tunnel inactive")

        try:
            # Use ProcessControl to launch the app (run in thread as it's blocking)
            def launch():
                # Create DVT secure socket proxy for DVT instruments
                dvt = DvtSecureSocketProxyService(tunnel.rsd)
                dvt.perform_handshake()

                with ProcessControl(dvt) as process_control:
                    pid = process_control.launch(
                        bundle_id=bundle_id,
                        arguments=[],
                        kill_existing=True,
                        start_suspended=False,
                        environment={},
                    )
                    return pid

            pid = await asyncio.to_thread(launch)

            if pid:
                logger.info(f"Successfully launched {bundle_id} on {udid} with PID {pid}")
                return True
            else:
                logger.error(f"Failed to launch {bundle_id} on {udid}")
                return False

        except Exception as e:
            logger.error(f"Error launching app {bundle_id} on {udid}: {e}")
            raise

    @retry(
        stop=stop_after_attempt(settings.max_retries),
        wait=wait_exponential(multiplier=settings.retry_delay, min=1, max=10),
        reraise=True,
    )
    async def set_location(self, udid: str, latitude: float, longitude: float) -> bool:
        """Set the location for a device."""
        tunnel = self.tunnel_manager.get_tunnel(udid)
        if not tunnel or not tunnel.active:
            raise ValueError(f"Device {udid} not found or tunnel inactive")

        try:
            # Use DtSimulateLocation to set the location (run in thread as it's blocking)
            def set_loc():
                dt_simulate = DtSimulateLocation(tunnel.rsd)
                dt_simulate.set(latitude, longitude)

            await asyncio.to_thread(set_loc)

            logger.info(f"Successfully set location for {udid} to ({latitude}, {longitude})")
            return True

        except Exception as e:
            logger.error(f"Error setting location for {udid}: {e}")
            raise

    @retry(
        stop=stop_after_attempt(settings.max_retries),
        wait=wait_exponential(multiplier=settings.retry_delay, min=1, max=10),
        reraise=True,
    )
    async def clear_location(self, udid: str) -> bool:
        """Clear the simulated location for a device."""
        tunnel = self.tunnel_manager.get_tunnel(udid)
        if not tunnel or not tunnel.active:
            raise ValueError(f"Device {udid} not found or tunnel inactive")

        try:
            # Clear simulated location (run in thread as it's blocking)
            def clear_loc():
                dt_simulate = DtSimulateLocation(tunnel.rsd)
                dt_simulate.clear()

            await asyncio.to_thread(clear_loc)

            logger.info(f"Successfully cleared location for {udid}")
            return True

        except Exception as e:
            logger.error(f"Error clearing location for {udid}: {e}")
            raise
