# Implement Review Results: Task-013

## Spec Review Issues

## Code Review Issues

### CR-001: Missing attendee_id in WebSocket service_call handler
- Status: Resolved
- Description: In `main.py` lines 204-215, the replacement WebSocket `service_call` handler calls `ServiceCallService.create(meeting_id, seat, svc_type)` which does NOT populate `attendee_id`. The old `persist_service_call` (deleted from the execution path) resolved the attendee via seat lookup and set `attendee_id` on the ServiceCall record. Now all WebSocket-initiated service calls have `attendee_id = None`, losing the ability to track which attendee requested which service. Compare `persist_service_call` in `service_calls.py` lines 14-44 (still defined but no longer called from the WebSocket handler) which does `attendee_id=attendee.id if attendee else None`.
- Decision Reason:

### CR-002: clear_speaker_seat silently succeeds when no active meeting
- Status: Resolved
- Description: In `seats.py` lines 83-91, `DELETE /api/seats/speaker` returns `{"success": True, "data": {"seat_id": None}}` even when no active meeting exists (line 89: `if active:` — when false, falls through to return OK). Contrast with `POST /api/seats/speaker` (lines 73-74) which raises `HTTPException(400, "NO_ACTIVE_MEETING")` in the same situation. Callers cannot distinguish between "speaker seat was successfully cleared" and "nothing happened because no meeting is active". This asymmetry also means a client could think they cleared the speaker seat for an upcoming meeting when nothing was actually done.
- Decision Reason:

### CR-003: VoteService.cast() exceptions propagate uncaught in WebSocket handler
- Status: Resolved
- Description: In `main.py` lines 198-199, `vs.cast(meeting_id, vid, aid, opt)` can raise `VoteNotFoundError`, `VoteClosedError`, or `InvalidVoteOptionError` (all subclasses of `VoteError`, defined in `vote_service.py`). None are caught. These propagate out of the `async for` loop in `ws_endpoint`, causing the WebSocket connection to close. The old `persist_vote_cast` returned `None` on failure (invalid vote, closed vote, invalid option) and kept the connection alive. A single bad vote cast now forcibly disconnects the client, which is a robustness regression — especially since vote options come from user input which may be stale or incorrect.
- Decision Reason:

### CR-004: Duplicate AttendeeRepository creation in checkin endpoint
- Status: Resolved
- Description: In `seats.py` lines 43-53, the `checkin()` function creates an `AttendeeRepository(db)` at line 46 for pre-checks, while `_get_service(db)` at line 44 already creates another `AttendeeRepository(db)` inside the `SeatService` constructor. Plus `SeatService.checkin()` (seat_service.py line 68) calls `self.attendee_repo.get_by_id(attendee_id)` again. This results in three separate attendee lookups for a single checkin request. The pre-check at lines 46-51 duplicates the service's own validations (seat_service.py lines 62-77). The extra repository instance is unnecessary since `svc.attendee_repo` could be used directly for the seat-assignment check.
- Decision Reason:
