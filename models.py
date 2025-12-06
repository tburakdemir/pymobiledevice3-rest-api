from pydantic import BaseModel, Field
from typing import Optional, List


class DeviceInfo(BaseModel):
    """Device information model."""

    udid: str
    name: Optional[str] = None
    product_type: Optional[str] = None
    product_version: Optional[str] = None
    total_memory: Optional[int] = None
    rsd_host: str
    rsd_port: int
    tunnel_active: bool = True


class DeviceStatistics(BaseModel):
    """Device statistics model."""

    cpuUsage: float = Field(..., description="CPU usage in percentage")
    totalMemoryUsage: float = Field(..., description="Total memory usage in MB")
    batteryLevel: Optional[int] = Field(None, description="Battery level in percentage (0-100)")
    appCpuUsage: Optional[float] = Field(None, description="App CPU usage in percentage (if bundle_id provided)")
    appMemoryUsage: Optional[float] = Field(None, description="App memory usage in MB (if bundle_id provided)")


class LaunchAppRequest(BaseModel):
    """Request model for launching an app."""

    app: str = Field(..., description="Bundle ID of the app to launch")


class SetLocationRequest(BaseModel):
    """Request model for setting device location."""

    latitude: float = Field(..., description="Latitude coordinate")
    longitude: float = Field(..., description="Longitude coordinate")


class InstallAppRequest(BaseModel):
    """Request model for installing an app."""

    path: str = Field(..., description="Path to the IPA file to install")


class UninstallAppsRequest(BaseModel):
    """Request model for uninstalling apps."""

    bundle_ids: List[str] = Field(..., description="List of bundle IDs to uninstall")
