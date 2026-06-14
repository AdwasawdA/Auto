from pohyb2 import Auto, Odbacanie, DC_Motor, Servo_Motor, Pohon, Tofl, Crash_Sensor, Flow_Sensor, Accelerometer
from adafruit_pca9685 import PCA9685
from board import SCL, SDA
import busio


def create_auto() -> Auto:
    i2c = busio.I2C(SCL, SDA)
    pca = PCA9685(i2c, address=0x40)

    motor1 = DC_Motor(26, 21, 4, False)
    motor2 = DC_Motor(27, 18, 17, True)

    pohon = Pohon(motory=[motor1, motor2])
    
    servo = Servo_Motor(pca, 0, 500, 2400, 270, 155)
    odbacanie = Odbacanie(servo=servo, max_uhol=90)
    
    try:
        ultrazvuk = Tofl(i2c)
    except Exception as e:
        print(f"Warning: ToF sensor failed to initialize: {e}")
        ultrazvuk = None
    
    try:
        crash_sensor = Crash_Sensor(8)
    except Exception as e:
        print(f"Warning: Crash sensor failed to initialize: {e}")
        crash_sensor = None

    try:
        flow_sensor = Flow_Sensor(height_cm=1.95, K=0.003100)
    except Exception as e:
        print(f"Warning: Flow sensor failed to initialize: {e}")
        flow_sensor = None

    try:
        accelerometer = Accelerometer(address=0x68)
    except Exception as e:
        print(f"Warning: Accelerometer failed to initialize: {e}")
        accelerometer = None

    return Auto(pohon=pohon, odbacanie=odbacanie, ultrazvuk=ultrazvuk, crash_sensor=crash_sensor, flow_sensor=flow_sensor, accelerometer=accelerometer)
