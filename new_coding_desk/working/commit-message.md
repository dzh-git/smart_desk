# Commit Message Template

```
feat: SmartDesk v2.0 Target Architecture Migration

Refactor from direct-callback architecture to EventBus-driven Service/Repository pattern.

## Changes

### Foundation (P0)
- Add EventBus (in-process dict dispatch) — `backend/services/event_bus.py`
- Add ORM models: SeatState, SpeakerSeat, TranslationRecord
- Add DB seed data (seat_states 1-10, speaker_seat id=1)
- Implement 6 Repository classes (Meeting, Attendee, Seat, Vote, ServiceCall, Translation)

### Service Layer (P0 + P1)
- Implement 7 Service classes (Meeting, Seat, Vote, ServiceCall, Translation, Dashboard, SeatStateMachine)
- WebSocket EventBridge: maps all 15 EventBus events to WS broadcast
- Rename business_logic.py → seat_state_machine.py (C5)

### API Path Migration (P1)
- `/api/translate/*` → `/api/translations/*`
- `/api/checkin/` → `/api/seats/{id}/checkin`
- `/api/translate/speaker-seat` → `/api/seats/speaker`
- New: `/api/meetings/active`, `/api/meetings/{id}/start`, `/api/meetings/{id}/end`
- New: `/api/dashboard`, `/api/votes/active`, `/api/votes/{id}/statistics`
- Remove anonymous attendee auto-creation (B3)

### Frontend Updates (P1 + P2)
- Update all API paths in `api/index.js`
- Update WebSocket event names: vote_update→vote_updated, translation_result→translation_final, etc.
- Add ConnectionLostOverlay.vue with 3s auto-reconnect (C1)

### Enhancements (P2)
- Service call 5-minute timeout auto-cancel (C2)
- Translation history 180-day retention cleanup (C3)
- File logging to logs/ directory with rotation (C4)
- Re-seat auto-binding on TOF re-occupation (C6)
- Auto-close open votes on meeting_end (C7)
- Speaker seat switch interrupts current recording (C8)
- Vote statistics accessible to Seat tablets (C9)
- Multi-admin tablet support (B5)

### Cleanup
- Remove speech_history.db → unified smart_desk.db (A3)
- Speaker Seat persistent in DB (A4)
- Remove CORS middleware (Nginx same-origin)
- Deprecate desk_coordinator.py

BREAKING CHANGES:
- API paths renamed (see migration guide)
- WebSocket event names changed
- Check-in now requires pre-assigned attendee_id
```
