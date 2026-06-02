# Changes: Task-007

## Files
- [new] D:\learning\smart_desktop\smart-desk\backend\services\seat_state_machine.py
- [mod] D:\learning\smart_desktop\smart-desk\backend\services\desk_coordinator.py
- [del] D:\learning\smart_desktop\smart-desk\backend\services\business_logic.py

## Summary
Renamed `business_logic.py` to `seat_state_machine.py`. Copied all contents with zero logic changes. Updated the single import in `desk_coordinator.py` from `backend.services.business_logic` to `backend.services.seat_state_machine`. Deleted the old file. Verified no other imports reference the old name and the app starts cleanly.

### CR-001 Fix
Updated module docstring from `"""Business logic — pure state machine for smart desk."""` to `"""Seat state machine — pure state machine for smart desk."""` to match the new module name. This is a documentation metadata update, not a logic change.
