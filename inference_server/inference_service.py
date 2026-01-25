"""
YOLO Inference Service for Robot Vision
Receives frames via WebSocket, performs inference, sends back detections
"""
import asyncio
import base64
import json
import logging
from dataclasses import dataclass, asdict
from typing import List, Optional
import time

import cv2
import numpy as np
import websockets
from ultralytics import YOLO

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@dataclass
class Detection:
    """Single object detection result"""
    class_id: int
    class_name: str
    confidence: float
    bbox: List[float]  # [x1, y1, x2, y2]
    bbox_center: List[float]  # [center_x, center_y]


@dataclass
class InferenceResult:
    """Complete inference result for a frame"""
    timestamp: float
    frame_id: int
    detections: List[Detection]
    inference_time_ms: float
    image_shape: List[int]  # [height, width]


class YOLOInferenceEngine:
    """YOLO inference engine with configurable model"""
    
    def __init__(
        self, 
        model_path: str = "yolov8n.pt",
        conf_threshold: float = 0.5,
        iou_threshold: float = 0.45,
        target_classes: Optional[List[int]] = None,
        device: str = "cuda:0"  # or "cpu"
    ):
        """
        Initialize YOLO model
        
        Args:
            model_path: Path to YOLO model weights (yolov8n.pt, yolov8s.pt, etc.)
            conf_threshold: Confidence threshold for detections
            iou_threshold: IOU threshold for NMS
            target_classes: List of class IDs to detect (None = all classes)
            device: Device to run inference on (cuda:0, cpu)
        """
        logger.info(f"Loading YOLO model: {model_path} on device: {device}")
        self.model = YOLO(model_path)
        self.conf_threshold = conf_threshold
        self.iou_threshold = iou_threshold
        self.target_classes = target_classes or [0]  # Default: person class only
        self.device = device
        
        # Warmup inference
        logger.info("Warming up model...")
        dummy_image = np.zeros((640, 640, 3), dtype=np.uint8)
        self.model(dummy_image, device=self.device, verbose=False)
        logger.info("Model ready")
    
    def infer(self, image: np.ndarray, frame_id: int = 0) -> InferenceResult:
        """
        Run inference on a single frame
        
        Args:
            image: Input image as numpy array (BGR format)
            frame_id: Frame identifier for tracking
            
        Returns:
            InferenceResult with all detections
        """
        start_time = time.time()
        
        # Run inference
        results = self.model(
            image,
            conf=self.conf_threshold,
            iou=self.iou_threshold,
            classes=self.target_classes,
            device=self.device,
            verbose=False
        )[0]
        
        # Parse detections
        detections = []
        if results.boxes is not None:
            for box in results.boxes:
                class_id = int(box.cls[0])
                confidence = float(box.conf[0])
                bbox = box.xyxy[0].cpu().numpy().tolist()  # [x1, y1, x2, y2]
                
                # Calculate center
                center_x = (bbox[0] + bbox[2]) / 2
                center_y = (bbox[1] + bbox[3]) / 2
                
                detection = Detection(
                    class_id=class_id,
                    class_name=results.names[class_id],
                    confidence=confidence,
                    bbox=bbox,
                    bbox_center=[center_x, center_y]
                )
                detections.append(detection)
        
        inference_time_ms = (time.time() - start_time) * 1000
        
        return InferenceResult(
            timestamp=time.time(),
            frame_id=frame_id,
            detections=detections,
            inference_time_ms=inference_time_ms,
            image_shape=list(image.shape[:2])  # [height, width]
        )


class InferenceWebSocketServer:
    """WebSocket server that receives frames and sends back inference results"""
    
    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 8765,
        model_path: str = "yolov8n.pt",
        conf_threshold: float = 0.5,
        device: str = "cuda:0"
    ):
        """
        Initialize inference server
        
        Args:
            host: Host to bind server to
            port: Port to bind server to
            model_path: Path to YOLO model
            conf_threshold: Confidence threshold for detections
            device: Device for inference (cuda:0 or cpu)
        """
        self.host = host
        self.port = port
        self.inference_engine = YOLOInferenceEngine(
            model_path=model_path,
            conf_threshold=conf_threshold,
            target_classes=[0],  # Person class for human tracking
            device=device
        )
        self.frame_count = 0
        self.total_inference_time = 0.0
        
    async def handle_client(self, websocket):
        """Handle a single WebSocket client connection"""
        client_addr = websocket.remote_address
        logger.info(f"Client connected: {client_addr}")
        
        try:
            async for message in websocket:
                await self.process_message(websocket, message)
                
        except websockets.exceptions.ConnectionClosed:
            logger.info(f"Client disconnected: {client_addr}")
        except Exception as e:
            logger.error(f"Error handling client {client_addr}: {e}", exc_info=True)
        finally:
            logger.info(f"Connection closed: {client_addr}")
    
    async def process_message(self, websocket, message):
        """Process incoming message from client"""
        try:
            # Parse incoming JSON message
            data = json.loads(message)
            msg_type = data.get("type")
            
            if msg_type == "frame":
                await self.handle_frame(websocket, data)
            elif msg_type == "ping":
                await self.handle_ping(websocket)
            elif msg_type == "config":
                await self.handle_config(websocket, data)
            else:
                logger.warning(f"Unknown message type: {msg_type}")
                
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON: {e}")
        except Exception as e:
            logger.error(f"Error processing message: {e}", exc_info=True)
    
    async def handle_frame(self, websocket, data):
        """Handle incoming frame for inference"""
        try:
            # Decode base64 JPEG image
            frame_data = data.get("data")
            frame_id = data.get("frame_id", self.frame_count)
            
            if not frame_data:
                logger.warning("No frame data received")
                return
            
            # Decode base64 to bytes
            img_bytes = base64.b64decode(frame_data)
            
            # Decode JPEG to numpy array
            nparr = np.frombuffer(img_bytes, np.uint8)
            image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            
            if image is None:
                logger.warning("Failed to decode image")
                return
            
            # Run inference
            result = self.inference_engine.infer(image, frame_id)
            
            # Update statistics
            self.frame_count += 1
            self.total_inference_time += result.inference_time_ms
            
            # Log periodic stats
            if self.frame_count % 50 == 0:
                avg_time = self.total_inference_time / self.frame_count
                fps = 1000.0 / avg_time if avg_time > 0 else 0
                logger.info(
                    f"Processed {self.frame_count} frames | "
                    f"Avg inference: {avg_time:.1f}ms | "
                    f"Avg FPS: {fps:.1f}"
                )
            
            # Send result back to client
            response = {
                "type": "inference_result",
                "result": self._serialize_result(result)
            }
            await websocket.send(json.dumps(response))
            
        except Exception as e:
            logger.error(f"Error handling frame: {e}", exc_info=True)
    
    async def handle_ping(self, websocket):
        """Handle ping message"""
        response = {
            "type": "pong",
            "timestamp": time.time()
        }
        await websocket.send(json.dumps(response))
    
    async def handle_config(self, websocket, data):
        """Handle configuration update"""
        try:
            conf_threshold = data.get("conf_threshold")
            if conf_threshold is not None:
                self.inference_engine.conf_threshold = conf_threshold
                logger.info(f"Updated confidence threshold to {conf_threshold}")
            
            response = {
                "type": "config_ack",
                "conf_threshold": self.inference_engine.conf_threshold
            }
            await websocket.send(json.dumps(response))
            
        except Exception as e:
            logger.error(f"Error handling config: {e}")
    
    def _serialize_result(self, result: InferenceResult) -> dict:
        """Convert InferenceResult to JSON-serializable dict"""
        return {
            "timestamp": result.timestamp,
            "frame_id": result.frame_id,
            "inference_time_ms": result.inference_time_ms,
            "image_shape": result.image_shape,
            "detections": [
                {
                    "class_id": d.class_id,
                    "class_name": d.class_name,
                    "confidence": d.confidence,
                    "bbox": d.bbox,
                    "bbox_center": d.bbox_center
                }
                for d in result.detections
            ]
        }
    
    async def start(self):
        """Start the WebSocket server"""
        logger.info(f"Starting inference server on {self.host}:{self.port}")
        async with websockets.serve(self.handle_client, self.host, self.port):
            logger.info("Inference server running. Press Ctrl+C to stop.")
            await asyncio.Future()  # Run forever


async def main():
    """Main entry point"""
    # Configuration
    HOST = "0.0.0.0"
    PORT = 8765
    MODEL_PATH = "yolov8n.pt"  # yolov8n, yolov8s, yolov8m, yolov8l, yolov8x
    CONF_THRESHOLD = 0.5
    DEVICE = "cuda:0"  # or "cpu" for CPU inference
    
    # Create and start server
    server = InferenceWebSocketServer(
        host=HOST,
        port=PORT,
        model_path=MODEL_PATH,
        conf_threshold=CONF_THRESHOLD,
        device=DEVICE
    )
    
    try:
        await server.start()
    except KeyboardInterrupt:
        logger.info("Shutting down inference server...")


if __name__ == "__main__":
    asyncio.run(main())