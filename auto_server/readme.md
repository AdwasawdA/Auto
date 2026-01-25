# Robot Car Camera Service

Camera and web interface for the robot car. Captures video, sends frames to inference server, displays video with detection overlays.

## Features

- **Camera capture** - Works with PiCamera2 (Raspberry Pi) or USB cameras
- **MJPEG streaming** - Low-latency video to web browser
- **Inference integration** - Sends frames to remote YOLO inference server
- **Real-time overlay** - Bounding boxes drawn on video feed
- **Metrics display** - Shows inference time, render time, and total latency
- **Toggle controls** - Enable/disable bounding box overlay
- **Responsive web UI** - Works on desktop and mobile

## System Requirements

### Raspberry Pi 4
- Raspberry Pi OS (64-bit recommended)
- PiCamera or USB camera
- 2GB+ RAM
- WiFi connection to local network

### Other platforms
- Python 3.10+
- USB camera or compatible video device
- Network connection

## Installation

### 1. Install system dependencies (Raspberry Pi)

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install camera dependencies
sudo apt install -y python3-picamera2 python3-libcamera

# Install OpenCV dependencies
sudo apt install -y python3-opencv libopencv-dev
```

### 2. Install Python dependencies with uv

```bash
# Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# Clone or create project directory
cd robot-car-service

# Install all dependencies
uv sync
```

### 3. Configure settings

```bash
# Copy example config
cp .env.example .env

# Edit configuration
nano .env
```

**Important:** Update `INFERENCE_SERVER_URL` with your PC/Jetson IP address:
```bash
INFERENCE_SERVER_URL=ws://192.168.1.100:8765
```

Find your PC's IP with `ip addr` (Linux) or `ipconfig` (Windows).

## Usage

### Start the service

```bash
# With uv
uv run python app.py

# Or activate venv first
source .venv/bin/activate
python app.py
```

The service will:
1. Initialize camera
2. Connect to inference server (if available)
3. Start web server on port 5000

### Access the web interface

Open browser and navigate to:
```
http://<robot-ip>:5000
```

Find robot IP with:
```bash
hostname -I
```

### Controls

- **Show Bounding Boxes** - Toggle detection overlay on/off
- **Metrics** - Real-time display of:
  - Inference Time: Time spent on YOLO detection
  - Render Time: Time to draw bounding boxes
  - Total Latency: End-to-end frame processing time

## Project Structure

```
robot-car-service/
├── pyproject.toml          # Dependencies
├── .env.example            # Config template
├── README.md               # This file
├── app.py                  # Flask web application
├── camera_service.py       # Camera capture and inference client
└── templates/
    └── index.html          # Web UI
```

## Configuration Options

### In app.py

```python
# Inference server URL (update with your PC IP)
INFERENCE_SERVER_URL = "ws://192.168.1.100:8765"
```

### Camera settings

```python
resolution = (640, 480)  # Width x Height
fps = 20                  # Frames per second
```

Higher resolution improves detection quality but increases bandwidth and processing time.

### Video quality

```python
JPEG_QUALITY = 85  # 0-100 (higher = better quality, larger size)
```

## Troubleshooting

### Camera not detected

**PiCamera:**
```bash
# Check camera is enabled
sudo raspi-config
# Interface Options > Camera > Enable

# Test camera
libcamera-hello
```

**USB Camera:**
```bash
# List video devices
ls /dev/video*

# Test with OpenCV
python -c "import cv2; print(cv2.VideoCapture(0).read())"
```

### Cannot connect to inference server

**Check network connectivity:**
```bash
# Ping PC
ping 192.168.1.100

# Check if port is open
nc -zv 192.168.1.100 8765
```

**Verify inference server is running:**
- Check inference server logs
- Ensure port 8765 is not blocked by firewall

**Camera works but no inference:**
- Service will run in "camera-only" mode
- Video will display without bounding boxes
- Status will show "Camera Only"

### High latency

**Reduce video resolution:**
```python
resolution = (416, 416)  # Smaller resolution
```

**Lower frame rate:**
```python
fps = 15  # Send fewer frames to inference
```

**Check network quality:**
```bash
# Test bandwidth to PC
iperf3 -c 192.168.1.100
```

### Web page not loading

**Check Flask is running:**
```bash
# Should show Flask process
ps aux | grep app.py
```

**Firewall (if enabled):**
```bash
# Allow port 5000
sudo ufw allow 5000
```

**Access from same device first:**
```
http://localhost:5000
```

## Performance Tips

### Raspberry Pi optimization

**Enable maximum performance:**
```bash
# Set to maximum performance mode
sudo raspi-config
# Performance Options > Performance Mode > On

# Or manually
echo "performance" | sudo tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor
```

**Reduce inference frequency:**
- Don't send every frame to inference
- Send every 2nd or 3rd frame (modify `camera_service.py`)

### Network optimization

**Use 5GHz WiFi** (better bandwidth, less interference)

**Static IP for robot:**
```bash
# Edit dhcpcd.conf
sudo nano /etc/dhcpcd.conf

# Add:
interface wlan0
static ip_address=192.168.1.50/24
static routers=192.168.1.1
```

## Running as a Service

Create systemd service for auto-start:

```bash
# Create service file
sudo nano /etc/systemd/system/robot-car.service
```

```ini
[Unit]
Description=Robot Car Camera Service
After=network.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/robot-car-service
Environment="PATH=/home/pi/robot-car-service/.venv/bin"
ExecStart=/home/pi/robot-car-service/.venv/bin/python app.py
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

```bash
# Enable and start
sudo systemctl daemon-reload
sudo systemctl enable robot-car.service
sudo systemctl start robot-car.service

# Check status
sudo systemctl status robot-car.service
```

## Next Steps

This is the camera and display component. You'll need to add:

1. **Motor control** - Add motor abstraction and control endpoints
2. **Control WebSocket** - Receive steering/throttle commands
3. **Auto-follow logic** - Calculate motor commands from detections

## License

MIT