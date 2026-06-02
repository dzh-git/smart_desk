# Changes: Task-001

## Files
- [mod] D:\learning\smart_desktop\smart-desk\backend\services\event_bus.py
- [mod] D:\learning\smart_desktop\smart-desk\tests\test_event_bus.py

## Summary
Implemented in-process EventBus singleton with dict-dispatch pub/sub pattern. Zero external dependencies. Supports: subscribe/publish with multiple handlers per event, handler exception isolation, graceful no-handler publishing, and module-level singleton access via `event_bus`.

## Review Fixes
- **CR-001**: Replaced silent `except Exception: pass` with `logger.exception()` to log handler failures
- **CR-002**: Narrowed handler type hint from `Callable` to `Callable[[BaseEvent], None]` for type safety
- **CR-003**: Added `threading.Lock` around `_handlers` dict access in `subscribe()` and `publish()` to prevent check-then-act race condition where concurrent first-time subscriptions to the same event name would silently drop handlers. `publish()` only holds the lock for getting the handler list reference, releasing it before iterating handlers to avoid deadlocks.
- Added `test_handler_exception_logged` test to verify CR-001 fix
- Added `test_concurrent_subscribe_no_handlers_lost` test to verify CR-003 fix (500 iterations x 20 concurrent threads, each to fresh event names)
- Added `test_concurrent_subscribe_publish_no_errors` test to verify CR-003 fix (2-second stress test, 10 publishers + 10 subscribers)
- **CR-004**: Added `unsubscribe(event_name, handler)` method to EventBus. Handlers can now be removed. Uses `threading.Lock` for thread safety (same lock as subscribe/publish). Silently handles non-existent handler or event name removal (no-op). Added 4 tests: `test_unsubscribe_removes_handler`, `test_unsubscribe_nonexistent_handler_no_error`, `test_unsubscribe_nonexistent_event_no_error`, `test_unsubscribe_thread_safe`
- **CR-005**: Fixed `publish()` to copy the handler list (`list()`) under lock before iterating, preventing handler skip when `unsubscribe()` is called concurrently during publish iteration (in-place list mutation during iteration causes CPython iterator to skip elements). Added `test_publish_iterates_snapshot_not_live_list` test.
- **CR-006**: Fixed `unsubscribe()` to delete the `_handlers` dict key when the handler list becomes empty after removal, preventing unbounded memory growth from orphaned empty lists under dynamic event names. Added `test_unsubscribe_cleans_empty_handler_list` test.
- **CR-007**: Removed unused `errors = []` variable in `test_concurrent_subscribe_no_handlers_lost` — dead code leftover from copy-paste pattern.
- **CR-008**: Updated docstring in `test_concurrent_subscribe_no_handlers_lost` to remove misleading reference to `time.sleep(0)` which was never used; documented actual strategy (distinct event names + 500 iterations / 20 threads).
- **CR-009**: Added comprehensive docstrings to `BaseEvent` dataclass and `EventBus` class including all three public methods (`subscribe`, `unsubscribe`, `publish`), documenting thread-safety guarantees, synchronous handler invocation, non-idempotent subscribe behavior, silent no-op unsubscribe, and exception isolation via logging.
- **CR-010**: Removed misleading "Immutable" from `BaseEvent` class docstring and documented that `payload` is a shared mutable dict — the same BaseEvent instance is passed to every handler, so mutations propagate to subsequent handlers. Added `test_payload_is_mutable_and_shared` to verify and document this behavior.
- **CR-011**: Fixed class docstring to accurately describe "snapshot-based locking strategy" instead of "reentrant locking strategy" — the lock is released before handler iteration, so handlers can safely call subscribe/unsubscribe/publish during publish. The mechanism is snapshot iteration with minimal lock holding, not reentrancy (RLock). Added `test_publish_from_handler_does_not_deadlock` to verify that calling publish() from within a handler does not deadlock (lock is already released during iteration).
- **SR-001**: Fixed `test_publish_from_handler_does_not_deadlock` docstring which incorrectly claimed `threading.RLock` is needed as the fix mechanism. Updated to accurately describe snapshot-based iteration — the lock is released before handler iteration, so `threading.Lock` (non-reentrant) works fine because the outer `publish()` already released the lock before calling handlers. No RLock is needed.
