# Task 024: Black-Box Integration Test — Run and Fix

## Project Overview

- **Goal:** Migrate SmartDesk from direct callback architecture to EventBus-driven decoupled architecture
- **Architecture:** Router → Service → Repository → SQLite, with in-process EventBus for decoupling
- **Tech Stack:** Python 3.11+, FastAPI, SQLAlchemy 2.0, SQLite, WebSocket

## Task Objective

Run the black-box integration tests written in Task 000 (RED phase). Those tests were written before any implementation and should now be PASSING after all infrastructure has been built. Fix any bugs discovered during test execution to bring the full system to green. Do NOT rewrite the test file — it already exists from Task 000.

This is Task 24 of 26.

---

**Files:**
- Verify: `D:\learning\smart_desktop\smart-desk\tests\test_integration.py` (created in Task 000, DO NOT REWRITE)
- Modify: (may touch any backend file to fix bugs found by integration tests)

- [ ] **Step 1: Run integration tests — verify they now PASS (Green Phase)**

```bash
cd D:\learning\smart_desktop\smart-desk && pytest tests/test_integration.py -v --tb=long
```

Expected: All tests from Task 000 now PASS. If they don't pass, go to Step 2.

- [ ] **Step 2: Fix any failures found**

For each failing test:
1. Identify if it's a test issue (wrong expected value in Task 000 test) or implementation issue (missing logic in tasks 001-023)
2. If implementation issue: fix the root cause in the appropriate backend file following TDD
3. If test issue: update the test assertion to match the correct spec behavior (document the reason)
4. Re-run until all pass

Common issues to check:
- MeetingService.create() must reject when active meeting exists (PR-001 resolved in tasks 008+012)
- VoteService.end() must publish individual vote_closed events (PR-004 resolved in task 008)
- Schemas must be fully defined (PR-005 resolved in task 002)
- Audio auto-resampling wired in transcribe_array (PR-006 resolved in task 015)
- meeting_started triggers preload (PR-008 resolved in tasks 015+021)
- checkin_prompt with 3s delay fires (PR-003 resolved in task 008)

Expected after fixes: All integration tests PASS

- [ ] **Step 3: Run the complete test suite**

```bash
cd D:\learning\smart_desktop\smart-desk && pytest tests/ -v --tb=short
```
Expected: All tests pass (with appropriate skips for slow tests requiring model download)
