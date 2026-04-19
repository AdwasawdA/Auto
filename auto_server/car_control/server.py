"""
Car Control Server
Runs on Raspberry Pi 4. Hosts the web UI and handles WebSocket commands.

Usage:
    python server.py                  # uses real hardware
    python server.py --mock           # uses mock Auto (for dev/testing)
"""
import argparse
import json
import logging
import threading
from flask import Flask, render_template, Response, jsonify, request

import asyncio
import io
import time
from threading import Lock

import cv2
import numpy as np
from flask_sock import Sock

from camera_service import (
    init_camera_service,
    get_camera_service,
    FrameMetrics
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

app = Flask(__name__)
sock = Sock(app)

# flask_sock is only needed at runtime (not during unit tests)
try:
    from flask_sock import Sock
    sock = Sock(app)
    _has_sock = True
except ImportError:
    sock = None
    _has_sock = False

# Will be set to an Auto instance (real or mock) at startup
auto = None
auto_lock = threading.Lock()

# Distance cache — updated by background poller at 5 Hz
_latest_distance = None
_distance_lock = threading.Lock()


def _distance_poller():
    """Background thread: reads distance sensor 5x per second and caches the result."""
    global _latest_distance
    while True:
        try:
            if auto is not None:
                with auto_lock:
                    dist = auto.vzdialenost()
                with _distance_lock:
                    _latest_distance = dist
        except Exception as e:
            log.error("Distance poll error: %s", e)
        time.sleep(0.5)

# Configuration
INFERENCE_SERVER_URL = "ws://10.42.0.168:8765"  # Update with your PC IP
SHOW_BBOX = True
frame_lock = Lock()


# ---------------------------------------------------------------------------
# Command dispatch
# ---------------------------------------------------------------------------

def handle_command(data: dict) -> dict:
    """
    Route a parsed JSON command to the correct Auto method.
    Returns a dict that is sent back to the client as JSON.
    """
    action = data.get("action")
    value = data.get("value", 10)  # default speed/steering 50%

    try:
        if action == "dopredu":
            with auto_lock:
                auto.dopredu(int(value))
            return {"ok": True, "action": action, "value": value}

        elif action == "dozadu":
            with auto_lock:
                auto.dozadu(int(value))
            return {"ok": True, "action": action, "value": value}

        elif action == "stop":
            with auto_lock:
                auto.stop()
            return {"ok": True, "action": action}

        elif action == "doprava":
            with auto_lock:
                auto.doprava(int(value))
            return {"ok": True, "action": action, "value": value}

        elif action == "dolava":
            with auto_lock:
                auto.dolava(int(value))
            return {"ok": True, "action": action, "value": value}

        elif action == "rovno":
            with auto_lock:
                auto.rovno()
            return {"ok": True, "action": action}

        elif action == "vzdialenost":
            with _distance_lock:
                dist = _latest_distance
            return {"ok": True, "action": action, "distance": dist}

        else:
            log.warning("Unknown action: %s", action)
            return {"ok": False, "error": f"Unknown action: {action}"}

    except Exception as e:
        log.error("Error handling command %s: %s", action, e)
        return {"ok": False, "error": str(e)}


def draw_detections(frame: np.ndarray, detections: list, show_bbox: bool = True) -> np.ndarray:
    """
    Draw bounding boxes and labels on frame
    
    Args:
        frame: Input frame
        detections: List of Detection objects
        show_bbox: Whether to draw bounding boxes
        
    Returns:
        Frame with drawings
    """
    if not show_bbox or not detections:
        return frame
    
    output = frame.copy()
    
    for det in detections:
        bbox = det.bbox
        x1, y1, x2, y2 = map(int, bbox)
        
        # Draw bounding box
        color = (0, 255, 0)  # Green
        cv2.rectangle(output, (x1, y1), (x2, y2), color, 2)
        
        # Draw label
        label = f"{det.class_name} {det.confidence:.2f}"
        label_size, _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 2)
        
        # Label background
        cv2.rectangle(
            output,
            (x1, y1 - label_size[1] - 10),
            (x1 + label_size[0], y1),
            color,
            -1
        )
        
        # Label text
        cv2.putText(
            output,
            label,
            (x1, y1 - 5),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (0, 0, 0),
            2
        )
        
        # Draw center point
        center = det.bbox_center
        cx, cy = map(int, center)
        cv2.circle(output, (cx, cy), 5, color, -1)
    
    return output


def draw_metrics(frame: np.ndarray, metrics: dict, show_bbox: bool) -> np.ndarray:
    """
    Draw metrics overlay on frame
    
    Args:
        frame: Input frame
        metrics: Metrics dictionary
        show_bbox: Current bbox toggle state
        
    Returns:
        Frame with metrics overlay
    """
    output = frame.copy()
    h, w = output.shape[:2]
    
    # Semi-transparent overlay
    overlay = output.copy()
    cv2.rectangle(overlay, (10, 10), (300, 120), (0, 0, 0), -1)
    cv2.addWeighted(overlay, 0.6, output, 0.4, 0, output)
    
    # Metrics text
    y_offset = 30
    font = cv2.FONT_HERSHEY_SIMPLEX
    font_scale = 0.5
    color = (0, 255, 0)
    thickness = 1
    
    texts = [
        f"Inference: {metrics.get('avg_inference_ms', 0):.1f}ms",
        f"Render: {metrics.get('avg_render_ms', 0):.1f}ms",
        f"Total Latency: {metrics.get('avg_total_latency_ms', 0):.1f}ms",
        f"BBox: {'ON' if show_bbox else 'OFF'}"
    ]
    
    for i, text in enumerate(texts):
        y_pos = y_offset + (i * 25)
        cv2.putText(output, text, (20, y_pos), font, font_scale, color, thickness)
    
    return output


def generate_frames():
    """Generator for MJPEG stream"""
    global SHOW_BBOX
    
    while True:
        try:
            service = get_camera_service()
            if service is None:
                time.sleep(0.1)
                continue
            
            # Get latest frame
            frame = service.get_latest_frame()
            if frame is None:
                time.sleep(0.1)
                continue
            
            capture_time = time.time()
            
            # Get detections
            detections = service.get_detections()
            
            # Measure rendering time
            render_start = time.time()
            
            with frame_lock:
                current_show_bbox = SHOW_BBOX
            
            # Draw detections
            if current_show_bbox:
                frame = draw_detections(frame, detections, show_bbox=current_show_bbox)
            
            # Get metrics
            inference_metrics = service.get_metrics()
            avg_metrics = service.get_average_metrics()
            
            # Calculate latencies
            inference_time_ms = inference_metrics.get('inference_time_ms', 0) if inference_metrics else 0
            render_time_ms = (time.time() - render_start) * 1000
            total_latency_ms = (time.time() - capture_time) * 1000
            
            # Store metrics
            if inference_metrics:
                frame_metrics = FrameMetrics(
                    frame_id=inference_metrics.get('frame_id', 0),
                    capture_time=capture_time,
                    inference_time_ms=inference_time_ms,
                    render_time_ms=render_time_ms,
                    total_latency_ms=total_latency_ms
                )
                service.add_metrics(frame_metrics)
            
            # Draw metrics overlay
            avg_metrics['avg_render_ms'] = render_time_ms  # Update with current
            #frame = draw_metrics(frame, avg_metrics, current_show_bbox)
            
            # Encode frame as JPEG
            _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
            frame_bytes = buffer.tobytes()
            
            # Yield frame in MJPEG format
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
            
        except Exception as e:
            log.error(f"Error generating frame: {e}")
            time.sleep(0.1)

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")

@app.route('/video_feed')
def video_feed():
    """MJPEG video stream endpoint"""
    return Response(
        generate_frames(),
        mimetype='multipart/x-mixed-replace; boundary=frame'
    )


@app.route('/api/metrics')
def api_metrics():
    """Get current metrics"""
    service = get_camera_service()
    if service is None:
        return jsonify({"error": "Service not initialized"}), 503
    
    metrics = service.get_average_metrics()
    return jsonify(metrics)


@app.route('/api/toggle_bbox', methods=['POST'])
def toggle_bbox():
    """Toggle bounding box display"""
    global SHOW_BBOX
    
    data = request.get_json()
    if data and 'show_bbox' in data:
        with frame_lock:
            SHOW_BBOX = data['show_bbox']
        return jsonify({"show_bbox": SHOW_BBOX})
    
    return jsonify({"error": "Invalid request"}), 400


@app.route('/api/status')
def api_status():
    """Get service status"""
    service = get_camera_service()
    if service is None:
        log.info("/api/status initializing")
        return jsonify({"status": "initializing"}), 503
    
    return jsonify({
        "status": "running",
        "inference_connected": service.inference_client.connected,
        "show_bbox": SHOW_BBOX
    })


def _register_ws():
    pass  # defined below if sock available

if _has_sock:
    @sock.route("/ws")
    def websocket(ws):
        log.info("Client connected")
        try:
            while True:
                raw = ws.receive()
                if raw is None:
                    break
                try:
                    data = json.loads(raw)
                    log.info("Command: %s", data)
                    response = handle_command(data)
                except json.JSONDecodeError:
                    response = {"ok": False, "error": "Invalid JSON"}
                ws.send(json.dumps(response))
        except Exception as e:
            log.info("Client disconnected: %s", e)


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

def _run_async_loop(loop, host, port):
    """Run the asyncio event loop in a background thread."""
    asyncio.set_event_loop(loop)
    loop.run_until_complete(_async_main(host, port))


async def _async_main(host, port):
    """Async initialisation: hardware + camera service. Runs in background thread."""
    global auto

    if _mock_mode:
        log.info("Starting with MOCK hardware")
        from tests.mock_auto import MockAuto
        auto = MockAuto()
    else:
        log.info("Starting with REAL hardware")
        from car_setup import create_auto
        auto = create_auto()

    threading.Thread(target=_distance_poller, daemon=True, name="distance-poller").start()
    log.info("Distance poller started at 2 Hz")

    log.info("Initializing camera service...")
    await init_camera_service(INFERENCE_SERVER_URL)

    log.info("Camera service running — keeping event loop alive")
    try:
        while True:
            await asyncio.sleep(1)
    except asyncio.CancelledError:
        pass
    finally:
        service = get_camera_service()
        if service:
            await service.stop()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Car Control Server")
    parser.add_argument("--mock", action="store_true", help="Use mock hardware (no RPi needed)")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=5000, help="Port (default: 5000)")
    args = parser.parse_args()

    _mock_mode = args.mock

    # Run asyncio (camera + hardware) in a background thread so Flask can
    # use the main thread and its threaded request handlers work normally.
    loop = asyncio.new_event_loop()
    bg = threading.Thread(target=_run_async_loop, args=(loop, args.host, args.port), daemon=True)
    bg.start()

    # Give the background loop a moment to initialise hardware + camera
    import time as _time
    _time.sleep(3)

    log.info("Car control server starting on http://%s:%d", args.host, args.port)
    app.run(host=args.host, port=args.port, debug=False, threaded=True)

