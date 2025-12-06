from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse, Response
from typing import Dict, Optional, List, Any
import logging
from contextlib import asynccontextmanager

from models import (
    DeviceInfo,
    DeviceStatistics,
    LaunchAppRequest,
    SetLocationRequest,
    InstallAppRequest,
    UninstallAppsRequest,
)
from tunnel_manager import TunnelManager
from device_manager import DeviceManager
from config import settings

logger = logging.getLogger(__name__)

# Global instances
tunnel_manager: Optional[TunnelManager] = None
device_manager: Optional[DeviceManager] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifespan."""
    global tunnel_manager, device_manager

    # Startup
    logger.info("Starting pymobiledevice3 REST API...")

    tunnel_manager = TunnelManager()
    device_manager = DeviceManager(tunnel_manager)

    await tunnel_manager.start()
    logger.info("Application started successfully")

    yield

    # Shutdown
    logger.info("Shutting down...")
    if tunnel_manager:
        await tunnel_manager.stop()
    logger.info("Application shut down successfully")


# Create FastAPI app
app = FastAPI(
    title="pymobiledevice3 REST API",
    description="REST API wrapper for pymobiledevice3 to manage iOS devices",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "name": "pymobiledevice3 REST API",
        "version": "1.0.0",
        "status": "running",
    }


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy"}


@app.get("/api/v1/devices", response_model=Dict[str, DeviceInfo])
async def get_devices():
    """
    Get all connected iOS devices with their information.

    Returns:
        Dictionary mapping UDIDs to device information including:
        - udid: Device UDID
        - name: Device name
        - product_type: Product type (e.g., iPhone14,2)
        - product_version: iOS version
        - total_memory: Total device memory in bytes
        - rsd_host: RSD tunnel host
        - rsd_port: RSD tunnel port
        - tunnel_active: Whether the tunnel is active
    """
    try:
        devices = await device_manager.get_all_devices()
        return devices
    except Exception as e:
        logger.error(f"Error getting devices: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get devices: {str(e)}")


@app.get("/api/v1/devices/{udid}", response_model=DeviceInfo)
async def get_device(udid: str):
    """
    Get information for a specific device by UDID.

    Args:
        udid: Device UDID

    Returns:
        Device information including:
        - udid: Device UDID
        - name: Device name
        - product_type: Product type
        - product_version: iOS version
        - total_memory: Total device memory in bytes
        - rsd_host: RSD tunnel host
        - rsd_port: RSD tunnel port
        - tunnel_active: Whether the tunnel is active
    """
    try:
        device_info = await device_manager.get_device_info(udid)
        return device_info
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error getting device {udid}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get device: {str(e)}")


@app.get("/api/v1/devices/{udid}/statistics", response_model=DeviceStatistics)
async def get_device_statistics(
    udid: str,
    bundle_id: Optional[str] = Query(None, description="Bundle ID to get app-specific statistics"),
):
    """
    Get device CPU, memory, and battery statistics.

    Args:
        udid: Device UDID
        bundle_id: Optional bundle ID to get app-specific statistics

    Returns:
        Statistics including:
        - cpuUsage: CPU usage in percentage
        - totalMemoryUsage: Total memory usage in MB
        - batteryLevel: Battery level in percentage (0-100)
        - appCpuUsage: App CPU usage in percentage (if bundle_id provided)
        - appMemoryUsage: App memory usage in MB (if bundle_id provided)
    """
    try:
        stats = await device_manager.get_device_statistics(udid, bundle_id)
        return stats
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error getting statistics for {udid}: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to get device statistics: {str(e)}"
        )


@app.post("/api/v1/devices/{udid}/launch")
async def launch_app(udid: str, request: LaunchAppRequest):
    """
    Launch an app on a device.

    Args:
        udid: Device UDID
        request: Request body containing:
            - app: Bundle ID of the app to launch

    Returns:
        Success message
    """
    try:
        success = await device_manager.launch_app(udid, request.app)

        if success:
            return {
                "status": "success",
                "message": f"App {request.app} launched successfully on device {udid}",
            }
        else:
            raise HTTPException(
                status_code=500, detail=f"Failed to launch app {request.app}"
            )

    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error launching app on {udid}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to launch app: {str(e)}")


@app.post("/api/v1/devices/{udid}/location")
async def set_location(udid: str, request: SetLocationRequest):
    """
    Set the location for a device.

    Args:
        udid: Device UDID
        request: Request body containing:
            - latitude: Latitude coordinate
            - longitude: Longitude coordinate

    Returns:
        Success message
    """
    try:
        success = await device_manager.set_location(
            udid, request.latitude, request.longitude
        )

        if success:
            return {
                "status": "success",
                "message": f"Location set to ({request.latitude}, {request.longitude}) for device {udid}",
            }
        else:
            raise HTTPException(status_code=500, detail="Failed to set location")

    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error setting location for {udid}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to set location: {str(e)}")


@app.delete("/api/v1/devices/{udid}/location")
async def clear_location(udid: str):
    """
    Clear the simulated location for a device.

    Args:
        udid: Device UDID

    Returns:
        Success message
    """
    try:
        success = await device_manager.clear_location(udid)

        if success:
            return {
                "status": "success",
                "message": f"Location cleared for device {udid}",
            }
        else:
            raise HTTPException(status_code=500, detail="Failed to clear location")

    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error clearing location for {udid}: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to clear location: {str(e)}"
        )


@app.get("/api/v1/devices/{udid}/apps", response_model=Dict[str, Any])
async def list_apps(udid: str):
    """
    List all installed apps on a device.

    Args:
        udid: Device UDID

    Returns:
        List of installed apps with their details
    """
    try:
        apps = await device_manager.list_apps(udid)
        return apps

    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error listing apps on {udid}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to list apps: {str(e)}")


@app.post("/api/v1/devices/{udid}/apps")
async def install_app(udid: str, request: InstallAppRequest):
    """
    Install an IPA on a device.

    Args:
        udid: Device UDID
        request: Request body containing:
            - path: Path to the IPA file to install

    Returns:
        Success message
    """
    try:
        success = await device_manager.install_app(udid, request.path)

        if success:
            return {
                "status": "success",
                "message": f"App installed successfully from {request.path} on device {udid}",
            }
        else:
            raise HTTPException(status_code=500, detail="Failed to install app")

    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error installing app on {udid}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to install app: {str(e)}")


@app.delete("/api/v1/devices/{udid}/apps")
async def uninstall_apps(udid: str, request: UninstallAppsRequest):
    """
    Uninstall apps from a device.

    Args:
        udid: Device UDID
        request: Request body containing:
            - bundle_ids: List of bundle IDs to uninstall

    Returns:
        Results for each bundle ID (success/failure)
    """
    try:
        results = await device_manager.uninstall_apps(udid, request.bundle_ids)

        failed = [bid for bid, success in results.items() if not success]
        if failed:
            return {
                "status": "partial",
                "message": f"Some apps failed to uninstall: {', '.join(failed)}",
                "results": results,
            }

        return {
            "status": "success",
            "message": f"All apps uninstalled successfully from device {udid}",
            "results": results,
        }

    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error uninstalling apps on {udid}: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to uninstall apps: {str(e)}"
        )


@app.post("/api/v1/devices/{udid}/screenshot")
async def take_screenshot(udid: str):
    """
    Take a screenshot of the device screen.

    Args:
        udid: Device UDID

    Returns:
        PNG image data
    """
    try:
        image_bytes = await device_manager.get_screenshot(udid)

        return Response(
            content=image_bytes,
            media_type="image/png",
        )

    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error taking screenshot on {udid}: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to take screenshot: {str(e)}"
        )
