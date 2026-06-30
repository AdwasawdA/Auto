"""
Launcher for RC Car server.
- Blinks LEDs while waiting for inference server
- Press crash sensor to skip inference and launch without it
- Once inference is reachable, lights all LEDs and launches server.py
"""
import asyncio
import logging
import os
import signal
import subprocess
import sys
import time
import threading

import RPi.GPIO as GPIO
import websockets

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
log = logging.getLogger("launcher")

# ── Pin config ────────────────────────────────────────────────────────────────
LED_PINS        = [5, 6, 13]       # Adeept hat LEDs
CRASH_PIN       = 8                # Crash sensor used as skip button
BLINK_INTERVAL  = 0.3              # seconds per LED step in animation
POLL_INTERVAL   = 5.0              # seconds between inference connection attempts
INFERENCE_URL   = "ws://10.42.0.168:8765"   # must match server.py
SERVER_SCRIPT   = os.path.join(os.path.dirname(__file__), "server.py")
# ─────────────────────────────────────────────────────────────────────────────


def setup_gpio():
    GPIO.setwarnings(False)
    GPIO.setmode(GPIO.BCM)
    for pin in LED_PINS:
        GPIO.setup(pin, GPIO.OUT)
        GPIO.output(pin, GPIO.LOW)
    GPIO.setup(CRASH_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)


def cleanup_gpio():
    for pin in LED_PINS:
        GPIO.output(pin, GPIO.LOW)
    GPIO.cleanup()


def leds_all(state: bool):
    for pin in LED_PINS:
        GPIO.output(pin, GPIO.HIGH if state else GPIO.LOW)


def leds_solid():
    leds_all(True)


def leds_off():
    leds_all(False)


class LEDAnimator:
    """
    Runs a looping chase animation on the 3 LEDs in a background thread.
    Call stop() to end the animation.
    """
    def __init__(self):
        self._running = False
        self._thread = None

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=1.0)
        leds_off()

    def _run(self):
        idx = 0
        while self._running:
            leds_off()
            GPIO.output(LED_PINS[idx], GPIO.HIGH)
            idx = (idx + 1) % len(LED_PINS)
            time.sleep(BLINK_INTERVAL)


async def try_connect_inference(url: str) -> bool:
    """Try to open a WebSocket connection to the inference server. Returns True on success."""
    try:
        async with websockets.connect(url, open_timeout=3) as ws:
            return True
    except Exception:
        return False


def crash_sensor_pressed() -> bool:
    """Returns True if crash sensor is currently pressed (pin pulled LOW)."""
    return GPIO.input(CRASH_PIN) == GPIO.LOW


def launch_server(with_inference: bool):
    """Replace this process with server.py (or launch without inference arg)."""
    cmd = [sys.executable, SERVER_SCRIPT]
    if not with_inference:
        cmd.append("--no-inference")
    log.info("Launching: %s", " ".join(cmd))
    # Use execv so server.py takes over this process — cleaner for systemd
    os.execv(sys.executable, cmd)


def main():
    setup_gpio()
    animator = LEDAnimator()
    animator.start()

    log.info("Waiting for inference server at %s", INFERENCE_URL)
    log.info("Press crash sensor to skip inference and start without it")

    last_poll = time.monotonic() - POLL_INTERVAL  # poll immediately on first loop

    try:
        while True:
            # Check skip button first
            if crash_sensor_pressed():
                log.info("Skip button pressed — launching without inference")
                animator.stop()
                leds_solid()
                time.sleep(0.5)
                cleanup_gpio()
                launch_server(with_inference=False)
                return  # unreachable after execv but keeps linter happy

            # Poll inference every POLL_INTERVAL seconds
            now = time.monotonic()
            if now - last_poll >= POLL_INTERVAL:
                last_poll = now
                log.info("Checking inference server...")
                connected = asyncio.run(try_connect_inference(INFERENCE_URL))
                if connected:
                    log.info("Inference server reachable — launching server")
                    animator.stop()
                    leds_solid()
                    time.sleep(0.5)
                    cleanup_gpio()
                    launch_server(with_inference=True)
                    return
                else:
                    log.info("Inference not reachable, retrying in %.0fs", POLL_INTERVAL)

            time.sleep(0.05)  # tight loop for responsive button

    except KeyboardInterrupt:
        log.info("Launcher interrupted")
        animator.stop()
        cleanup_gpio()
        sys.exit(0)


if __name__ == "__main__":
    main()
