"""
Safety Monitor
Runs as a background daemon thread alongside server.py.

Responsibilities:
  1. Brake automatically when the ToF distance sensor reads < DISTANCE_THRESHOLD_MM.
  2. Brake + reverse automatically when the crash sensor is triggered.
  3. After a crash/too-close event, back away for REVERSE_DURATION seconds, then stop.

Usage — add these two lines inside _async_main() in server.py,
AFTER the `auto` variable has been assigned:

    from safety_monitor import SafetyMonitor
    SafetyMonitor(auto=auto, auto_lock=auto_lock).start()
"""

import logging
import threading
import time

log = logging.getLogger(__name__)

DISTANCE_THRESHOLD_MM = 400
REVERSE_SPEED         = 40
REVERSE_DURATION_S    = 1.0
REVERSE_COOLDOWN_S    = 2.0
POLL_INTERVAL_S       = 0.05

# ── Tuneable constants ────────────────────────────────────────────────────────
def update_settings(self, settings: dict):
        global DISTANCE_THRESHOLD_MM, REVERSE_SPEED, REVERSE_DURATION_S, REVERSE_COOLDOWN_S
        DISTANCE_THRESHOLD_MM = settings.get("safety_distance_mm",      DISTANCE_THRESHOLD_MM)
        REVERSE_SPEED         = settings.get("safety_reverse_speed",     REVERSE_SPEED)
        REVERSE_DURATION_S    = settings.get("safety_reverse_duration",  REVERSE_DURATION_S)
        REVERSE_COOLDOWN_S    = settings.get("safety_cooldown",          REVERSE_COOLDOWN_S)
        
# ─────────────────────────────────────────────────────────────────────────────

class SafetyMonitor:
    """
    Background thread that watches the distance sensor and crash sensor.
    It shares `auto_lock` with server.py so it never races with manual commands.
    """

    def __init__(self, auto, auto_lock: threading.Lock, get_distance_fn=None):
        self._auto = auto
        self._lock = auto_lock
        self._get_distance = get_distance_fn
        self._last_event_time = 0.0   # timestamp of the last reversal

        self._thread = threading.Thread(
            target=self._loop,
            name="safety-monitor",
            daemon=True,
        )

    def start(self):
        self._thread.start()
        log.info("SafetyMonitor started (threshold=%d mm, poll=%.0f Hz)",
                 DISTANCE_THRESHOLD_MM, 1 / POLL_INTERVAL_S)

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _cooldown_ok(self) -> bool:
        """Return True if enough time has passed since the last auto-reversal."""
        return (time.time() - self._last_event_time) >= REVERSE_COOLDOWN_S

    def _do_reverse(self, reason: str):
        """Stop, reverse for REVERSE_DURATION_S, then stop again."""
        log.warning("SafetyMonitor triggered (%s) — reversing", reason)
        self._last_event_time = time.time()

        with self._lock:
            self._auto.stop()
            self._auto.rovno()           # straighten steering while backing up
            self._auto.dozadu(REVERSE_SPEED)

        time.sleep(REVERSE_DURATION_S)

        with self._lock:
            self._auto.stop()

        log.info("SafetyMonitor: reversal complete")

    def _do_escape_forward(self, reason: str):
        """Stop, move forward for REVERSE_DURATION_S, then stop again."""
        log.warning("SafetyMonitor triggered (%s) — escaping forward", reason)
        self._last_event_time = time.time()

        with self._lock:
            self._auto.stop()
            self._auto.rovno()
            self._auto.dopredu(REVERSE_SPEED)

        time.sleep(REVERSE_DURATION_S)

        with self._lock:
            self._auto.stop()

        log.info("SafetyMonitor: forward escape complete")

    # ── Main loop ─────────────────────────────────────────────────────────────

    def _loop(self):
        while True:
            try:
                self._check()
            except Exception as exc:
                log.error("SafetyMonitor error: %s", exc)
            time.sleep(POLL_INTERVAL_S)

    def _check(self):
        auto = self._auto
        if auto is None:
            return

        # ── 1. Crash sensor ───────────────────────────────────────────────────
        if auto.crash_sensor is not None:
            with self._lock:
                hit = auto.crash_sensor.naraz()
            if hit and self._cooldown_ok():
                self._do_escape_forward("crash sensor")
                return   # skip distance check this cycle

        # ── 2. Distance / TofL sensor ──────────────────────────────────────────
        if self._get_distance is not None:
            dist = self._get_distance()   # uses cached value, no I2C hit

            if dist is not None and dist < DISTANCE_THRESHOLD_MM:
                if auto._dopredu and auto.rychlost > 0:
                    if self._cooldown_ok():
                        self._do_reverse(
                            f"distance {dist:.0f} mm < {DISTANCE_THRESHOLD_MM} mm"
                        )