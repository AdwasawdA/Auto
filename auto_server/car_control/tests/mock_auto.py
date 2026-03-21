"""
MockAuto — drop-in replacement for pohyb2.Auto.
No GPIO, no I2C. Tracks calls so tests can assert on them.
"""


class MockAuto:
    def __init__(self):
        self.rychlost = 0
        self._dopredu = True
        self.steering = 0          # -100 left … 0 center … +100 right
        self.calls = []            # log of (method, kwargs)

    def _log(self, method, **kwargs):
        self.calls.append((method, kwargs))

    def dopredu(self, rychlost):
        self.rychlost = rychlost
        self._dopredu = True
        self._log("dopredu", rychlost=rychlost)

    def dozadu(self, rychlost):
        self.rychlost = rychlost
        self._dopredu = False
        self._log("dozadu", rychlost=rychlost)

    def stop(self):
        self.rychlost = 0
        self._dopredu = True
        self._log("stop")

    def doprava(self, percento):
        self.steering = percento
        self._log("doprava", percento=percento)

    def dolava(self, percento):
        self.steering = -percento
        self._log("dolava", percento=percento)

    def rovno(self):
        self.steering = 0
        self._log("rovno")

    def vzdialenost(self):
        self._log("vzdialenost")
        return 42.0   # fixed mock distance in cm

    def last_call(self):
        return self.calls[-1] if self.calls else None

    def reset(self):
        self.calls.clear()
        self.rychlost = 0
        self._dopredu = True
        self.steering = 0
