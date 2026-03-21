"""
Tests for car_control server.
Run from services/car_control/:  pytest tests/
"""
import json
import sys
import os
import pytest

# Make sure we can import server and mock from this location
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from tests.mock_auto import MockAuto
import server as srv


@pytest.fixture(autouse=True)
def inject_mock_auto():
    """Replace the global `auto` in server with a fresh MockAuto before each test."""
    mock = MockAuto()
    srv.auto = mock
    yield mock
    srv.auto = None


# ── handle_command dispatch ──────────────────────────────────────

class TestHandleCommand:

    def test_dopredu(self, inject_mock_auto):
        res = srv.handle_command({"action": "dopredu", "value": 70})
        assert res["ok"] is True
        assert inject_mock_auto.rychlost == 70
        assert inject_mock_auto._dopredu is True

    def test_dozadu(self, inject_mock_auto):
        res = srv.handle_command({"action": "dozadu", "value": 40})
        assert res["ok"] is True
        assert inject_mock_auto.rychlost == 40
        assert inject_mock_auto._dopredu is False

    def test_stop(self, inject_mock_auto):
        inject_mock_auto.dopredu(60)
        res = srv.handle_command({"action": "stop"})
        assert res["ok"] is True
        assert inject_mock_auto.rychlost == 0

    def test_doprava(self, inject_mock_auto):
        res = srv.handle_command({"action": "doprava", "value": 60})
        assert res["ok"] is True
        assert inject_mock_auto.steering == 60

    def test_dolava(self, inject_mock_auto):
        res = srv.handle_command({"action": "dolava", "value": 80})
        assert res["ok"] is True
        assert inject_mock_auto.steering == -80

    def test_rovno(self, inject_mock_auto):
        inject_mock_auto.doprava(50)
        res = srv.handle_command({"action": "rovno"})
        assert res["ok"] is True
        assert inject_mock_auto.steering == 0

    def test_vzdialenost(self, inject_mock_auto):
        res = srv.handle_command({"action": "vzdialenost"})
        assert res["ok"] is True
        assert res["distance"] == 42.0

    def test_unknown_action(self, inject_mock_auto):
        res = srv.handle_command({"action": "flyaway"})
        assert res["ok"] is False
        assert "Unknown action" in res["error"]

    def test_default_value_used_when_missing(self, inject_mock_auto):
        # value defaults to 50 if not provided
        res = srv.handle_command({"action": "dopredu"})
        assert res["ok"] is True
        assert inject_mock_auto.rychlost == 50

    def test_invalid_json_type_handled(self, inject_mock_auto):
        # value as string that can't convert to int
        res = srv.handle_command({"action": "dopredu", "value": "fast"})
        assert res["ok"] is False


# ── MockAuto self-tests ──────────────────────────────────────────

class TestMockAuto:

    def test_initial_state(self):
        m = MockAuto()
        assert m.rychlost == 0
        assert m._dopredu is True
        assert m.steering == 0

    def test_call_log(self):
        m = MockAuto()
        m.dopredu(30)
        m.doprava(50)
        assert len(m.calls) == 2
        assert m.calls[0] == ("dopredu", {"rychlost": 30})
        assert m.calls[1] == ("doprava", {"percento": 50})

    def test_reset(self):
        m = MockAuto()
        m.dopredu(80)
        m.reset()
        assert m.rychlost == 0
        assert m.calls == []

    def test_last_call(self):
        m = MockAuto()
        assert m.last_call() is None
        m.stop()
        assert m.last_call() == ("stop", {})

    def test_vzdialenost_returns_float(self):
        m = MockAuto()
        d = m.vzdialenost()
        assert isinstance(d, float)


# ── Flask test client (integration) ─────────────────────────────

@pytest.fixture
def client(inject_mock_auto):
    srv.app.config["TESTING"] = True
    with srv.app.test_client() as c:
        yield c


class TestRoutes:

    def test_index_returns_200(self, client):
        res = client.get("/")
        assert res.status_code == 200
        assert b"CAR" in res.data or b"ctrl" in res.data.lower()
