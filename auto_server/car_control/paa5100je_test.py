import time
import math
from pmw3901 import PAA5100

# --- CONFIGURATION CONSTANTS ---
# 1. Physical mounting height from the lens to the surface (in centimeters)
SENSOR_HEIGHT_CM = 3.0  

# 2. Calibration factor (k)
# This constant maps pixel displacement to physical distance at a unit height.
# Adjust this value empirically if your measured distance deviates from reality.
CALIBRATION_K = 0.0025  

try:
    sensor = PAA5100()
except Exception as e:
    print(f"Failed to initialize sensor: {e}")
    exit(1)

print("PAA5100JE Speed Test Initialized. Move the sensor...")
print("Press Ctrl+C to exit.")

# Initialize temporal anchors
last_time = time.perf_counter()

try:
    while True:
        current_time = time.perf_counter()
        motion = sensor.get_motion()
        
        if motion is not None:
            dx, dy = motion
            
            # Calculate elapsed time segment (dt)
            dt = current_time - last_time
            
            if dt > 0:
                # Calculate absolute pixel displacement vector
                pixel_distance = math.sqrt(dx**2 + dy**2)
                
                # Scale displacement based on mounting height and calibration constant
                # Physical Distance = k * Height * Pixels
                physical_distance_cm = CALIBRATION_K * SENSOR_HEIGHT_CM * pixel_distance
                
                # Calculate speed: cm divided by seconds
                speed_cm_s = physical_distance_cm / dt
                speed_km_h = speed_cm_s * 0.036
                
                print(f"DX: {dx:3d} | DY: {dy:3d} | dt: {dt:.4f}s | Speed: {speed_km_h:6.2f} km/h")
        
        # Reset the timestamp anchor for the next iteration
        last_time = current_time
        time.sleep(0.01)  # Shorter sleep provides cleaner differential time slices

except KeyboardInterrupt:
    print("\nTest stopped.")
