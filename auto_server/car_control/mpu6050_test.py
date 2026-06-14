from mpu6050 import mpu6050
import time

# Initialize the sensor at its default I2C address (0x68)
sensor = mpu6050(0x68)

print("Reading data from MPU6050... Press Ctrl+C to stop.")

try:
    while True:
        # Get accelerometer, gyroscope, and temperature readings
        accel_data = sensor.get_accel_data()
        gyro_data = sensor.get_gyro_data()
        temp = sensor.get_temp()
        
        print("---")
        print(f"Temp: {temp:.2f} °C")
        print(f"Accel - X: {accel_data['x']:.2f}, Y: {accel_data['y']:.2f}, Z: {accel_data['z']:.2f} m/s^2")
        print(f"Gyro  - X: {gyro_data['x']:.2f}, Y: {gyro_data['y']:.2f}, Z: {gyro_data['z']:.2f} deg/s")
        
        time.sleep(1)

except KeyboardInterrupt:
    print("\nProgram stopped.")
