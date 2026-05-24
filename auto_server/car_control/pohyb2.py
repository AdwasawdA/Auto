from board import SCL, SDA
import busio
from adafruit_motor import servo
from adafruit_pca9685 import PCA9685
import RPi.GPIO as GPIO
import time
GPIO.setwarnings(False)
GPIO.setmode(GPIO.BCM)
import adafruit_vl53l0x



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
    def __init__(self, scl = SCL, sda = SDA):
        i2c = busio.I2C(scl, sda)
        self.tofl = adafruit_vl53l0x.VL53L0X(i2c)
    def distance(self):
        return self.tofl.range
        
class Crash_Sensor:
    def __init__(self, pin = None):
        GPIO.setup(pin, GPIO.IN)
        self.pin = pin
    def naraz(self):
        if GPIO.input(8) == GPIO.LOW:
            return 1

class Auto:
    def __init__(self, pohon = None, odbacanie = None, 
                 ultrazvuk = None, crash_sensor = None, sleep_time = 0.05):
        self.pohon = pohon
        self.odbacanie = odbacanie
        self.ultrazvuk = ultrazvuk
        self.crash_sensor = crash_sensor
        self._dopredu = True
        self.rychlost = 0
        self.sleep_time = sleep_time

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