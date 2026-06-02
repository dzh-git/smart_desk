# Implement Review Results: Task-000

## Spec Review Issues

## Code Review Issues

### CR-001: Test isolation not guaranteed — no database reset between tests
- Status: Resolved
- Description: All tests share a single FastAPI `app` instance backed by a persistent SQLite file (`smart_desk.db`, per `database.py` line 5-6). The `client` fixture is function-scoped but the underlying app state and database persist across tests. If `test_create_and_start_meeting` runs first and leaves an active meeting, `test_seat_lifecycle` and `test_vote_lifecycle` will fail at `POST /api/meetings` because ACTIVE_MEETING_EXISTS would block creation. There is no `db.rollback()`, in-memory test DB, or fixture-based teardown. Tests are order-dependent.
- Decision Reason:

### CR-002: `test_create_and_start_meeting` line 43-44 asserts 400 against a pending (not active) meeting
- Status: Resolved
- Description: The test creates Meeting 1 (status=pending), then immediately tries to create Meeting 2 and asserts `resp2.status_code == 400`. Per `docs/API_SPEC.md` the only create-time rejection is `ACTIVE_MEETING_EXISTS`, and per `docs/system_architecture.md` section 5.5 the check is "无其他 active 会议" when *starting*, not when creating. Meeting 1 is pending (not active), so the spec-compliant behavior is 201 Created, not 400. The inline comment on line 44 even states `# ACTIVE_MEETING_EXISTS not yet triggered since not started`, acknowledging the meeting is not active. This assertion would fail against a correctly implemented spec-compliant backend. The 400 rejection test should occur AFTER starting the first meeting (i.e., after line 49), not before.
- Decision Reason:

### CR-003: `test_create_and_start_meeting` creates an active meeting and never terminates it
- Status: Resolved
- Description: The test creates and starts a meeting (lines 32-49) but never calls the `/end` endpoint. Combined with CR-001, this leaves mutable state (an active meeting) that poisons subsequent tests that need to create their own meetings. All lifecycle tests that create+start meetings should clean up by ending the meeting.
- Decision Reason:

### CR-004: `test_translation_endpoints` line 218 assertion is too weak
- Status: Resolved
- Description: `assert "ready" in resp.json()["data"]` only validates key presence in the preload status response, not its type or value. The `ready` field is a boolean (`translation.py` line 68: `speech.ready`). The assertion passes if `ready` is `False`, `None`, or any other value, as long as the key exists. Should assert `resp.json()["data"]["ready"] is True` or at minimum check `isinstance(..., bool)` to catch misconfigured preload states.
- Decision Reason:

### CR-005: `test_unified_response_format` covers only 3 of 20+ endpoints, no error-response validation
- Status: Resolved
- Description: The test (lines 225-237) only validates 3 GET endpoints (`/api/meetings/active`, `/api/seats`, `/api/seats/speaker`). It does not test any POST endpoints, does not test error responses (which must include `error_code` field per `docs/API_SPEC.md` sections 1 and 11), and does not validate `data` is non-null on success or `data` is null on failure. The docstring claims "All endpoints return..." but coverage is minimal. At minimum, the test should sample one error path (e.g., GET `/api/meetings/99999` expecting 404 with `error_code: "MEETING_NOT_FOUND"`) and one POST success path to verify the format is consistent across HTTP methods.
- Decision Reason:

### CR-006: reset_state fixture silently swallows all exceptions — makes test pollution invisible
- Status: Resolved
- Description: The `reset_state` fixture (test_integration.py lines 28-40) catches `except Exception: pass` unconditionally. In the red phase this is benign because endpoints don't exist. But once `/api/meetings/active` and `/api/meetings/{id}/end` are implemented, ANY bug in the reset logic (response format mismatch, unexpected status code, DB issues) will be silently swallowed. The fixture would fail to end an active meeting, leaving it to poison subsequent tests with no warning. Fix: narrow the catch to only the specific exceptions that indicate "endpoint not yet implemented" (e.g., HTTPError from TestClient when route is missing), or log a warning on unexpected failures. The bare `except Exception: pass` at line 38-39 should be replaced with targeted exception handling.
- Decision Reason: Replaced `except Exception: pass` with `except (ValueError, KeyError, TypeError): pass` — only catches JSON decode failures and missing key errors expected during red phase, while real bugs (AttributeError, OSError, etc.) will propagate and fail visibly.

### CR-007: test_unified_response_format success path does not assert `success is True`
- Status: Resolved
- Description: Lines 258-263 check that `success`, `message`, `data` keys exist in the POST `/api/meetings` response and that `data is not None`. The error path test (lines 270-278) correctly asserts `success is False`. However, the success path only checks key presence — it never asserts `assert data["success"] is True`. If the endpoint returns `{"success": false, "message": "some error", "data": {"id": 1, ...}}`, the test would pass incorrectly. Add `assert data["success"] is True` after the key-presence check to match the rigor of the error path validation.
- Decision Reason: Added `assert data["success"] is True` immediately after the key-presence check on the POST success path.

### CR-008: test_end_meeting_cleans_up does not verify seat count — allows vacuous pass on empty response
- Status: Resolved
- Description: Lines 208-210 iterate over seats and assert each is `"vacant"`, but never assert `len(resp.json()["data"]) == 10` (the system has exactly 10 seats per DATABASE_SCHEMA.md section 6: `seat_id 固定为 1~10，系统初始化时自动创建10条记录`). If `GET /api/seats` returns an empty list (e.g., `seat_states` table not initialized), the for-loop never executes and the test passes vacuously. Add `assert len(resp.json()["data"]) == 10` before the loop at line 208 to catch missing seat initialization.
- Decision Reason: Added `assert len(seats_data) == 10, f"Expected 10 seats, got {len(seats_data)}"` before the per-seat vacancy check.

### CR-009: test_end_meeting_cleans_up missing seat occupation simulation before checkin
- Status: Resolved
- Description: `test_end_meeting_cleans_up` at line 195 calls `POST /api/seats/3/checkin` without first setting seat 3 to `occupied_unchecked` via the debug/simulate endpoint. Compare with `test_seat_lifecycle` at line 98 which correctly calls `client.post("/api/debug/simulate/3?action=occupied")` before checkin at line 101. Per API_SPEC.md section 7, the checkin rule is "seat status = occupied_unchecked" -- the seat must already be in the occupied_unchecked state before checkin is allowed. A spec-compliant implementation of the checkin endpoint will reject the call at line 195 (e.g., 400 SEAT_NOT_OCCUPIED or 409 INVALID_SEAT_STATE), causing `test_end_meeting_cleans_up` to fail in the green phase. The fix is to add `client.post("/api/debug/simulate/3?action=occupied")` before the checkin call at line 195, consistent with the pattern used in `test_seat_lifecycle`.
- Decision Reason: Added `client.post("/api/debug/simulate/3?action=occupied")` before the checkin call at line 195, consistent with `test_seat_lifecycle` pattern for seat occupation simulation per API_SPEC.md section 7.

### CR-010: Test exercises undocumented query parameters on vote/service-call/dashboard endpoints
- Status: Don't Fix
- Description: The following endpoints receive a `meeting_id` query parameter in the tests but the API_SPEC.md (Frozen v1.1) does not document these query parameters: `GET /api/votes/active?meeting_id={mid}` (line 137), `POST /api/service-calls?meeting_id={mid}` (line 163), `GET /api/service-calls?meeting_id={mid}` (line 176), `GET /api/dashboard?meeting_id={mid}` (line 227). API_SPEC.md section 8 shows `GET /api/votes/active` without query params; section 9 shows `POST /api/service-calls` and `GET /api/service-calls` without query params; section 3 shows `GET /api/dashboard` without query params. A spec-compliant implementation would not parse these query parameters. In the green phase, if the implementation follows the spec literally, these tests will fail because the endpoints ignore or reject unknown query params. The spec should be updated to document these parameters, or the tests should be aligned with the existing spec.
- Decision Reason: Tests exercise target-architecture endpoints with meeting_id query params. In the new EventBus-driven architecture, vote/service-call/dashboard endpoints need meeting_id scoping (multiple meetings may exist, active state is meeting-scoped). This is a spec update needed as part of the migration, not a test defect. The frozen API_SPEC.md v1.1 describes the legacy callback architecture; the EventBus migration will update it. Keeping the tests as-is ensures the new implementation correctly scopes by meeting_id.

### CR-011: Test exercises undocumented /api/translations/preload/status endpoint
- Status: Don't Fix
- Description: Line 239 calls `GET /api/translations/preload/status`. API_SPEC.md section 10 only documents `POST /api/translations` and `GET /api/translations`. The `preload/status` sub-path is entirely new and undocumented. The implementation may not include this endpoint if it only follows the documented spec. Either the endpoint should be added to API_SPEC.md or the test should be updated to test only documented endpoints.
- Decision Reason: The /api/translations/preload/status endpoint is needed in the new architecture for async model preload status monitoring. The existing codebase already has a /api/translate/preload/status endpoint (translation.py line 66-68) — the test path differs (/api/translations/ vs /api/translate/) because the new architecture moves translation under a unified /api/translations prefix per the migration design. This is a spec documentation gap for the migration, not a test defect. The frozen API_SPEC.md v1.1 needs updating as part of the EventBus migration. Keeping the test as-is validates the new unified translation prefix.

### CR-012: reset_state fixture does not validate end-meeting response status
- Status: Resolved
- Description: The `reset_state` autouse fixture (line 38) calls `client.post(f"/api/meetings/{meeting['id']}/end")` without checking the response status code. If the end endpoint returns a non-200 status (e.g., 400 MEETING_ALREADY_FINISHED, 404 MEETING_NOT_FOUND, 500 INTERNAL_ERROR), the fixture silently continues as if cleanup succeeded. The active meeting persists and the next test inherits poisoned state. In the green phase, this would cause confusing cascading failures unrelated to the test logic. The fixture should at minimum check `resp.status_code == 200` and log or raise a warning on failure, so test isolation failures are visible and debuggable rather than silently ignored.
- Decision Reason: Added response status validation — the fixture now captures `end_resp` and uses `warnings.warn()` when `end_resp.status_code != 200`, making test isolation failures visible. Also imported `warnings` at the point of use within the fixture scope to keep imports minimal.

### CR-013: Setup response assertions missing — silent cascading failures in green phase
- Status: Resolved
- Description: Multiple test methods call critical setup endpoints (start meeting, simulate seat occupancy, set speaker seat) without checking the response status code. If any of these setup operations fail in the green phase, subsequent calls dependent on that state will fail with confusing, unrelated error messages — the root cause (failed setup) is invisible. Affected lines: test_seat_lifecycle:89 (`POST /api/meetings/{mid}/start` — no assertion), test_vote_lifecycle:128 (same), test_service_call_lifecycle:166 (same), test_end_meeting_cleans_up:194 (same), test_end_meeting_cleans_up:201 (`POST /api/debug/simulate/3?action=occupied` — no assertion), test_end_meeting_cleans_up:203 (`POST /api/seats/speaker` — no assertion), test_translation_endpoints:242 (`POST /api/meetings/{mid}/start` — no assertion). These should assert `resp.status_code == 200` so setup failures surface immediately with clear error messages rather than cascading into unrelated failures. See contrast with test_create_and_start_meeting:73-75 where the start response IS properly asserted.
- Decision Reason: Added `assert <var>.status_code == 200` to all 7 unchecked setup calls: start meeting (4 calls across seat_lifecycle, vote_lifecycle, service_call_lifecycle, translation_endpoints), debug simulate (1 call), checkin (1 call), set speaker (1 call). Each now captures response in a named variable and asserts 200, surfacing setup failures immediately.

### CR-014: debug/simulate call at line 105 still missing response assertion — missed in CR-013 fix batch
- Status: Resolved
- Description: `test_seat_lifecycle` line 105 calls `client.post("/api/debug/simulate/3?action=occupied")` without capturing the response or asserting status code. This is the same pattern that CR-013 fixed for `test_end_meeting_cleans_up` line 205 (where `sim_resp` is captured and asserted). In the green phase, if the debug/simulate endpoint fails or returns a non-200 status, the subsequent checkin at line 108 will fail with a misleading error (e.g., SEAT_NOT_OCCUPIED) rather than revealing the root cause (simulate setup failed). Fix: capture the response and assert status 200, matching the pattern at lines 205-206.
- Decision Reason: Captured `sim_resp = client.post(...)` and added `assert sim_resp.status_code == 200`, matching the pattern at lines 205-206 used in `test_end_meeting_cleans_up`.
