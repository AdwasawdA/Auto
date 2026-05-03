import RPi.GPIO as GPIO
import time

GPIO.setmode(GPIO.BCM)

GPIO.setup(8, GPIO.IN)

print("Test")

try:
    while True:
        if GPIO.input(8) == GPIO.LOW:
            print("Narazene!")
            time.sleep(0.2)
        time.sleep(0.01)
except KeyboardInterrupt:
    GPIO.cleanup()
