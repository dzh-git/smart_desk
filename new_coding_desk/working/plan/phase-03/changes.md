# Phase 03 Changes

## Modified Files

### backend/services/meeting_service.py
- Added imports: `SeatState`, `Vote`, `VoteClosedEvent`
- Modified `end_meeting()`:
  - Reset all `seat_states` to `vacant` with `attendee_id=None`
  - Clear attendee `seat_id` and set `checked_in=false` for meeting's attendees
  - Auto-close open vote (publish `vote_closed` event)
  - Speaker seat deliberately preserved (no change)
  - Publish `meeting_ended` event

### backend/services/seat_service.py
- Added imports: `Attendee`, `Meeting`, `AttendeeRepository`
- Added `AttendeeRepository` to `__init__`
- Added `_active_meeting()` helper
- Modified `check_in()`:
  - Validate attendee exists (`ATTENDEE_NOT_FOUND`)
  - Validate attendee belongs to active meeting (`ATTENDEE_NOT_IN_ACTIVE_MEETING`)
  - Validate attendee not already bound to another seat (`ATTENDEE_ALREADY_CHECKED_IN`)
  - Validate seat not bound to a different attendee (`SEAT_ALREADY_BOUND`)
  - On success: update both `seat` (status, attendee_id) and `attendee` (seat_id, checked_in)
  - Auto-inject active meeting ID into `check_in` event if not explicitly provided

### backend/api/seats.py
- Added `MeetingService` import and `_active_meeting_id()` helper
- Modified `check_in()`: auto-injects active meeting ID
- Modified `set_speaker_seat()`: auto-injects active meeting ID
- Modified `clear_speaker_seat()`: auto-injects active meeting ID

### backend/main.py
- Added `dev` router import and `seed_demo_data` import
- Added `seed_demo_data(db)` call in lifespan after `SeatRepository.init_seats`
- Added `app.include_router(dev.router)`

### docs/API_SPEC.md
- Added §15 Development-Only Endpoints (dev API table, env vars)
- Added §16 Frontend Rules (renumbered)
- Added 4 new error codes: `ATTENDEE_NOT_IN_ACTIVE_MEETING`, `ATTENDEE_ALREADY_CHECKED_IN`, `SEAT_ALREADY_BOUND`, `MEETING_NOT_ACTIVE`

### tests/test_meeting_service.py
- Added imports: `SeatService`, `SeatRepository`, `SeatState`, `Vote`, `SpeakerSeat`
- Added `TestEndMeetingExtended` class with 8 tests covering:
  - Seat reset to vacant after meeting end
  - Attendee unbinding after meeting end
  - Open vote auto-close on meeting end
  - Speaker seat preservation on meeting end
  - Meeting ended event publishing
  - No vote_closed when no open vote
  - Service calls preserved after meeting end

### tests/test_seat_service.py
- Rewritten check-in tests to use `_active_meeting_with_attendee` helper
- Added validation tests: attendee not found, no active meeting, attendee already bound
- Updated lifecycle tests to create meetings/attendees

## New Files

### backend/api/dev.py
- `POST /api/dev/seats/{seat_id}/occupy` — dev seat occupy endpoint
- `POST /api/dev/seats/{seat_id}/vacate` — dev seat vacate endpoint
- Controlled by `ENABLE_DEMO_SEAT_API` env var (default `false` → 404)
- Both return `ApiResponse<SeatState>` and route through `SeatService`

### backend/seed_demo.py
- `seed_demo_data(db)` function for demo data
- Controlled by `ENABLE_DEMO_SEED` env var (default `false`)
- Idempotent: only seeds when no meetings exist
- Creates: 1 active meeting, 5 agendas, 8 attendees, 10 seat states (mixed), speaker seat, 1 open vote, 1 service call, 2 translation records

### tests/test_dev_api.py
- 19 tests covering:
  - Dev API disabled (404)
  - Dev API enabled: occupy, vacate, error cases, list verification
  - Demo seed disabled: no data
  - Demo seed enabled: all data types, idempotent, existing data preservation
