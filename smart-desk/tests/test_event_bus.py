import logging
import threading
import time

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


def test_multiple_handlers():
    bus = EventBus()
    calls = []

    bus.subscribe("multi", lambda e: calls.append("A"))
    bus.subscribe("multi", lambda e: calls.append("B"))
    bus.publish(BaseEvent(name="multi"))

    assert calls == ["A", "B"]


def test_handler_exception_isolated():
    bus = EventBus()
    calls = []

    bus.subscribe("err", lambda e: (_ for _ in ()).throw(Exception("boom")))
    bus.subscribe("err", lambda e: calls.append("survived"))
    bus.publish(BaseEvent(name="err"))

    assert calls == ["survived"]


def test_no_handlers_no_error():
    bus = EventBus()
    # Should not raise
    bus.publish(BaseEvent(name="no_such_event"))


def test_singleton_instance():
    from backend.services.event_bus import event_bus
    from backend.services.event_bus import event_bus as eb2
    assert event_bus is eb2



def test_concurrent_subscribe_no_handlers_lost():
    """CR-003: Concurrent subscribe to same NEW event must not lose handlers.

    The check-then-act race in subscribe():
        if name not in dict:          # Thread A sees False
            dict[name] = []           # Thread B overwrites A's list
        dict[name].append(h)          # Thread A appends to wrong list

    Without a lock, simultaneous first-time subscriptions to the same
    event name can silently drop handlers. We force the race by:
    - Using distinct event names per iteration (always "new" to the bus)
    - Running 500 iterations with 20 concurrent subscribe threads each
    """
    for _ in range(500):
        bus = EventBus()
        received = []
        lock = threading.Lock()
        event_name = f"ev_{_}"
        num_handlers = 20

        def subscribe_one(i):
            def handler(e):
                with lock:
                    received.append(i)
            bus.subscribe(event_name, handler)

        threads = [threading.Thread(target=subscribe_one, args=(i,)) for i in range(num_handlers)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        bus.publish(BaseEvent(name=event_name))
        # Every handler that was subscribed should be called
        assert len(received) == num_handlers, (
            f"Iteration {_}: expected {num_handlers} handlers called, "
            f"got {len(received)} (handlers lost to race condition)"
        )


def test_concurrent_subscribe_publish_no_errors():
    """CR-003: Heavy concurrent subscribe+publish must not raise exceptions."""
    bus = EventBus()
    errors = []
    lock = threading.Lock()
    stop = threading.Event()

    def publisher():
        while not stop.is_set():
            try:
                bus.publish(BaseEvent(name="ts"))
            except Exception as e:
                with lock:
                    errors.append(e)

    def subscriber():
        def handler(e):
            pass
        while not stop.is_set():
            try:
                bus.subscribe("ts", handler)
            except Exception as e:
                with lock:
                    errors.append(e)

    threads = []
    for _ in range(10):
        threads.append(threading.Thread(target=publisher))
        threads.append(threading.Thread(target=subscriber))

    for t in threads:
        t.start()

    time.sleep(2)
    stop.set()
    for t in threads:
        t.join(timeout=5)

    assert errors == [], f"Thread-safety errors: {errors}"


def test_handler_exception_logged(caplog):
    """CR-001: Handler exceptions must be logged via logging.exception()."""
    bus = EventBus()
    error_msg = "handler_bug_detected"

    bus.subscribe("err", lambda e: (_ for _ in ()).throw(ValueError(error_msg)))

    with caplog.at_level(logging.ERROR):
        bus.publish(BaseEvent(name="err"))

    assert error_msg in caplog.text


def test_unsubscribe_removes_handler():
    """CR-004: Unsubscribed handler must not be called on publish."""
    bus = EventBus()
    received = []

    def handler_a(event):
        received.append("A")

    def handler_b(event):
        received.append("B")

    bus.subscribe("ev", handler_a)
    bus.subscribe("ev", handler_b)
    bus.unsubscribe("ev", handler_a)
    bus.publish(BaseEvent(name="ev"))

    assert received == ["B"]


def test_unsubscribe_nonexistent_handler_no_error():
    """CR-004: Unsubscribing a handler not registered must not raise."""
    bus = EventBus()

    def handler(event):
        pass

    bus.unsubscribe("no_such_event", handler)


def test_unsubscribe_nonexistent_event_no_error():
    """CR-004: Unsubscribing from an event with no handlers must not raise."""
    bus = EventBus()

    def handler(event):
        pass

    bus.subscribe("real_event", handler)
    bus.unsubscribe("no_such_event", handler)
    # Must not raise; handler on real_event still works
    received = []
    bus.subscribe("real_event", lambda e: received.append("ok"))
    bus.publish(BaseEvent(name="real_event"))
    assert "ok" in received


def test_unsubscribe_thread_safe():
    """CR-004: Concurrent subscribe and unsubscribe must not raise or lose handlers."""
    bus = EventBus()
    errors = []
    lock = threading.Lock()
    stop = threading.Event()

    def sub_unsub():
        def handler(e):
            pass
        while not stop.is_set():
            try:
                bus.subscribe("ts", handler)
                bus.unsubscribe("ts", handler)
            except Exception as e:
                with lock:
                    errors.append(e)

    threads = [threading.Thread(target=sub_unsub) for _ in range(20)]
    for t in threads:
        t.start()

    time.sleep(1.5)
    stop.set()
    for t in threads:
        t.join(timeout=5)

    assert errors == [], f"Thread-safety errors during subscribe/unsubscribe: {errors}"


def test_publish_iterates_snapshot_not_live_list():
    """CR-005: publish() must iterate a snapshot, not the live handler list.

    When a handler unsubscribes another handler during publish(), the
    unsubscribed handler must still be called because publish iterates
    a snapshot taken before any mutations.
    """
    bus = EventBus()
    received = []

    def handler_a(event):
        received.append("A")
        bus.unsubscribe("ev", handler_b)

    def handler_b(event):
        received.append("B")

    bus.subscribe("ev", handler_a)
    bus.subscribe("ev", handler_b)
    bus.publish(BaseEvent(name="ev"))

    # Both handlers must fire: publish() iterates a snapshot
    assert "A" in received, "handler_a should have been called"
    assert "B" in received, (
        "CR-005: handler_b was skipped because publish() iterated "
        "the live list while handler_a mutated it via unsubscribe()"
    )


def test_unsubscribe_cleans_empty_handler_list():
    """CR-006: unsubscribe() must delete empty handler lists from _handlers dict.

    Without cleanup, unique event names (e.g. per-request UUIDs) cause
    unbounded memory growth as empty lists accumulate forever.
    """
    bus = EventBus()

    def handler(event):
        pass

    bus.subscribe("temp_event", handler)
    assert "temp_event" in bus._handlers

    bus.unsubscribe("temp_event", handler)
    assert "temp_event" not in bus._handlers, (
        "CR-006: empty handler list for 'temp_event' was not removed from "
        "_handlers dict — will cause unbounded memory growth"
    )


def test_publish_from_handler_does_not_deadlock():
    """CR-011: publish() from within a handler must not deadlock.

    The EventBus uses snapshot-based iteration: the handler list is copied
    under the lock, then the lock is released before iterating handlers.
    When a handler calls publish() (e.g., to chain events), the inner
    publish() can safely acquire the lock — even with threading.Lock
    (non-reentrant) — because the outer publish() already released the
    lock before calling handlers. No RLock is needed.

    This test verifies that chained publish() from within a handler
    executes correctly and handlers run in the expected order.
    """
    bus = EventBus()
    chain_result = []

    def inner_handler(event):
        chain_result.append("inner")

    def outer_handler(event):
        bus.subscribe("inner_event", inner_handler)
        bus.publish(BaseEvent(name="inner_event"))
        chain_result.append("outer")

    bus.subscribe("outer_event", outer_handler)
    bus.publish(BaseEvent(name="outer_event"))

    assert chain_result == ["inner", "outer"], (
        f"Expected ['inner', 'outer'], got {chain_result}. "
        "CR-011: publish() from handler deadlocked or failed because "
        "threading.Lock is not reentrant."
    )


def test_payload_is_mutable_and_shared():
    """CR-010: BaseEvent payload is a plain mutable dict shared across handlers.

    The same BaseEvent instance is passed to every handler. A handler that
    mutates event.payload will affect the payload seen by subsequent handlers
    — this is documented behavior, not a bug. Handlers must not mutate
    event.payload unless they intend to communicate with later handlers.
    """
    bus = EventBus()
    payloads_seen = []

    def handler_a(event):
        payloads_seen.append(dict(event.payload))
        event.payload["modified_by_a"] = True

    def handler_b(event):
        payloads_seen.append(dict(event.payload))

    bus.subscribe("ev", handler_a)
    bus.subscribe("ev", handler_b)
    bus.publish(BaseEvent(name="ev", payload={"initial": 1}))

    # handler_a saw original payload
    assert payloads_seen[0] == {"initial": 1}
    # handler_b sees the mutation from handler_a — shared mutable dict
    assert payloads_seen[1] == {"initial": 1, "modified_by_a": True}
