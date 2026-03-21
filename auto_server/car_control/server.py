"""
Car Control Server
Runs on Raspberry Pi 4. Hosts the web UI and handles WebSocket commands.

Usage:
    python server.py                  # uses real hardware
    python server.py --mock           # uses mock Auto (for dev/testing)
"""
import argparse
import json
import logging
import threading
from flask import Flask, render_template

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

app = Flask(__name__)

# flask_sock is only needed at runtime (not during unit tests)
try:
    from flask_sock import Sock
    sock = Sock(app)
    _has_sock = True
except ImportError:
    sock = None
    _has_sock = False

# Will be set to an Auto instance (real or mock) at startup
auto = None
auto_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Command dispatch
# ---------------------------------------------------------------------------

def handle_command(data: dict) -> dict:
    """
    Route a parsed JSON command to the correct Auto method.
    Returns a dict that is sent back to the client as JSON.
    """
    action = data.get("action")
    value = data.get("value", 20)  # default speed/steering 50%

    try:
        if action == "dopredu":
            with auto_lock:
                auto.dopredu(int(value))
            return {"ok": True, "action": action, "value": value}

        elif action == "dozadu":
            with auto_lock:
                auto.dozadu(int(value))
            return {"ok": True, "action": action, "value": value}

        elif action == "stop":
            with auto_lock:
                auto.stop()
            return {"ok": True, "action": action}

        elif action == "doprava":
            with auto_lock:
                auto.doprava(int(value))
            return {"ok": True, "action": action, "value": value}

        elif action == "dolava":
            with auto_lock:
                auto.dolava(int(value))
            return {"ok": True, "action": action, "value": value}

        elif action == "rovno":
            with auto_lock:
                auto.rovno()
            return {"ok": True, "action": action}

        elif action == "vzdialenost":
            with auto_lock:
                dist = auto.vzdialenost()
            return {"ok": True, "action": action, "distance": dist}

        else:
            log.warning("Unknown action: %s", action)
            return {"ok": False, "error": f"Unknown action: {action}"}

    except Exception as e:
        log.error("Error handling command %s: %s", action, e)
        return {"ok": False, "error": str(e)}


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


def _register_ws():
    pass  # defined below if sock available

if _has_sock:
    @sock.route("/ws")
    def websocket(ws):
        log.info("Client connected")
        try:
            while True:
                raw = ws.receive()
                if raw is None:
                    break
                try:
                    data = json.loads(raw)
                    log.info("Command: %s", data)
                    response = handle_command(data)
                except json.JSONDecodeError:
                    response = {"ok": False, "error": "Invalid JSON"}
                ws.send(json.dumps(response))
        except Exception as e:
            log.info("Client disconnected: %s", e)


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

def main():
    global auto

    parser = argparse.ArgumentParser(description="Car Control Server")
    parser.add_argument("--mock", action="store_true", help="Use mock hardware (no RPi needed)")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=5000, help="Port (default: 5000)")
    args = parser.parse_args()

    if args.mock:
        log.info("Starting with MOCK hardware")
        from tests.mock_auto import MockAuto
        auto = MockAuto()
    else:
        log.info("Starting with REAL hardware")
        from car_setup import create_auto
        auto = create_auto()

    log.info("Car control server starting on http://%s:%d", args.host, args.port)
    app.run(host=args.host, port=args.port, debug=False)


if __name__ == "__main__":
    main()
