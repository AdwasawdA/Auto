import time
import math
from pmw3901 import PAA5100

try:
    sensor = PAA5100()
except Exception as e:
    print(f"Failed to initialize sensor: {e}")
    exit(1)

print("=== PAA5100JE CALIBRATION SCRIPT ===")
print("1. Place your vehicle against a ruler at the 0 cm mark.")
print("2. Move the vehicle forward in a straight line (e.g., exactly 30 or 50 cm).")
print("3. Stop moving, then press Ctrl+C to get your total pixel count.\n")

total_raw_pixels = 0.0

try:
    while True:
        motion = sensor.get_motion()
        
        if motion is not None:
            dx, dy = motion
            # Calculate the frame's movement magnitude
            frame_pixels = math.sqrt(dx**2 + dy**2)
            # Add to the running total
            total_raw_pixels += frame_pixels
            
            # Print feedback so you know it's counting
            if frame_pixels > 0:
                print(f"Counting... Total accumulated pixels: {total_raw_pixels:.2f}", end="\r")
        
        time.sleep(0.01)

except KeyboardInterrupt:
    print("\n\n=== TEST FINISHED ===")
    print(f"Total Raw Pixels accumulated: {total_raw_pixels:.2f}")
    print("Use this number in the formula below to find your K factor.")
