# Changes: Task-000

## Files
- [new] D:\learning\smart_desktop\smart-desk\tests\__init__.py
- [mod] D:\learning\smart_desktop\smart-desk\tests\test_integration.py

## Summary

### Initial (prior iteration)
Created black-box integration test file implementing the full meeting lifecycle through HTTP API endpoints. The tests cover: meeting create/start/end, seat lifecycle (checkin, speaker), vote lifecycle (create/cast/statistics/close), service call lifecycle (create/resolve), translation endpoints, and unified response format validation. All 7 tests FAIL as expected (RED phase of TDD).

### Review fixes — batch 1 (CR-001 to CR-005)
- **CR-001**: Added `reset_state` autouse fixture to end any active meeting before each test, ensuring test isolation
- **CR-002**: Fixed assertion on second meeting creation — expects 201 (success) when first meeting is still pending, not 400 (ACTIVE_MEETING_EXISTS only applies to active meetings per spec)
- **CR-003**: reset_state fixture ensures clean state between tests; test_unified_response_format also cleans up its created meeting
- **CR-004**: Strengthened translation preload status assertion from `assert "ready" in data` to `assert isinstance(data["ready"], bool)`
- **CR-005**: Expanded unified_response_format test to cover POST success path, error response (404 with error_code), and data null validation on errors

### Review fixes — batch 2 (CR-006 to CR-008)
- **CR-006**: Narrowed `reset_state` exception handling from `except Exception` to `except (ValueError, KeyError, TypeError)` — only swallows expected red-phase failures (JSON decode errors, missing keys), while real bugs propagate visibly
- **CR-007**: Added `assert data["success"] is True` on the POST success path in `test_unified_response_format` to match the rigor of the error path validation
- **CR-008**: Added `assert len(seats_data) == 10` before the per-seat vacancy loop in `test_end_meeting_cleans_up` to prevent vacuous pass on empty seat list

### Review fixes — batch 3 (CR-009)
- **CR-009**: Added `client.post("/api/debug/simulate/3?action=occupied")` before checkin in `test_end_meeting_cleans_up` — ensures seat is in `occupied_unchecked` state before checkin per API_SPEC.md section 7, consistent with `test_seat_lifecycle` pattern

### Review fixes — batch 4 (CR-012)
- **CR-012**: Added end-meeting response status validation in `reset_state` fixture — captures `end_resp` and emits `warnings.warn()` when `end_resp.status_code != 200`, making test isolation failures visible and debuggable rather than silently ignored

### Review fixes — batch 5 (CR-013)
- **CR-013**: Added `assert <var>.status_code == 200` to all 7 unchecked setup calls across 5 test methods: start meeting (4 calls in test_seat_lifecycle, test_vote_lifecycle, test_service_call_lifecycle, test_translation_endpoints), debug simulate occupancy (1 call), seat checkin (1 call), set speaker seat (1 call). Each now captures the response in a named variable and asserts status 200, so setup failures surface immediately with clear error messages rather than cascading into unrelated failures during the green phase.

### Review fixes — batch 6 (CR-014)
- **CR-014**: Added response capture and status assertion for the `debug/simulate` call in `test_seat_lifecycle` — the call at line 105 now captures `sim_resp = client.post(...)` and asserts `assert sim_resp.status_code == 200`, matching the pattern already used at lines 205-206 in `test_end_meeting_cleans_up`. This prevents silent setup failures from cascading into misleading test errors during the green phase.

### Pending issues resolved as Don't Fix
- **CR-010**: `meeting_id` query params on vote/service-call/dashboard endpoints — kept as-is; these are target-architecture requirements for meeting-scoped state in the EventBus migration, not test defects
- **CR-011**: `/api/translations/preload/status` endpoint — kept as-is; this is the target-architecture path under the unified `/api/translations` prefix, already implemented in existing codebase as `/api/translate/preload/status`
