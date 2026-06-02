# Task 007: Rename business_logic.py to seat_state_machine.py

## Project Overview

- **Goal:** Migrate SmartDesk from direct callback architecture to EventBus-driven decoupled architecture
- **Architecture:** Router → Service → Repository → SQLite, with in-process EventBus for decoupling
- **Tech Stack:** Python 3.11+, FastAPI, SQLAlchemy 2.0, SQLite, WebSocket

## Task Objective

Rename `business_logic.py` to `seat_state_machine.py` and move it to `backend/services/` (already there). Update all imports. This is migration item C5. The state machine remains pure (zero I/O), exactly as it is — only the file name changes.

This is Task 7 of 26.

---

**Files:**
- Create: `D:\learning\smart_desktop\smart-desk\backend\services\seat_state_machine.py`
- Modify: `D:\learning\smart_desktop\smart-desk\backend\services\desk_coordinator.py`
- Delete: `D:\learning\smart_desktop\smart-desk\backend\services\business_logic.py`

- [ ] **Step 1: Create the renamed file (copy contents)**

Copy all contents from `backend/services/business_logic.py` to `backend/services/seat_state_machine.py`.
No logic changes — only the file name changes.

- [ ] **Step 2: Update import in desk_coordinator.py**

In `D:\learning\smart_desktop\smart-desk\backend\services\desk_coordinator.py`, change:
```python
from backend.services.business_logic import DeskStateMachine
```
to:
```python
from backend.services.seat_state_machine import DeskStateMachine
```

- [ ] **Step 3: Verify no other imports reference the old file**

Run: `cd D:\learning\smart_desktop\smart-desk && grep -r "business_logic" backend/`
Expected: Only `business_logic.py` itself shows up (if it still exists)

- [ ] **Step 4: Verify the app starts**

Run backend start script or simple import test:
```bash
cd D:\learning\smart_desktop\smart-desk && python -c "from backend.services.seat_state_machine import DeskStateMachine; sm = DeskStateMachine(); print(sm.all_seats_state[0])"
```
Expected: Output showing seat state dict

- [ ] **Step 5: Delete the old file**

```bash
rm D:\learning\smart_desktop\smart-desk\backend\services\business_logic.py
```

- [ ] **Step 6: Verify again after deletion**

```bash
cd D:\learning\smart_desktop\smart-desk && python -c "from backend.services.desk_coordinator import desk; print('OK')"
```
Expected: OK (no import errors)
