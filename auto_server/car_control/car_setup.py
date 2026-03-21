"""
Car hardware initialization.
Import this module to get a fully configured Auto instance.
Separated from server.py so it can be mocked in tests.
"""
from pohyb2 import Auto, Odbacanie, DC_Motor, Servo_Motor, Pohon, Tofl
from adafruit_pca9685 import PCA9685
from board import SCL, SDA
import busio


def create_auto() -> Auto:
    i2c = busio.I2C(SCL, SDA)
    pca = PCA9685(i2c, address=0x40)

    motor1 = DC_Motor(26, 21, 4, False)
    motor2 = DC_Motor(27, 18, 17, True)

    servo = Servo_Motor(pca, 0, 500, 2400, 270, 160)

    pohon = Pohon(motory=[motor1, motor2])
    odbacanie = Odbacanie(servo=servo, max_uhol=90)
    ultrazvuk = Tofl()

    return Auto(pohon=pohon, odbacanie=odbacanie, ultrazvuk=ultrazvuk)
