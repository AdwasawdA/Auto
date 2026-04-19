"""
Camera Service for Robot Car
Captures video, sends frames to inference server, receives detections
"""
import asyncio
import base64
import json
import logging
import time
from dataclasses import dataclass
from typing import Optional, List
import sys

import cv2
import numpy as np
import websockets

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@dataclass
class Detection:
    """Object detection from inference server"""
    class_id: int
    class_name: str
    confidence: float
    bbox: List[float]
    bbox_center: List[float]


@dataclass
class FrameMetrics:
    """Timing metrics for a frame"""
    frame_id: int
    capture_time: float
    inference_time_ms: float
    render_time_ms: float
    total_latency_ms: float


class CameraCapture:
    """Camera capture handler - works with PiCamera2 or USB camera"""
    
    def __init__(self, resolution=(640, 480), fps=20, use_picamera=True):
        """
        Initialize camera
        
        Args:
            resolution: (width, height) tuple
            fps: Target frames per second
            use_picamera: Use PiCamera2 if available, else OpenCV
        """
        self.resolution = resolution
        self.fps = fps
        self.camera = None
        self.use_picamera = use_picamera and self._is_raspberry_pi()
        
        self._init_camera()
    
    def _is_raspberry_pi(self):
        """Check if running on Raspberry Pi"""
        try:
            with open('/proc/device-tree/model', 'r') as f:
                return 'raspberry pi' in f.read().lower()
        except:
            return False
    
    def _init_camera(self):
        """Initialize camera based on platform"""
        logger.info("Init_camera...")
        if self.use_picamera:
            try:
                from picamera2 import Picamera2
                logger.info("Initializing PiCamera2...")
                self.camera = Picamera2()
                config = self.camera.create_preview_configuration(
                    main={"size": self.resolution, "format": "RGB888"}
                )
                self.camera.configure(config)
                self.camera.start()
                logger.info("PiCamera2 initialized")
            except Exception as e:
                logger.warning(f"Failed to initialize PiCamera2: {e}")
                logger.info("Falling back to OpenCV camera...")
                self.use_picamera = False
                self._init_opencv_camera()
        else:
            self._init_opencv_camera()
    
    def _init_opencv_camera(self):
        """Initialize OpenCV camera"""
        logger.info("Initializing OpenCV camera...")
        self.camera = cv2.VideoCapture(0)
        self.camera.set(cv2.CAP_PROP_FRAME_WIDTH, self.resolution[0])
        self.camera.set(cv2.CAP_PROP_FRAME_HEIGHT, self.resolution[1])
        self.camera.set(cv2.CAP_PROP_FPS, self.fps)
        
        if not self.camera.isOpened():
            raise RuntimeError("Failed to open camera")
        logger.info("OpenCV camera initialized")
    
    def capture_frame(self) -> Optional[np.ndarray]:
        """Capture a single frame"""
        try:
            if self.use_picamera:
                frame = self.camera.capture_array()
                # PiCamera2 returns BGR directly
                return frame
            else:
                ret, frame = self.camera.read()
                return frame if ret else None
        except Exception as e:
            logger.error(f"Failed to capture frame: {e}")
            return None
    
    def release(self):
        """Release camera resources"""
        if self.use_picamera:
            self.camera.stop()
        else:
            self.camera.release()


class InferenceClient:
    """WebSocket client for inference server"""
    
    def __init__(self, server_url: str = "ws://localhost:8765"):
        """
        Initialize inference client
        
        Args:
            server_url: WebSocket URL of inference server
        """
        self.server_url = server_url
        self.websocket = None
        self.connected = False
        self.frame_id = 0
        self.latest_detections = []
        self.latest_metrics = None
        self._running = False
    
    async def connect(self):
        """Connect to inference server"""
        try:
            logger.info(f"Connecting to inference server: {self.server_url}")
            self.websocket = await websockets.connect(self.server_url)
            self.connected = True
            logger.info("Connected to inference server")
        except Exception as e:
            logger.error(f"Failed to connect to inference server: {e}")
            self.connected = False
            raise
    
    async def send_frame(self, frame: np.ndarray) -> int:
        """
        Send frame to inference server
        
        Args:
            frame: BGR image as numpy array
            
        Returns:
            frame_id for tracking
        """
        if not self.connected:
            return -1
        
        try:
            # Encode frame as JPEG
            _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
            jpg_base64 = base64.b64encode(buffer).decode('utf-8')
            
            # Send to server
            self.frame_id += 1
            message = {
                "type": "frame",
                "frame_id": self.frame_id,
                "data": jpg_base64,
                "timestamp": time.time()
            }
            await self.websocket.send(json.dumps(message))
            return self.frame_id
            
        except Exception as e:
            logger.error(f"Failed to send frame: {e}")
            self.connected = False
            return -1
    
    async def receive_loop(self):
        """Background loop to receive inference results"""
        self._running = True
        try:
            while self._running and self.connected:
                try:
                    message = await asyncio.wait_for(
                        self.websocket.recv(),
                        timeout=5.0
                    )
                    await self._handle_message(message)
                except asyncio.TimeoutError:
                    continue
                except websockets.exceptions.ConnectionClosed:
                    logger.warning("Connection to inference server closed")
                    self.connected = False
                    break
                    
        except Exception as e:
            logger.error(f"Error in receive loop: {e}")
            self.connected = False
    
    async def _handle_message(self, message: str):
        """Handle incoming message from server"""
        try:
            data = json.loads(message)
            msg_type = data.get("type")
            
            if msg_type == "inference_result":
                result = data.get("result", {})
                
                # Parse detections
                detections = []
                for d in result.get("detections", []):
                    detection = Detection(
                        class_id=d["class_id"],
                        class_name=d["class_name"],
                        confidence=d["confidence"],
                        bbox=d["bbox"],
                        bbox_center=d["bbox_center"]
                    )
                    detections.append(detection)
                
                self.latest_detections = detections
                
                # Store metrics
                self.latest_metrics = {
                    "frame_id": result.get("frame_id"),
                    "inference_time_ms": result.get("inference_time_ms"),
                    "timestamp": result.get("timestamp")
                }
                
        except Exception as e:
            logger.error(f"Failed to handle message: {e}")
    
    def get_detections(self) -> List[Detection]:
        """Get latest detections"""
        return self.latest_detections.copy()
    
    def get_metrics(self) -> Optional[dict]:
        """Get latest metrics"""
        return self.latest_metrics
    
    async def close(self):
        """Close connection"""
        self._running = False
        if self.websocket:
            await self.websocket.close()
        self.connected = False


class CameraService:
    """Main camera service - captures, sends to inference, stores results"""
    
    def __init__(
        self,
        inference_url: str = "ws://localhost:8765",
        resolution: tuple = (640, 480),
        fps: int = 20
    ):
        """
        Initialize camera service
        
        Args:
            inference_url: URL of inference server
            resolution: Camera resolution
            fps: Target FPS
        """
        self.camera = CameraCapture(resolution=resolution, fps=fps)
        self.inference_client = InferenceClient(server_url=inference_url)
        self.latest_frame = None
        self.latest_detections = []
        self.metrics_history = []
        self.max_metrics_history = 100
        self._running = False
        
    async def start(self):
        """Start camera service"""
        logger.info("Starting camera service...")
        
        # Connect to inference server
        try:
            await self.inference_client.connect()
        except Exception as e:
            logger.error(f"Failed to connect to inference server: {e}")
            logger.info("Running in camera-only mode (no inference)")
        
        # Start background tasks
        self._running = True
        tasks = [
            asyncio.create_task(self._capture_loop()),
            asyncio.create_task(self.inference_client.receive_loop())
        ]
        
        await asyncio.gather(*tasks, return_exceptions=True)
    
    async def _capture_loop(self):
        """Main capture loop"""
        frame_interval = 1.0 / self.camera.fps
        
        while self._running:
            start_time = time.time()
            
            # Capture frame
            frame = self.camera.capture_frame()
            if frame is None:
                logger.warning("Failed to capture frame")
                await asyncio.sleep(0.1)
                continue
            
            capture_time = time.time()
            self.latest_frame = frame.copy()
            
            # Send to inference server
            if self.inference_client.connected:
                await self.inference_client.send_frame(frame)
                
                # Get latest detections
                self.latest_detections = self.inference_client.get_detections()
            
            # Calculate timing
            elapsed = time.time() - start_time
            sleep_time = max(0, frame_interval - elapsed)
            await asyncio.sleep(sleep_time)
    
    def get_latest_frame(self) -> Optional[np.ndarray]:
        """Get latest captured frame"""
        return self.latest_frame.copy() if self.latest_frame is not None else None
    
    def get_detections(self) -> List[Detection]:
        """Get latest detections"""
        return self.latest_detections.copy()
    
    def get_metrics(self) -> Optional[dict]:
        """Get inference metrics"""
        return self.inference_client.get_metrics()
    
    def get_average_metrics(self) -> dict:
        """Calculate average metrics"""
        if not self.metrics_history:
            return {
                "avg_inference_ms": 0.0,
                "avg_render_ms": 0.0,
                "avg_total_latency_ms": 0.0
            }
        
        recent = self.metrics_history[-50:]  # Last 50 frames
        
        return {
            "avg_inference_ms": np.mean([m.inference_time_ms for m in recent]),
            "avg_render_ms": np.mean([m.render_time_ms for m in recent]),
            "avg_total_latency_ms": np.mean([m.total_latency_ms for m in recent])
        }
    
    def add_metrics(self, metrics: FrameMetrics):
        """Add frame metrics to history"""
        self.metrics_history.append(metrics)
        if len(self.metrics_history) > self.max_metrics_history:
            self.metrics_history.pop(0)
    
    async def stop(self):
        """Stop camera service"""
        logger.info("Stopping camera service...")
        self._running = False
        await self.inference_client.close()
        self.camera.release()


# Singleton instance
camera_service = None


async def init_camera_service(inference_url: str):
    """Initialize global camera service"""
    global camera_service
    camera_service = CameraService(inference_url=inference_url)
    asyncio.create_task(camera_service.start())
    # Give it a moment to initialize
    await asyncio.sleep(1.0)


def get_camera_service() -> CameraService:
    """Get camera service instance"""
    return camera_service