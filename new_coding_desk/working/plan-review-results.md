# Plan Review Results

## Issues

### PR-001: Missing ACTIVE_MEETING_EXISTS check on meeting creation
- Status: Resolved
- Description: Spec section 4.5 states that POST /api/meetings must return 400 + ACTIVE_MEETING_EXISTS when an active meeting already exists. Task 012 Step 2's create_meeting endpoint calls MeetingService.create() directly with no such check. Task 008's MeetingService.create() also has no guard. An implementer following the plan would silently create multiple pending meetings even when one is active, violating the spec constraint.
- Decision Reason:

### PR-002: Black-box integration test TDD violation — no pre-implementation failing-test task
- Status: Resolved
- Description: The black-box testing skill requires black-box tests to be written in a separate task BEFORE implementation tasks, so they can be observed failing (red phase). Task 024 writes AND runs the black-box integration tests in a single task at position 24, after all implementation is done. This violates the TDD pattern "Task 1: write/update black-box tests for a feature and see them failed" before any code tasks. The plan needs a separate pre-implementation task that writes the black-box tests (which will fail initially) placed before the implementation tasks begin (before Task 001), and Task 024 should only run/verify those tests and do bug fixes.
- Decision Reason:

### PR-003: checkin_prompt with 3-second delay not wired up
- Status: Resolved
- Description: Spec section 9.1 describes a flow where after seat_occupied, a 3-second timer fires `checkin_prompt` sent to the specific seat tablet. Task 008's SeatService has a `schedule_checkin_prompt()` method but nobody calls it — neither `on_seat_occupied()` nor the serial handler in Task 021 triggers a delayed `checkin_prompt` publish. The `checkin_prompt` event is registered in the WS bridge (Task 011) but will never fire. The CheckInModal popup behavior specified in sections 9.1 and 10.3 would not work.
- Decision Reason:

### PR-004: Missing per-vote vote_closed events on meeting_ended auto-close
- Status: Resolved
- Description: Spec section 8.3 and 4.5 require that meeting_ended triggers auto-close of all open votes AND broadcasts individual vote_closed events for each. Task 008's MeetingService.end() calls `vote_repo.close_all_open()` which does a bulk SQL UPDATE without iterating through votes to publish vote_closed events. Only a single `meeting_ended` event is published. The frontend Wiring (spec 10.3) handles `vote_closed` separately (closes VotingPanel, resets LEDs). Without individual vote_closed events, VotingPanel components would not properly close when a meeting ends.
- Decision Reason:

### PR-005: Pydantic schemas referenced in router tasks but never defined
- Status: Resolved
- Description: Tasks 012-015 import and use schemas like MeetingCreate, MeetingUpdate, MeetingOut, AttendeeCreate, AttendeeOut, AgendaCreate, AgendaOut, VoteCreateRequest, VoteCastRequest, ServiceCallCreateRequest, TextTranslateRequest — but the only schemas added anywhere in the plan are TranslationRecordCreate, TranslationRecordOut, SeatStateOut, SpeakerSeatOut, SpeakerSeatSet in Task 002 Step 15. No task adds the other schemas. An implementer would hit ImportError and be stuck at the router implementation steps.
- Decision Reason:

### PR-006: Audio auto-resampling requirement not addressed
- Status: Resolved
- Description: Spec sections 4.11 and 12.1 state the backend must auto-resample unsupported sample rates to 16kHz (marked [待实现]). The SpeechModule facade's `transcribe_array(audio, sr)` method takes sample rate as a parameter, implying resampling support. However, no task in the plan covers updating `speech_module/audio_utils.py` or the SpeechModule facade to implement automatic resampling. This is a spec requirement with no task coverage.
- Decision Reason:

### PR-007: Task count metadata is wrong in every task header
- Status: Resolved
- Description: Every task file claims "This is Task N of 30" (e.g., Task 001 says "This is Task 1 of 30", Task 025 says "This is Task 25 of 30"). There are only 25 tasks in the plan directory, not 30. While this does not block implementation, it indicates the plan was truncated or the numbering was never corrected, and implementers may look for non-existent tasks 026-030.
- Decision Reason:

### PR-008: meeting_started does not trigger automatic model preload
- Status: Resolved
- Description: Spec sections 12.4 and Q22 require model preload to be triggered automatically by the `meeting_started` event (not manual `/preload` API call). Task 015 Step 3 attempts to wire this subscription with a `from backend.services.translation_service import _preload_handler` import, but `_preload_handler` does not exist in `TranslationService` — the class only has a `preload()` method. Furthermore, Task 021's final `main.py` lifespan function does not include any subscription of a preload handler to `meeting_started`. The Task 021 rewritten main.py calls `register_ws_bridge()` but sets up no preload trigger. An implementer following the plan would either: (a) leave preload as manual-only (violating Q22), or (b) hit ImportError on the non-existent `_preload_handler`, or (c) be forced to invent the wiring themselves without guidance. The `SpeechModule.preload()` method will never be called by the meeting_started flow.
- Decision Reason:

