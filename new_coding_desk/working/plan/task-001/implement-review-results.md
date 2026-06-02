# Implement Review Results: Task-001

## Spec Review Issues

### SR-001: test_publish_from_handler_does_not_deadlock docstring describes wrong fix mechanism
- Status: Resolved
- Description: The test docstring at test_event_bus.py lines 277-287 states "The fix is to use threading.RLock (reentrant) so the docstring claim of 'reentrant locking strategy' is accurate." This is factually incorrect. The actual code uses threading.Lock (non-reentrant) at event_bus.py line 47. The real fix is snapshot-based iteration — the lock is released before handler iteration, so re-acquiring it from within a handler is safe with a plain Lock. The test itself passes correctly because of this snapshot pattern, but the docstring documents a different (unimplemented) mechanism, misleading readers about how the deadlock prevention actually works.
- Decision Reason:

## Code Review Issues

### CR-001: Silent exception swallowing in publish() — no error visibility
- Status: Resolved

### CR-002: Handler type hint too broad — loses type safety
- Status: Resolved

### CR-003: No thread safety on EventBus handler dictionary
- Status: Resolved
- Description: The module-level `event_bus` singleton is shared across the application. `subscribe()` performs a non-atomic read-check-write on `self._handlers` followed by list append. `publish()` gets a reference to the handler list and iterates it. In a FastAPI app with sync endpoints or background tasks (which run in thread pools), concurrent subscribe+publish can cause `RuntimeError: dictionary changed size during iteration`, lost handler registrations, or silently dropped events. Since the EventBus is foundational infrastructure for all subsequent tasks, this race condition will propagate to every subscriber. Add a `threading.Lock` around `_handlers` access in both `subscribe()` and `publish()`.
- Decision Reason:

### CR-004: Missing unsubscribe() method — handlers cannot be removed
- Status: Resolved
- Description: The EventBus API only supports `subscribe()` and `publish()`. There is no `unsubscribe(event_name, handler)` method. On the module-level `event_bus` singleton (which lives for the entire application lifetime), any handler registered will never be garbage collected — the EventBus holds a strong reference via `self._handlers[event_name]`, which pins the handler and all its closure-captured variables. This causes unbounded memory growth in long-running applications whenever components register handlers dynamically (e.g., per-request WebSocket connections, plugin load/unload cycles). A standard pub/sub API must include unsubscribe for production readiness. The handler list-snapshot pattern already used by `publish()` (copy under lock, iterate outside lock) also works for safe removal during iteration.
- Decision Reason:

### CR-005: publish() iterates live handler list — race with concurrent unsubscribe() skips handlers
- Status: Resolved
- Description: In `publish()` (event_bus.py:38-47), the lock is held only for retrieving the handlers list reference at line 40: `handlers = self._handlers.get(event.name, [])`. The lock is then released, and the returned list object is iterated at line 41. If another thread calls `unsubscribe()` during this iteration, `handlers.remove(handler)` at line 34 mutates the same list object in-place. In CPython, in-place list mutation during iteration causes the iterator to skip elements — remaining handlers that were not yet visited may never be called. This is a correctness bug: a publish should either deliver to all currently-subscribed handlers or to none, but not to an arbitrary subset. The current `test_unsubscribe_thread_safe` test only stresses concurrent subscribe+unsubscribe without concurrent publish, so this race is untested. Fix: copy the list before releasing the lock — `handlers = list(self._handlers.get(event.name, []))` — so iteration is isolated from concurrent mutations.

### CR-006: Orphaned empty handler lists accumulate in `_handlers` dict — unbounded memory growth
- Status: Resolved
- Description: When all handlers for an event name are unsubscribed, `_handlers[event_name]` remains as an empty list `[]` — there is no cleanup. If the application uses dynamic event names (e.g., `f"task_complete_{uuid}"`), each unique name creates a permanent entry in the dict. Over the lifetime of a long-running server process, this grows without bound. Fix: in `unsubscribe()`, after removing the handler, delete the key if the list is now empty — `if not handlers: del self._handlers[event_name]`. For extra safety, this can also be done in `publish()` when the handlers list is empty, or a dedicated `clear_event(event_name)` method can be exposed.

### CR-007: Unused variable `errors` in test_concurrent_subscribe_no_handlers_lost
- Status: Resolved
- Description: At `test_event_bus.py:74`, `errors = []` is declared but never appended to or asserted on. The variable is dead code — a leftover from a copy-paste pattern used in the other concurrent stress tests (`test_concurrent_subscribe_publish_no_errors` and `test_unsubscribe_thread_safe`) where `errors` IS used. This does not affect test correctness but reduces code clarity and may confuse future readers who wonder why errors are collected but never checked.
- Decision Reason:

### CR-008: Outdated docstring in test_concurrent_subscribe_no_handlers_lost references unused strategy
- Status: Resolved
- Description: At `test_event_bus.py:70`, the docstring describes the race-widening strategy as including "Using time.sleep(0) between check and write to widen the race window". The actual test code never calls `time.sleep(0)`. The test relies on high iteration count (500) and thread count (20) instead. The docstring is misleading — it documents a tactic that was never implemented. Fix: update the docstring to accurately reflect the actual strategy (distinct event names + high iteration/thread counts).
- Decision Reason:

### CR-009: EventBus public API lacks docstrings
- Status: Resolved
- Description: The `EventBus` class (event_bus.py:18) and its three public methods — `subscribe()` (line 23), `unsubscribe()` (line 29), `publish()` (line 40) — have no docstrings. Neither does `BaseEvent` (line 11). This is the foundational module that all 25 subsequent tasks depend on for inter-component communication. Without docstrings, developers integrating with the EventBus must read the implementation to understand: whether handlers are called synchronously or asynchronously, whether subscribe is idempotent (it is not — duplicate subscriptions result in duplicate calls), whether unsubscribe is safe for non-existent handlers (it is — silently no-ops), and the thread-safety guarantees. The code is short and clean, which helps, but production infrastructure modules should document their contract explicitly.
- Decision Reason:

### CR-010: BaseEvent docstring claims "Immutable" but payload is a mutable dict
- Status: Resolved
- Description: At `event_bus.py:13`, the class docstring describes BaseEvent as "Immutable event envelope for publishing on the EventBus." However, at line 22 the `payload` field is a plain mutable `dict`. During `publish()`, the same single BaseEvent instance is passed to every handler in sequence. Any handler that mutates `event.payload` (e.g., `event.payload["key"] = "new"`) will corrupt the payload seen by all subsequent handlers in the iteration — a subtle cross-handler data corruption bug that can be very hard to diagnose. Developers who read the "Immutable" claim in the docstring will reasonably assume payload mutations are safe or impossible. Fix: either remove the word "Immutable" from the docstring and document that payload is shared/mutable, or wrap payload in `types.MappingProxyType` at construction time to enforce immutability.
- Decision Reason:

### CR-011: EventBus class docstring incorrectly claims "reentrant locking strategy"
- Status: Resolved
- Description: At `event_bus.py:39`, the class docstring states "subscribe, unsubscribe, and publish use a reentrant locking strategy." However, the code uses `threading.Lock()` (line 44), which is explicitly NOT reentrant — `threading.RLock` is the reentrant variant. The code is functionally correct: the lock is released before handlers are iterated in `publish()`, which is why handlers CAN safely call subscribe/unsubscribe during publish. But the mechanism is "snapshot-based iteration with minimal lock holding," not reentrancy. A developer who trusts the word "reentrant" and calls `bus.publish()` from inside a handler expecting reentrant lock acquisition will deadlock — `publish()` acquires the same Lock, and `Lock` does not allow the same thread to acquire it twice. The fix is to replace "reentrant locking strategy" with accurate terminology such as "snapshot-based locking strategy" or "minimal lock holding with snapshot iteration."
- Decision Reason:
