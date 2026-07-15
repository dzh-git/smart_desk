from backend.events import BaseEvent
from backend.hardware.arduino_manager import ArduinoManager
from backend.hardware.lighting_manager import LightingManager


class FakeGateway:
    seat_ids = [1, 2]

    def __init__(self):
        self.commands = []

    def send(self, seat_id, command, arg=None):
        self.commands.append((seat_id, command, arg))
        return True


def event(name: str, **payload) -> BaseEvent:
    return BaseEvent(event_name=name, meeting_id=1, payload=payload)


def test_base_and_overlay_priority_and_cleanup(monkeypatch):
    gateway = FakeGateway()
    manager = LightingManager(gateway)
    monkeypatch.setattr(manager, "_schedule", lambda *args, **kwargs: None)

    manager._on_meeting_started(event("meeting_started"))
    manager._on_agenda_updated(event("agenda_updated", current_agenda_id=4))
    manager._on_speaker_speaking(event("speaker_speaking", seat_id=1))
    assert manager.seat_mode[1] == "AI_SPEAKING"

    manager._on_vote_started(event("vote_started"))
    assert manager.seat_mode[1] == "VOTE_OPEN"
    manager._on_service_call_created(event("service_call_created", seat_id=1))
    assert manager.seat_mode[1] == "SERVICE_CALL"

    manager._on_service_call_finished(event("service_call_resolved", seat_id=1))
    assert manager.seat_mode[1] == "VOTE_OPEN"
    manager._on_meeting_ended(event("meeting_ended"))
    assert manager.seat_mode[1] == "MEETING_ENDED"
    assert manager.overlays[1] == {}


def test_agenda_create_without_current_keeps_meeting_mode(monkeypatch):
    manager = LightingManager(FakeGateway())
    monkeypatch.setattr(manager, "_schedule", lambda *args, **kwargs: None)
    manager._on_meeting_started(event("meeting_started"))
    manager._on_agenda_updated(event("agenda_updated", action="create", current_agenda_id=None))
    assert set(manager.seat_mode.values()) == {"MEETING_ACTIVE"}


def test_reconnect_resends_intended_mode(monkeypatch):
    gateway = FakeGateway()
    manager = LightingManager(gateway)
    monkeypatch.setattr(manager, "_schedule", lambda *args, **kwargs: None)
    manager._on_meeting_started(event("meeting_started"))
    gateway.commands.clear()
    manager._on_connection(1, True)
    assert gateway.commands == [(1, "SET_MODE", "MEETING_ACTIVE")]


def test_stale_timer_cannot_clear_newer_overlay(monkeypatch):
    timers = []

    class FakeTimer:
        def __init__(self, delay, callback):
            self.callback = callback
            self.daemon = False
            timers.append(self)

        def start(self):
            pass

        def cancel(self):
            pass

    monkeypatch.setattr(
        "backend.hardware.lighting_manager.threading.Timer", FakeTimer,
    )
    manager = LightingManager(FakeGateway())
    manager._set_overlay(1, "vote", "VOTE_OPEN", 1)
    old_timer = timers[-1]
    manager._set_overlay(1, "vote", "VOTE_CLOSED", 1)
    old_timer.callback()
    assert manager.seat_mode[1] == "VOTE_CLOSED"


def test_arduino_ack_tracks_confirmed_not_intended_mode():
    manager = ArduinoManager({"enabled": False})
    manager.last_command = "SET_MODE VOTE_OPEN"
    manager.command_pending = True
    manager._handle_line("OK SET_MODE VOTE_OPEN")
    assert manager.current_mode == "VOTE_OPEN"
    assert manager.command_pending is False
    assert manager.last_ack_at is not None


def test_arduino_missing_pyserial_is_reported(monkeypatch):
    monkeypatch.setattr("backend.hardware.arduino_manager._SERIAL_AVAILABLE", False)
    manager = ArduinoManager({"enabled": True, "port": "COM9"})
    assert manager.enabled is False
    assert manager.last_error == "pyserial not installed"
