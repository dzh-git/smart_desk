# Implement Review Results: Task-010

## Spec Review Issues

## Code Review Issues

### CR-001: Unreliable language auto-detection in on_translation_final
- Status: Resolved
- Description: `translation_service.py:62` detects source language via `any('一' <= c <= '鿿' for c in zh)`. This heuristic has multiple failure modes: (a) CJK range misses Extension A characters (U+3400-U+4DBF); (b) empty `zh` string defaults to `"en"` regardless of actual source language; (c) mixed-language or punctuation-only text produces arbitrary results; (d) the detection is redundant -- the caller (SpeechModule) already knows source/target languages. The `zh`/`en` parameter names imply known direction but the auto-detection contradicts them. Wrong source_lang/target_lang gets persisted to the DB, corrupting translation history queries.
- Decision Reason: 

### CR-002: meeting_id missing from translation_final event payload
- Status: Resolved
- Description: `translation_service.py:69-75` publishes `translation_final` event with payload keys `zh, en, seat_id, segment_id, is_final` but omits `meeting_id`. In an EventBus-driven architecture, subscribers (e.g., WebSocket broadcaster) cannot route the event to the correct meeting room without cross-referencing seat_id against some external mapping. The `meeting_id` is already a parameter of `on_translation_final` (line 59) and used for the DB upsert (line 64), so it is available and should be included.
- Decision Reason: 

### CR-003: seat_id falsy check instead of is-not-None in get_history
- Status: Resolved
- Description: `translation_service.py:52` uses `if seat_id:` to branch between `list_by_meeting_seat` and `list_by_meeting`. If `seat_id=0` were ever passed, it would be treated as falsy and fall through to the non-filtered path. While seat IDs in this codebase are 1-10, this pattern is fragile and contradicts the type hint `int | None`. Should use `if seat_id is not None:`.
- Decision Reason: 

### CR-004: self.mt attribute stored but never referenced
- Status: Resolved
- Description: `translation_service.py:10,15` accepts `mt_engine` in `__init__` and stores it as `self.mt`, but no method in the class ever reads `self.mt`. The `ready` property (line 17-21) checks only `self.speech`, not `self.mt`. If `mt_engine` is meant to be used by this service, its readiness should also be checked; if it is only for SpeechModule initialization, it should not be stored as an instance attribute on TranslationService.
- Decision Reason: 

### CR-005: attendee_repo injected but unused in DashboardService
- Status: Resolved
- Description: `dashboard_service.py:8,12` accepts `attendee_repo` in `__init__` and stores it as `self.attendee_repo`, but `get_dashboard` never uses it. The `seats` block (lines 39-42) returns `attendee_id` as an opaque integer without resolving attendee names. This forces the frontend to make additional API calls to resolve attendee identities, and forces callers to construct and pass an AttendeeRepository that is never consulted.
- Decision Reason: 

### CR-006: Test coverage gaps for both services
- Status: Resolved
- Description: TranslationService tests (3 tests) cover only `on_translation_final`, `get_history` (happy path), and `delete_history`. Not tested: language detection edge cases (CR-001), `translate_text`, `transcribe_audio`, `process_interim`, `reset_interim`, `start_utterance`, `preload`, `cleanup_expired`, `ready` property, `get_history` with `seat_id` filter, no-speech_module (degraded) paths. DashboardService tests (1 test) cover only the happy path with all blocks present. Not tested: non-existent meeting_id (null meeting block), active vote with data, pending service calls with data, assigned speaker seat, empty seats list.
- Decision Reason: 

### CR-007: N+1 query pattern in DashboardService._resolve_attendee_name
- Status: Resolved
- Description: `dashboard_service.py:51` calls `self._resolve_attendee_name(s.attendee_id)` inside a list comprehension over all seats. Each call hits `attendee_repo.get_by_id()` (line 21), issuing one SQL query per seat. With 10 seats this is 10 queries; the `AttendeeRepository` already has `list_by_meeting(meeting_id)` (line 20-23 of attendee_repository.py) that returns all attendees for a meeting in a single query. `get_dashboard` receives `meeting_id` and should fetch all attendees once, build a dict keyed on attendee_id, then do O(1) lookups instead of N queries.
- Decision Reason: 

### CR-008: Unsafe getattr fallback default in TranslationService.ready
- Status: Resolved
- Description: `translation_service.py:21` uses `getattr(self.mt, 'ready', True)` — the third argument defaults to `True`. This means if `self.mt` is a non-None object that lacks a `ready` attribute (e.g., a misconfigured or incomplete mock, or an MT engine class that renamed the property), it is silently treated as ready. The conservative default should be `False`: if the mt_engine does not expose `ready`, the service should report `ready=False` rather than silently proceeding. Alternatively, check `hasattr(self.mt, 'ready')` explicitly and raise a clear error for a missing attribute.
- Decision Reason: 
