import logging
import threading
import time
from collections import deque
from typing import Callable, List, Optional

log = logging.getLogger(__name__)

# ── default constants (overridable at runtime via update_settings) ────────────
FRAME_W         = 640
FRAME_H         = 480
FRAME_CENTER_X  = FRAME_W // 2        # 320

EMA_ALPHA       = 0.25                # bbox center smoother (lower = smoother)
DEAD_ZONE_PX    = 30                  # ±px horizontal dead zone
STEER_MAX_ERROR = 200                 # px where steering reaches STEER_MAX_PCT
STEER_MAX_PCT   = 20                  # max steering % (hardware limit for lego axles)

# bbox-height distance zones (px in 480px frame)
BBOX_H_STOP     = 455                 # > this → too close, stop  (~< 0.8 m)
BBOX_H_HOLD     = 400                 # hold position here (~1 m)
BBOX_H_SLOW     = 280                 # creep toward person (~1.5 m)
                                      # < 280 → drive toward person (~> 2 m)
SPEED_SLOW      = 50
SPEED_DRIVE     = 80

# ToF-based distance zones (mm) — disabled, kept for reference
# TARGET_NEAR_MM  = 600
# TARGET_FAR_MM   = 800
# SLOW_ZONE_MM    = 1300
# TOF_WINDOW      = 5

MIN_CONFIDENCE  = 0.45                # ignore detections below this
LOST_TIMEOUT_S  = 1.5                 # stop if no person detected for this long
CONTROL_HZ      = 10                  # control loop rate
# ─────────────────────────────────────────────────────────────────────────────


class PersonFollower:
    """
    Person-following controller. Runs a 10 Hz background daemon thread that
    reads camera detections and issues motor commands based on bbox position.

    All tunable parameters live as instance variables and can be updated at
    runtime via update_settings() without restarting.

    Thread-safe: all public methods can be called from Flask threads.
    """

    def __init__(
        self,
        auto,
        get_distance_fn: Callable[[], Optional[float]],
        get_detections_fn: Callable[[], List],
        auto_lock: Optional[threading.Lock] = None,
        settings: Optional[dict] = None,
    ):
        self._auto           = auto
        self._get_distance   = get_distance_fn   # kept for future ToF use
        self._get_detections = get_detections_fn
        self._auto_lock      = auto_lock or threading.Lock()

        self._enabled          = False
        self._person_detected  = False
        self._lock             = threading.Lock()

        self._ema_cx: Optional[float] = None
        # self._tof_window: deque = deque(maxlen=TOF_WINDOW)  # ToF disabled
        self._last_seen: float = 0.0

        # runtime-tunable parameters
        s = settings or {}
        self.ema_alpha      = float(s.get("ema_alpha",          EMA_ALPHA))
        self.dead_zone_px   = int(s.get("dead_zone_px",         DEAD_ZONE_PX))
        self.steer_max_pct  = int(s.get("follow_steer_max",     STEER_MAX_PCT))
        self.bbox_h_stop    = int(s.get("bbox_h_stop",          BBOX_H_STOP))
        self.bbox_h_hold    = int(s.get("bbox_h_hold",          BBOX_H_HOLD))
        self.bbox_h_slow    = int(s.get("bbox_h_slow",          BBOX_H_SLOW))
        self.speed_slow     = int(s.get("follow_speed_slow",    SPEED_SLOW))
        self.speed_drive    = int(s.get("follow_speed_drive",   SPEED_DRIVE))

        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="person-follower"
        )
        self._thread.start()

    # ── public API ────────────────────────────────────────────────────────────

    def enable(self) -> None:
        with self._lock:
            self._enabled         = True
            self._person_detected = False
            self._ema_cx          = None
            # self._tof_window.clear()  # ToF disabled
            self._last_seen = time.monotonic()
        log.info("PersonFollower enabled")

    def disable(self) -> None:
        with self._lock:
            self._enabled         = False
            self._person_detected = False
        self._safe_stop()
        log.info("PersonFollower disabled")

    @property
    def is_enabled(self) -> bool:
        with self._lock:
            return self._enabled

    def get_status(self) -> dict:
        with self._lock:
            return {
                "follow_enabled":  self._enabled,
                "person_detected": self._person_detected,
            }

    def update_settings(self, s: dict) -> None:
        with self._lock:
            if "ema_alpha"          in s: self.ema_alpha     = float(s["ema_alpha"])
            if "dead_zone_px"       in s: self.dead_zone_px  = int(s["dead_zone_px"])
            if "follow_steer_max"   in s: self.steer_max_pct = int(s["follow_steer_max"])
            if "bbox_h_stop"        in s: self.bbox_h_stop   = int(s["bbox_h_stop"])
            if "bbox_h_hold"        in s: self.bbox_h_hold   = int(s["bbox_h_hold"])
            if "bbox_h_slow"        in s: self.bbox_h_slow   = int(s["bbox_h_slow"])
            if "follow_speed_slow"  in s: self.speed_slow    = int(s["follow_speed_slow"])
            if "follow_speed_drive" in s: self.speed_drive   = int(s["follow_speed_drive"])

    # ── control loop ─────────────────────────────────────────────────────────

    def _loop(self) -> None:
        interval = 1.0 / CONTROL_HZ
        while True:
            t0 = time.monotonic()
            try:
                if self.is_enabled:
                    self._tick()
            except Exception:
                log.exception("PersonFollower tick error")
            elapsed = time.monotonic() - t0
            time.sleep(max(0.0, interval - elapsed))

    def _tick(self) -> None:
        detections = self._get_detections()
        person     = self._select_person(detections)

        # ToF disabled — uncomment to re-enable
        # raw_dist = self._get_distance()
        # if raw_dist is not None and 0 < raw_dist < 4000:
        #     self._tof_window.append(raw_dist)
        # dist = self._median_distance()

        now = time.monotonic()

        if person is not None:
            self._last_seen = now
            with self._lock:
                self._person_detected = True
        else:
            with self._lock:
                self._person_detected = False

        # person lost for too long → stop
        if (now - self._last_seen) > LOST_TIMEOUT_S:
            self._safe_stop()
            return

        # person momentarily absent but within timeout → hold last commands
        if person is None:
            return

        # snapshot mutable settings so they stay consistent within this tick
        with self._lock:
            ema_alpha    = self.ema_alpha
            dead_zone    = self.dead_zone_px
            steer_max    = self.steer_max_pct
            bbox_h_stop  = self.bbox_h_stop
            bbox_h_hold  = self.bbox_h_hold
            bbox_h_slow  = self.bbox_h_slow
            speed_slow   = self.speed_slow
            speed_drive  = self.speed_drive

        # update EMA on horizontal position
        raw_cx = person.bbox_center[0]
        if self._ema_cx is None:
            self._ema_cx = raw_cx
        else:
            self._ema_cx = ema_alpha * raw_cx + (1 - ema_alpha) * self._ema_cx

        bbox_h = person.bbox[3] - person.bbox[1]

        if bbox_h > bbox_h_stop:
            self._safe_stop()
            return

        if bbox_h > bbox_h_hold:
            with self._auto_lock:
                self._auto.stop()
                self._apply_steering(self._ema_cx, dead_zone, steer_max)
            return

        with self._auto_lock:
            self._apply_steering(self._ema_cx, dead_zone, steer_max)
            if bbox_h > bbox_h_slow:
                self._auto.dopredu(speed_slow)
            else:
                self._auto.dopredu(speed_drive)

    # ── helpers ───────────────────────────────────────────────────────────────

    def _select_person(self, detections) -> Optional[object]:
        persons = [
            d for d in detections
            if d.class_name == "person" and d.confidence >= MIN_CONFIDENCE
        ]
        if not persons:
            return None
        return max(persons, key=lambda d: d.confidence)

    # def _median_distance(self) -> Optional[float]:  # ToF disabled
    #     if not self._tof_window:
    #         return None
    #     s = sorted(self._tof_window)
    #     n = len(s)
    #     mid = n // 2
    #     return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2.0

    def _apply_steering(self, smoothed_cx: float, dead_zone: int, steer_max: int) -> None:
        error   = smoothed_cx - FRAME_CENTER_X
        abs_err = abs(error)

        if abs_err < dead_zone:
            self._auto.rovno()
            return

        effective = abs_err - dead_zone
        pct = min(effective / (STEER_MAX_ERROR - dead_zone), 1.0) * steer_max
        pct = int(pct)

        if error > 0:
            self._auto.doprava(pct)
        else:
            self._auto.dolava(pct)

    def _safe_stop(self) -> None:
        try:
            with self._auto_lock:
                self._auto.stop()
                self._auto.rovno()
        except Exception:
            log.exception("PersonFollower safe_stop error")
