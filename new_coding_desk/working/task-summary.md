# Task Summary: SmartDesk v2.0 Architecture Migration

**Plan:** 25 tasks (task-001 through task-025)
**Spec:** working/spec.md
**Branch:** replace-speech-module

---

## Task Manifest

| Task | Name | Files Created | Files Modified | Status |
|------|------|--------------|----------------|--------|
| 001 | EventBus Implementation | 1 | 0 | pending |
| 002 | ORM Models (SeatState, SpeakerSeat, TranslationRecord) | 0 | 3 | pending |
| 003 | MeetingRepository + AttendeeRepository | 3 | 0 | pending |
| 004 | SeatRepository | 1 | 0 | pending |
| 005 | VoteRepository | 1 | 0 | pending |
| 006 | ServiceCallRepository + TranslationRepository | 2 | 1 | pending |
| 007 | Rename business_logic.py → seat_state_machine.py | 1 | 1 | pending |
| 008 | MeetingService + SeatService | 2 | 0 | pending |
| 009 | VoteService + ServiceCallService | 2 | 0 | pending |
| 010 | TranslationService + DashboardService | 2 | 0 | pending |
| 011 | WebSocket EventBridge | 1 | 1 | pending |
| 012 | Refactor Meetings Router + New Attendees Router | 1 | 1 | pending |
| 013 | Refactor checkin.py → seats.py | 1 | 1 | pending |
| 014 | Refactor Votes + Service Calls Routers | 0 | 2 | pending |
| 015 | Refactor Translation Router + Dashboard Router | 1 | 1 | pending |
| 016 | Frontend API Paths Update | 0 | 1 | pending |
| 017 | Frontend WS Event Names Update | 0 | 5 | pending |
| 018 | ConnectionLostOverlay.vue | 1 | 2 | pending |
| 019 | Timeout + Logging + Cleanup | 1 | 1 | pending |
| 020 | Speaker Switch Recording Interrupt | 0 | 3 | pending |
| 021 | Main.py Cleanup | 0 | 3 | pending |
| 022 | Remove speech_history.db | 0 | 3 | pending |
| 023 | Multi-Admin + Hardware Event Guard | 0 | 3 | pending |
| 024 | Black-Box Integration Tests | 1 | 0 | pending |
| 025 | Final Cleanup | 0 | 4 | pending |

**Total:** ~23 new files, ~40 modified files

---

## Migration Items Covered

| Migration Item | Covered By |
|---------------|------------|
| A1: Repository layer | Tasks 003-006 |
| A2: EventBus | Task 001 |
| A3: TranslationRecord unified SQLite | Tasks 002, 022 |
| A4: Speaker Seat DB persistence | Tasks 002, 004 |
| B1: API path renaming | Tasks 012-016 |
| B2: Event name renaming | Tasks 011, 017 |
| B3: Check-in pre-assignment | Tasks 008, 013 |
| B4: Auto preload on meeting_started | Tasks 008, 015 |
| B5: Multi-admin support | Task 023 |
| C1: Connection Lost overlay | Task 018 |
| C2: Service call timeout | Task 019 |
| C3: Translation cleanup | Task 019 |
| C4: File logging | Task 019 |
| C5: Rename business_logic.py | Task 007 |
| C6: Re-seat auto-binding | Task 008 |
| C7: Auto-close votes on meeting_end | Task 008 |
| C8: Interrupt recording on switch | Task 020 |
| C9: Vote statistics for seats | Task 014, 023 |

---

## Execution Order

Tasks must be executed in numeric order (001 → 025). Dependencies:

- Tasks 003-006 depend on 001-002 (EventBus + Models)
- Tasks 008-010 depend on 003-007 (Repositories)
- Tasks 011 depends on 001, 008-010 (EventBus + Services)
- Tasks 012-015 depend on 008-011 (Services + Bridge)
- Tasks 016-018 depend on 012-015 (Router refactoring)
- Tasks 019-023 depend on 012-018 (Stable APIs)
- Task 024 depends on all previous
- Task 025 is final cleanup
