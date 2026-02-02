"""
Flask Web Application for Robot Car
Serves video stream with inference overlay and metrics
"""
import asyncio
import io
import time
import logging
from threading import Lock

import cv2
import numpy as np
from flask import Flask, Response, render_template, jsonify, request
from flask_sock import Sock

from camera_service import (
    init_camera_service,
    get_camera_service,
    FrameMetrics
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
sock = Sock(app)

# Configuration
INFERENCE_SERVER_URL = "ws://192.168.50.124:8765"  # Update with your PC IP
SHOW_BBOX = True
frame_lock = Lock()


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
            frame = draw_metrics(frame, avg_metrics, current_show_bbox)
            
            # Encode frame as JPEG
            _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
            frame_bytes = buffer.tobytes()
            
            # Yield frame in MJPEG format
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
            
        except Exception as e:
            logger.error(f"Error generating frame: {e}")
            time.sleep(0.1)


@app.route('/')
def index():
    """Serve main page"""
    return render_template('index.html')


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
        return jsonify({"status": "initializing"}), 503
    
    return jsonify({
        "status": "running",
        "inference_connected": service.inference_client.connected,
        "show_bbox": SHOW_BBOX
    })


def run_flask_app():
    """Run Flask application"""
    app.run(host='0.0.0.0', port=5000, threaded=True, debug=False)


async def main():
    """Main entry point"""
    # Initialize camera service
    logger.info("Initializing camera service...")
    await init_camera_service(INFERENCE_SERVER_URL)
    
    # Run Flask in background thread
    import threading
    flask_thread = threading.Thread(target=run_flask_app, daemon=True)
    flask_thread.start()
    
    logger.info("Robot car service running!")
    logger.info("Web UI available at http://<robot-ip>:5000")
    
    # Keep running
    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        service = get_camera_service()
        if service:
            await service.stop()


if __name__ == "__main__":
    asyncio.run(main())