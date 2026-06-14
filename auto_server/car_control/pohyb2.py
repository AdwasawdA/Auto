from board import SCL, SDA
import busio
from adafruit_motor import servo
from adafruit_pca9685 import PCA9685
import RPi.GPIO as GPIO
import time
import math
GPIO.setwarnings(False)
GPIO.setmode(GPIO.BCM)
import adafruit_vl53l0x
from pmw3901 import PAA5100
from mpu6050 import mpu6050


class DC_Motor:
    def __init__(self, pin1, pin2, en, otoceny=False):
        GPIO.setup(en, GPIO.OUT)
        GPIO.setup(pin1, GPIO.OUT)
        GPIO.setup(pin2, GPIO.OUT)
        self.pwm = GPIO.PWM(en, 1000)
        self.pin1 = pin1
        self.pin2 = pin2
        self.en = en
        self.otoceny = otoceny

    def rychlost(self, rychlost, dopredu):
        if self.otoceny:
            dopredu = not(dopredu) 
        if dopredu and rychlost > 0:
            GPIO.output(self.pin1, GPIO.LOW)
            GPIO.output(self.pin2, GPIO.HIGH)
            self.pwm.start(100)
            self.pwm.ChangeDutyCycle(rychlost)
        elif not dopredu and rychlost > 0:                      
            GPIO.output(self.pin1, GPIO.HIGH)
            GPIO.output(self.pin2, GPIO.LOW)
            self.pwm.start(0)
            self.pwm.ChangeDutyCycle(rychlost)
        elif rychlost == 0:  
            GPIO.output(self.pin1, GPIO.LOW)
            GPIO.output(self.pin2, GPIO.LOW)
            GPIO.output(self.en, GPIO.LOW)                    



class Pohon:
    def __init__(self, motory=[]):
        self.motory = motory

    def rychlost(self, rychlost, dopredu):
        for motor in self.motory:
            motor.rychlost(rychlost, dopredu)    



class Servo_Motor:
    def __init__(self, pca, idx, min_pulse, max_pulse, range,stred = None):
        self.pca = pca
        self.pca.frequency = 50
        self.idx = idx
        self.range = range
        if stred is not None:
            self.stred = stred
        else:
            self.stred = range/2
        self.servo = servo.Servo(self.pca.channels[idx],
                               min_pulse = min_pulse,
                               max_pulse = max_pulse,
                               actuation_range = range)
        
    def nastav_uhol(self, uhol):
        print('uhol', uhol)
        self.servo.angle = uhol

    def rovno(self):
        self.nastav_uhol(self.stred)

    def vpravo(self, uhol):
        self.nastav_uhol(self.stred + uhol)

    def vlavo(self, uhol):
        self.nastav_uhol(self.stred - uhol)    

class Odbacanie:
    def __init__(self, servo, max_uhol):
        self.servo = servo
        self.max_uhol = max_uhol
    
    def rovno(self):
        self.servo.rovno()

    def vpravo(self, percento):
        self.servo.vpravo(percento / 100 * self.max_uhol)

    def vlavo(self, percento):
        self.servo.vlavo(percento / 100 * self.max_uhol)    

class Ultrazvuk:
    def __init__(self, trigg, echo):
        try:
            GPIO.setmode(GPIO.BCM)
        except:
            pass
        self.trigg = trigg
        self.echo = echo
        GPIO.setup(trigg, GPIO.OUT)
        GPIO.setup(echo, GPIO.IN)

    def distance(self):
        GPIO.output(self.trigg, True)
        time.sleep(0.00001)
        GPIO.output(self.trigg, False)
        StartTime = time.time()
        StopTime = time.time()
        while GPIO.input(self.echo) == 0:
            StartTime = time.time()
        while GPIO.input(self.echo) == 1:
            StopTime = time.time()
        TimeElapsed = StopTime - StartTime
        distance = (TimeElapsed * 34300) / 2
        return distance
    
class Tofl:
    def __init__(self, i2c=None, scl=SCL, sda=SDA):
        if i2c is None:
            i2c = busio.I2C(scl, sda)
        self.tofl = adafruit_vl53l0x.VL53L0X(i2c)
    def distance(self):
        return self.tofl.range
        
class Crash_Sensor:
    def __init__(self, pin = None):
        GPIO.setup(pin, GPIO.IN)
        self.pin = pin
    def naraz(self):
        if GPIO.input(self.pin) == GPIO.LOW:
            return 1
        return 0
    
class Flow_Sensor:
    def __init__(self, height_cm=1.95, K=0.003100):
        self.height_cm = height_cm
        self.K = K
        self.sensor = PAA5100()
        self._last_time = time.perf_counter()
    def flow_speed(self):
        current_time = time.perf_counter()
        motion = self.sensor.get_motion()
        if motion is None:
            self._last_time = current_time
            return None
        dx, dy = motion
        dt = current_time - self._last_time
        self._last_time = current_time
        if dt <= 0:
            return None
        pixel_distance = math.sqrt(dx**2 + dy**2)
        physical_distance_cm = self.K * self.height_cm * pixel_distance
        speed_cm_s = physical_distance_cm / dt
        speed_km_h = speed_cm_s * 0.036
        return speed_km_h
    def pohyb(self):
        return self.sensor.get_motion()

class Accelerometer:
    def __init__(self, address=0x68):
        self.sensor = mpu6050(address)
    def acceleration(self):
        return self.sensor.get_accel_data()
    def gyroscope(self):
        return self.sensor.get_gyro_data()
    def all(self):
        return {
            'acceleration': self.acceleration(),
            'gyroscope':    self.gyroscope(),
        }

class Auto:
    def __init__(self, pohon = None, odbacanie = None, 
                 ultrazvuk = None, crash_sensor = None, sleep_time = 0.05,
                 flow_sensor = None, accelerometer = None):
        self.pohon = pohon
        self.odbacanie = odbacanie
        self.ultrazvuk = ultrazvuk
        self.crash_sensor = crash_sensor
        self._dopredu = True
        self.rychlost = 0
        self.sleep_time = sleep_time
        self.flow_sensor = flow_sensor
        self.accelerometer = accelerometer

    def zmena_r(self, r1, r2):
        step = 5
        r1 = int(r1 / step) * 5
        r2 = int(r2 / step) * 5
        step = min(step, abs(r2 - r1))
        if r2 > r1:
            res = [r for r in range(r1, r2 + step, step)]
        elif r2 < r1:
            res = [r for r in range(r1, r2 - step, -step)] 
        else:
            res = [r1]
        return res
    
    def smer_na_r(self, dopredu, rychlost):
        if dopredu:
            return rychlost
        else:
            return -rychlost

    def dopredu(self, rychlost):
        if self.pohon is not None:
            r1 = self.smer_na_r(self._dopredu, self.rychlost)
            r2 = self.smer_na_r(True, rychlost)
            rychlosti = self.zmena_r(r1, r2)
            for r in rychlosti:
                time.sleep(self.sleep_time)
                if r < 0:
                    self.pohon.rychlost(abs(r), dopredu = False)
                else:
                    self.pohon.rychlost(abs(r), dopredu = True)    
        self.rychlost = rychlost
        self._dopredu = True

    
    def dozadu(self,rychlost):
        if self.pohon is not None:
            r1 = self.smer_na_r(self._dopredu, self.rychlost)
            r2 = self.smer_na_r(False, rychlost)
            rychlosti = self.zmena_r(r1, r2)
            for r in rychlosti:
                time.sleep(self.sleep_time)
                if r < 0:
                    self.pohon.rychlost(abs(r), dopredu = False)
                else:
                    self.pohon.rychlost(abs(r), dopredu = True)    
        self.rychlost = rychlost
        self._dopredu = False

    def stop(self):
        if self.pohon is not None:
            r1 = self.smer_na_r(self._dopredu, self.rychlost)
            r2 = self.smer_na_r(True, 0)
            rychlosti = self.zmena_r(r1, r2)
            for r in rychlosti:
                time.sleep(self.sleep_time)
                if r < 0:
                    self.pohon.rychlost(abs(r), dopredu = False)
                else:
                    self.pohon.rychlost(abs(r), dopredu = True)    
        self.rychlost = 0
        self._dopredu = True

    def doprava(self, percento):
        self.percento = percento
        self.vpravo = True
        if self.odbacanie is not None:
            self.odbacanie.vpravo(percento)

    def dolava(self, percento):
        self.percento = percento
        self.vlavo = True
        if self.odbacanie is not None:
            self.odbacanie.vlavo(percento)

    def rovno(self):
        self.vlavo = False
        self.percento = 0
        if self.odbacanie is not None:
            self.odbacanie.rovno()
    
    def vzdialenost(self):
        dist = None
        if self.ultrazvuk is not None:
            dist = self.ultrazvuk.distance()
            print ("Measured Distance = %.1f cm" % dist)
        return dist
    
    def naraz(self):
        naraz = 0
        if self.crash_sensor is not None:
            naraz = self.crash_sensor.naraz()

    def flow_speed(self):
        speed = None
        if self.flow_sensor is not None:
            speed = self.flow_sensor.flow_speed()
            print("Flow speed = %.2f km/h" % speed if speed is not None else "Flow speed = None")
        return speed

    def acceleration(self):
        data = None
        if self.accelerometer is not None:
            data = self.accelerometer.acceleration()
            print("Accel - X: %.2f, Y: %.2f, Z: %.2f m/s^2" % (data['x'], data['y'], data['z']))
        return data

    def gyroscope(self):
        data = None
        if self.accelerometer is not None:
            data = self.accelerometer.gyroscope()
            print("Gyro  - X: %.2f, Y: %.2f, Z: %.2f deg/s" % (data['x'], data['y'], data['z']))
        return data

    def all_sensors(self):
        data = None
        if self.accelerometer is not None:
            data = self.accelerometer.all()
        return data