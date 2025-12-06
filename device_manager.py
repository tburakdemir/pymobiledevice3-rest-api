import logging
import asyncio
from typing import Optional, Dict
from tenacity import retry, stop_after_attempt, wait_exponential
from pymobiledevice3.services.dvt.dvt_secure_socket_proxy import DvtSecureSocketProxyService
from pymobiledevice3.services.dvt.instruments.process_control import ProcessControl
from pymobiledevice3.services.dvt.instruments.sysmontap import Sysmontap
from pymobiledevice3.services.simulate_location import DtSimulateLocation
from pymobiledevice3.services.diagnostics import DiagnosticsService
from models import DeviceInfo, DeviceStatistics
from tunnel_manager import TunnelManager
from config import settings

logger = logging.getLogger(__name__)

# iPhone model to total memory mapping (in bytes)
# Sources: https://9to5mac.com/2023/11/18/iphone-ram-list/
#          https://www.gsmarena.com/
#          https://gist.github.com/adamawolf/3048717
IPHONE_MEMORY_MAP: Dict[str, int] = {
    # iPhone (2007) - 128 MB
    "iPhone1,1": 128 * 1024 * 1024,
    # iPhone 3G - 128 MB
    "iPhone1,2": 128 * 1024 * 1024,
    # iPhone 3GS - 256 MB
    "iPhone2,1": 256 * 1024 * 1024,
    # iPhone 4 - 512 MB
    "iPhone3,1": 512 * 1024 * 1024,
    "iPhone3,2": 512 * 1024 * 1024,
    "iPhone3,3": 512 * 1024 * 1024,
    # iPhone 4S - 512 MB
    "iPhone4,1": 512 * 1024 * 1024,
    # iPhone 5 - 1 GB
    "iPhone5,1": 1 * 1024 * 1024 * 1024,
    "iPhone5,2": 1 * 1024 * 1024 * 1024,
    # iPhone 5C - 1 GB
    "iPhone5,3": 1 * 1024 * 1024 * 1024,
    "iPhone5,4": 1 * 1024 * 1024 * 1024,
    # iPhone 5S - 1 GB
    "iPhone6,1": 1 * 1024 * 1024 * 1024,
    "iPhone6,2": 1 * 1024 * 1024 * 1024,
    # iPhone 6 - 1 GB
    "iPhone7,2": 1 * 1024 * 1024 * 1024,
    # iPhone 6 Plus - 1 GB
    "iPhone7,1": 1 * 1024 * 1024 * 1024,
    # iPhone 6s - 2 GB
    "iPhone8,1": 2 * 1024 * 1024 * 1024,
    # iPhone 6s Plus - 2 GB
    "iPhone8,2": 2 * 1024 * 1024 * 1024,
    # iPhone SE (1st gen) - 2 GB
    "iPhone8,4": 2 * 1024 * 1024 * 1024,
    # iPhone 7 - 2 GB
    "iPhone9,1": 2 * 1024 * 1024 * 1024,
    "iPhone9,3": 2 * 1024 * 1024 * 1024,
    # iPhone 7 Plus - 3 GB
    "iPhone9,2": 3 * 1024 * 1024 * 1024,
    "iPhone9,4": 3 * 1024 * 1024 * 1024,
    # iPhone 8 - 2 GB
    "iPhone10,1": 2 * 1024 * 1024 * 1024,
    "iPhone10,4": 2 * 1024 * 1024 * 1024,
    # iPhone 8 Plus - 3 GB
    "iPhone10,2": 3 * 1024 * 1024 * 1024,
    "iPhone10,5": 3 * 1024 * 1024 * 1024,
    # iPhone X - 3 GB
    "iPhone10,3": 3 * 1024 * 1024 * 1024,
    "iPhone10,6": 3 * 1024 * 1024 * 1024,
    # iPhone XS - 4 GB
    "iPhone11,2": 4 * 1024 * 1024 * 1024,
    # iPhone XS Max - 4 GB
    "iPhone11,4": 4 * 1024 * 1024 * 1024,
    "iPhone11,6": 4 * 1024 * 1024 * 1024,
    # iPhone XR - 3 GB
    "iPhone11,8": 3 * 1024 * 1024 * 1024,
    # iPhone 11 - 4 GB
    "iPhone12,1": 4 * 1024 * 1024 * 1024,
    # iPhone 11 Pro - 4 GB
    "iPhone12,3": 4 * 1024 * 1024 * 1024,
    # iPhone 11 Pro Max - 4 GB
    "iPhone12,5": 4 * 1024 * 1024 * 1024,
    # iPhone SE (2nd gen) - 3 GB
    "iPhone12,8": 3 * 1024 * 1024 * 1024,
    # iPhone 12 mini - 4 GB
    "iPhone13,1": 4 * 1024 * 1024 * 1024,
    # iPhone 12 - 4 GB
    "iPhone13,2": 4 * 1024 * 1024 * 1024,
    # iPhone 12 Pro - 6 GB
    "iPhone13,3": 6 * 1024 * 1024 * 1024,
    # iPhone 12 Pro Max - 6 GB
    "iPhone13,4": 6 * 1024 * 1024 * 1024,
    # iPhone 13 Pro - 6 GB
    "iPhone14,2": 6 * 1024 * 1024 * 1024,
    # iPhone 13 Pro Max - 6 GB
    "iPhone14,3": 6 * 1024 * 1024 * 1024,
    # iPhone 13 mini - 4 GB
    "iPhone14,4": 4 * 1024 * 1024 * 1024,
    # iPhone 13 - 4 GB
    "iPhone14,5": 4 * 1024 * 1024 * 1024,
    # iPhone SE (3rd gen) - 4 GB
    "iPhone14,6": 4 * 1024 * 1024 * 1024,
    # iPhone 14 - 6 GB
    "iPhone14,7": 6 * 1024 * 1024 * 1024,
    # iPhone 14 Plus - 6 GB
    "iPhone14,8": 6 * 1024 * 1024 * 1024,
    # iPhone 14 Pro - 6 GB
    "iPhone15,2": 6 * 1024 * 1024 * 1024,
    # iPhone 14 Pro Max - 6 GB
    "iPhone15,3": 6 * 1024 * 1024 * 1024,
    # iPhone 15 - 6 GB
    "iPhone15,4": 6 * 1024 * 1024 * 1024,
    # iPhone 15 Plus - 6 GB
    "iPhone15,5": 6 * 1024 * 1024 * 1024,
    # iPhone 15 Pro - 8 GB
    "iPhone16,1": 8 * 1024 * 1024 * 1024,
    # iPhone 15 Pro Max - 8 GB
    "iPhone16,2": 8 * 1024 * 1024 * 1024,
    # iPhone 16 Pro - 8 GB
    "iPhone17,1": 8 * 1024 * 1024 * 1024,
    # iPhone 16 Pro Max - 8 GB
    "iPhone17,2": 8 * 1024 * 1024 * 1024,
    # iPhone 16 - 8 GB
    "iPhone17,3": 8 * 1024 * 1024 * 1024,
    # iPhone 16 Plus - 8 GB
    "iPhone17,4": 8 * 1024 * 1024 * 1024,
    # iPhone 16e - 8 GB
    "iPhone17,5": 8 * 1024 * 1024 * 1024,
    # iPhone 17 Pro - 12 GB
    "iPhone18,1": 12 * 1024 * 1024 * 1024,
    # iPhone 17 Pro Max - 12 GB
    "iPhone18,2": 12 * 1024 * 1024 * 1024,
    # iPhone 17 - 12 GB
    "iPhone18,3": 12 * 1024 * 1024 * 1024,
    # iPhone 17 Air - 12 GB
    "iPhone18,4": 12 * 1024 * 1024 * 1024,
}


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
            product_type = device_values.get("ProductType")
            total_memory = IPHONE_MEMORY_MAP.get(product_type)

            return DeviceInfo(
                udid=udid,
                name=device_values.get("DeviceName"),
                product_type=product_type,
                product_version=device_values.get("ProductVersion"),
                total_memory=total_memory,
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
        """Get CPU, memory, and battery statistics for a device."""
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
                    # Use iter_processes() to get process snapshots
                    # The first sample doesn't have reliable cpuUsage values,
                    # so we need to skip it and use the second sample
                    process_iter = sysmontap.iter_processes()

                    # Skip first sample (uninitialized cpuUsage values)
                    next(process_iter)

                    # Get second sample with accurate CPU data
                    processes = next(process_iter)

                    # Calculate total CPU usage
                    cpu_usage = 0.0
                    total_memory_mb = 0.0
                    app_cpu_usage = None
                    app_memory_mb = None

                    # Sum up CPU and memory from all processes
                    for process in processes:
                        process_cpu = process.get("cpuUsage") or 0.0
                        cpu_usage += process_cpu
                        # Use physFootprint for physical memory usage
                        memory_bytes = process.get("physFootprint") or 0
                        total_memory_mb += memory_bytes / (1024 * 1024)

                        # If bundle_id is specified, get app-specific stats
                        if bundle_id and process.get("name") == bundle_id:
                            app_cpu_usage = process_cpu
                            app_memory_mb = memory_bytes / (1024 * 1024)

                    return cpu_usage, total_memory_mb, app_cpu_usage, app_memory_mb

            # Get battery level using DiagnosticsService
            def get_battery():
                try:
                    diagnostics = DiagnosticsService(tunnel.rsd)
                    battery_info = diagnostics.get_battery()
                    # Battery info is a list of power sources, get the first one
                    if battery_info and len(battery_info) > 0:
                        power_source = battery_info[0]
                        # CurrentCapacity is the battery level percentage
                        return power_source.get("CurrentCapacity")
                    return None
                except Exception as e:
                    logger.warning(f"Could not get battery level for {udid}: {e}")
                    return None

            cpu_usage, total_memory_mb, app_cpu_usage, app_memory_mb = await asyncio.to_thread(get_stats)
            battery_level = await asyncio.to_thread(get_battery)

            return DeviceStatistics(
                cpuUsage=round(cpu_usage, 2),
                totalMemoryUsage=round(total_memory_mb, 2),
                batteryLevel=battery_level,
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
