# Task 001: EventBus Implementation

## Project Overview

- **Goal:** Migrate SmartDesk from direct callback architecture to EventBus-driven decoupled architecture
- **Architecture:** Router → Service → Repository → SQLite, with in-process EventBus for decoupling
- **Tech Stack:** Python 3.11+, FastAPI, SQLAlchemy 2.0, SQLite, WebSocket

## Task Objective

Implement the in-process EventBus singleton — the foundational decoupling mechanism. All subsequent Service and Router refactoring depends on this EventBus. It is a simple dict-dispatch pub/sub with zero external dependencies.

This is Task 1 of 26.

---

**Files:**
- Create: `D:\learning\smart_desktop\smart-desk\backend\services\event_bus.py`
- Test: `D:\learning\smart_desktop\smart-desk\tests\test_event_bus.py`

- [ ] **Step 1: Write the failing test — publish and subscribe**

```python
# tests/test_event_bus.py
from backend.services.event_bus import EventBus, BaseEvent


def test_subscribe_and_publish():
    bus = EventBus()
    received = []

    def handler(event):
        received.append(event)

    bus.subscribe("test_event", handler)
    event = BaseEvent(name="test_event", payload={"key": "value"})
    bus.publish(event)

    assert len(received) == 1
    assert received[0].payload["key"] == "value"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_event_bus.py::test_subscribe_and_publish -v`
Expected: FAIL with ModuleNotFoundError or ImportError

- [ ] **Step 3: Write minimal implementation**

```python
# backend/services/event_bus.py
from __future__ import annotations
from dataclasses import dataclass, field
from collections.abc import Callable
import time


@dataclass
class BaseEvent:
    name: str
    payload: dict = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


class EventBus:
    def __init__(self):
        self._handlers: dict[str, list[Callable]] = {}

    def subscribe(self, event_name: str, handler: Callable) -> None:
        if event_name not in self._handlers:
            self._handlers[event_name] = []
        self._handlers[event_name].append(handler)

    def publish(self, event: BaseEvent) -> None:
        handlers = self._handlers.get(event.name, [])
        for handler in handlers:
            try:
                handler(event)
            except Exception:
                pass  # handler errors don't affect other handlers
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_event_bus.py::test_subscribe_and_publish -v`
Expected: PASS

- [ ] **Step 5: Write failing test — multiple handlers**

```python
def test_multiple_handlers():
    bus = EventBus()
    calls = []

    bus.subscribe("multi", lambda e: calls.append("A"))
    bus.subscribe("multi", lambda e: calls.append("B"))
    bus.publish(BaseEvent(name="multi"))

    assert calls == ["A", "B"]
```

- [ ] **Step 6: Run test to verify it fails**

Run: `pytest tests/test_event_bus.py::test_multiple_handlers -v`
Expected: PASS (already works) — skip to next

- [ ] **Step 7: Write failing test — handler exception isolated**

```python
def test_handler_exception_isolated():
    bus = EventBus()
    calls = []

    bus.subscribe("err", lambda e: (_ for _ in ()).throw(Exception("boom")))
    bus.subscribe("err", lambda e: calls.append("survived"))
    bus.publish(BaseEvent(name="err"))

    assert calls == ["survived"]
```

- [ ] **Step 8: Run test to verify**

Run: `pytest tests/test_event_bus.py::test_handler_exception_isolated -v`
Expected: PASS (already handles via try/except)

- [ ] **Step 9: Write failing test — no handlers for event**

```python
def test_no_handlers_no_error():
    bus = EventBus()
    # Should not raise
    bus.publish(BaseEvent(name="no_such_event"))
```

- [ ] **Step 10: Run test to verify**

Run: `pytest tests/test_event_bus.py::test_no_handlers_no_error -v`
Expected: PASS

- [ ] **Step 11: Write failing test — single instance**

```python
def test_singleton_instance():
    from backend.services.event_bus import event_bus
    from backend.services.event_bus import event_bus as eb2
    assert event_bus is eb2
```

- [ ] **Step 12: Add singleton to implementation**

Add at bottom of `event_bus.py`:
```python
# Singleton
event_bus = EventBus()
```

- [ ] **Step 13: Run all tests**

Run: `pytest tests/test_event_bus.py -v`
Expected: 5 PASS
