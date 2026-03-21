# car_control

WebSocket control server + mobile web UI for the RC car.  
Runs on Raspberry Pi 4. Separate from the camera/YOLO inference service.

## Structure

```
car_control/
├── server.py          # Flask app + WebSocket handler
├── car_setup.py       # Hardware initialisation (RPi only)
├── pohyb2.py          # Motor/servo/sensor classes (your original code)
├── templates/
│   └── index.html     # Mobile-first control UI
├── tests/
│   ├── mock_auto.py   # Hardware-free MockAuto for testing
│   └── test_server.py # Unit + integration tests
└── pyproject.toml
```

## Setup

```bash
# Install uv if needed
curl -LsSf https://astral.sh/uv/install.sh | sh

# Dev environment (no RPi hardware needed)
uv sync --extra dev

# RPi environment (includes GPIO + Adafruit libs)
uv sync --extra rpi --extra dev
```

## Run

```bash
# On Raspberry Pi (real hardware)
uv run python server.py

# On any machine for development (mock hardware)
uv run python server.py --mock

# Custom host/port
uv run python server.py --mock --host 0.0.0.0 --port 8080
```

Then open `http://<rpi-ip>:5000` on your phone.

## WebSocket API

Connect to `ws://<rpi-ip>:5000/ws`

### Commands (send as JSON)

| Action | Params | Description |
|---|---|---|
| `dopredu` | `value: 0–100` | Drive forward at speed % |
| `dozadu` | `value: 0–100` | Drive backward at speed % |
| `stop` | — | Stop motors (smooth ramp down) |
| `doprava` | `value: 0–100` | Steer right at % |
| `dolava` | `value: 0–100` | Steer left at % |
| `rovno` | — | Straighten steering |
| `vzdialenost` | — | Query distance sensor |

### Response

```json
{ "ok": true, "action": "dopredu", "value": 60 }
{ "ok": true, "action": "vzdialenost", "distance": 34.5 }
{ "ok": false, "error": "Unknown action: fly" }
```

## Tests

```bash
uv run pytest
uv run pytest --cov=server --cov-report=term-missing
```
