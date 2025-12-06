# pymobiledevice3 REST API

A REST API wrapper for [pymobiledevice3](https://github.com/doronz88/pymobiledevice3) that provides easy HTTP access to iOS device management features.

## Features

- **Automatic Device Discovery**: Automatically discovers and manages all connected iOS devices
- **RSD Tunnel Management**: Creates and maintains RemoteXPC tunnels for each device with automatic recovery
- **Device Information**: Get detailed information about connected devices
- **Performance Monitoring**: Monitor CPU and memory usage for devices and apps
- **App Management**: Launch apps remotely on connected devices
- **Location Simulation**: Set custom GPS coordinates for testing location-based features
- **Retry & Fallback**: Built-in retry mechanisms and tunnel crash recovery

## Prerequisites

- Python 3.8 or higher
- pymobiledevice3 installed and configured
- iOS devices connected and paired with your computer
- Remote Service Discovery (RSD) enabled on your iOS devices (iOS 17+)

## Installation

1. Clone the repository:
```bash
git clone https://github.com/yourusername/pymobiledevice3-rest-api.git
cd pymobiledevice3-rest-api
```

2. Create a virtual environment (recommended):
```bash
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. (Optional) Create a `.env` file from the example:
```bash
cp .env.example .env
```

## Configuration

Configuration can be done via environment variables or a `.env` file:

| Variable | Default | Description |
|----------|---------|-------------|
| `HOST` | `0.0.0.0` | Server host address |
| `PORT` | `8000` | Server port |
| `LOG_LEVEL` | `info` | Logging level (debug, info, warning, error) |
| `TUNNEL_CHECK_INTERVAL` | `30` | Interval in seconds to check tunnel health |
| `TUNNEL_RESTART_MAX_ATTEMPTS` | `3` | Maximum tunnel restart attempts |
| `TUNNEL_RESTART_DELAY` | `5` | Delay in seconds between restart attempts |
| `MAX_RETRIES` | `3` | Maximum retries for operations |
| `RETRY_DELAY` | `2` | Delay in seconds between retries |

## Usage

### Starting the Server

```bash
python main.py
```

The server will start on `http://localhost:8000` by default.

### API Documentation

Once the server is running, you can access:
- Interactive API docs: `http://localhost:8000/docs`
- Alternative API docs: `http://localhost:8000/redoc`

## API Endpoints

### GET /api/v1/devices

Get all connected devices with their information.

**Response:**
```json
{
  "00008030-001234567890ABCD": {
    "udid": "00008030-001234567890ABCD",
    "name": "iPhone 14 Pro",
    "product_type": "iPhone15,2",
    "product_version": "17.1.1",
    "rsd_host": "localhost",
    "rsd_port": 49152,
    "tunnel_active": true
  }
}
```

### GET /api/v1/devices/{udid}

Get information for a specific device.

**Response:**
```json
{
  "udid": "00008030-001234567890ABCD",
  "name": "iPhone 14 Pro",
  "product_type": "iPhone15,2",
  "product_version": "17.1.1",
  "rsd_host": "localhost",
  "rsd_port": 49152,
  "tunnel_active": true
}
```

### GET /api/v1/devices/{udid}/statistics

Get device CPU and memory statistics.

**Query Parameters:**
- `bundle_id` (optional): App bundle ID to get app-specific memory usage

**Example:**
```bash
curl "http://localhost:8000/api/v1/devices/00008030-001234567890ABCD/statistics?bundle_id=com.example.app"
```

**Response:**
```json
{
  "cpuUsage": 4.5,
  "totalMemoryUsage": 233.45,
  "appMemoryUsage": 21.3
}
```

### POST /api/v1/devices/{udid}/launch

Launch an app on the device.

**Request Body:**
```json
{
  "app": "com.example.app"
}
```

**Response:**
```json
{
  "status": "success",
  "message": "App com.example.app launched successfully on device 00008030-001234567890ABCD"
}
```

### POST /api/v1/devices/{udid}/location

Set a custom location on the device.

**Request Body:**
```json
{
  "latitude": 37.7749,
  "longitude": -122.4194
}
```

**Response:**
```json
{
  "status": "success",
  "message": "Location set to (37.7749, -122.4194) for device 00008030-001234567890ABCD"
}
```

### DELETE /api/v1/devices/{udid}/location

Clear the simulated location.

**Response:**
```json
{
  "status": "success",
  "message": "Location cleared for device 00008030-001234567890ABCD"
}
```

## Example Usage

### Using curl

```bash
# Get all devices
curl http://localhost:8000/api/v1/devices

# Get device statistics
curl http://localhost:8000/api/v1/devices/YOUR_UDID/statistics

# Launch an app
curl -X POST http://localhost:8000/api/v1/devices/YOUR_UDID/launch \
  -H "Content-Type: application/json" \
  -d '{"app": "com.apple.mobilesafari"}'

# Set location
curl -X POST http://localhost:8000/api/v1/devices/YOUR_UDID/location \
  -H "Content-Type: application/json" \
  -d '{"latitude": 37.7749, "longitude": -122.4194}'
```

### Using Python

```python
import requests

BASE_URL = "http://localhost:8000"

# Get all devices
response = requests.get(f"{BASE_URL}/api/v1/devices")
devices = response.json()

# Get first device UDID
udid = list(devices.keys())[0]

# Get statistics
stats = requests.get(
    f"{BASE_URL}/api/v1/devices/{udid}/statistics",
    params={"bundle_id": "com.example.app"}
).json()

print(f"CPU Usage: {stats['cpuUsage']}%")
print(f"Memory: {stats['totalMemoryUsage']} MB")

# Launch app
requests.post(
    f"{BASE_URL}/api/v1/devices/{udid}/launch",
    json={"app": "com.apple.mobilesafari"}
)

# Set location
requests.post(
    f"{BASE_URL}/api/v1/devices/{udid}/location",
    json={"latitude": 37.7749, "longitude": -122.4194}
)
```

## Architecture

### Components

1. **Tunnel Manager** (`tunnel_manager.py`):
   - Manages RSD tunnels for all connected devices
   - Monitors tunnel health and automatically restarts crashed tunnels
   - Handles device connection/disconnection

2. **Device Manager** (`device_manager.py`):
   - Provides high-level device operations
   - Implements retry logic for all operations
   - Handles communication with pymobiledevice3 services

3. **API** (`api.py`):
   - FastAPI application with REST endpoints
   - Request validation using Pydantic models
   - Error handling and HTTP responses

### Tunnel Recovery

The system includes robust tunnel management:
- Health checks every 30 seconds (configurable)
- Automatic tunnel restart on failure
- Up to 3 restart attempts (configurable)
- Exponential backoff for retries

## Troubleshooting

### No devices found

1. Ensure iOS devices are connected and unlocked
2. Check that devices are paired: `pymobiledevice3 pair`
3. Verify RSD is enabled (iOS 17+ required)
4. Start tunneld: `pymobiledevice3 remote tunneld`

### Tunnel crashes

- The system automatically recovers from tunnel crashes
- Check logs for detailed error messages
- Increase `TUNNEL_RESTART_MAX_ATTEMPTS` if needed

### Permission errors

- Ensure you have proper permissions to access USB devices
- On Linux, you may need to add udev rules for iOS devices

## Development

### Running in development mode

```bash
# With auto-reload
uvicorn api:app --reload --host 0.0.0.0 --port 8000
```

### Running tests

```bash
pytest
```

## License

MIT

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.