# Service Call Module — Implementation Report

**Phase:** 4.4
**Date:** 2026-06-01
**Status:** Complete & Smoke-Tested

---

## 1. Files Created (3)

| File | Lines | Purpose |
|---|---|---|
| `backend/schemas/service_call.py` | 35 | Pydantic DTOs: `ServiceCallCreate`, `ServiceCallResponse` |
| `backend/repositories/service_call_repository.py` | 63 | Extends `BaseRepository[ServiceCall]`, custom queries |
| `backend/services/service_call_service.py` | 148 | Business logic, state machine, event publishing |

## 2. Files Modified (4)

| File | Change |
|---|---|
| `backend/api/service_calls.py` | Replaced stub with 5 endpoints (115 lines) |
| `backend/repositories/__init__.py` | Added `ServiceCallRepository` export |
| `backend/services/__init__.py` | Added `ServiceCallService` export |
| `backend/events/__init__.py` | Added 3 event class exports |

## 3. Endpoints (5)

| Method | Route | Status | Events |
|---|---|---|---|
| POST | `/api/service-calls` | 201 | `service_call_created` {call_id, seat_id, service_type} |
| GET | `/api/service-calls?meeting_id=N` | 200 | — |
| GET | `/api/service-calls/current?meeting_id=N&seat_id=S` | 200 | — |
| POST | `/api/service-calls/{call_id}/resolve` | 200 | `service_call_resolved` {call_id} |
| POST | `/api/service-calls/{call_id}/cancel` | 200 | `service_call_cancelled` {call_id} |

## 4. Business Rules

| Rule | Description | Enforcement | Verified |
|---|---|---|---|
| C1 | pending → resolved | `resolve_call()` requires status=="pending" | ✅ |
| C2 | pending → cancelled | `cancel_call()` requires status=="pending" | ✅ |
| C3 | resolved不可取消 | Covered by C2: non-pending rejected with SERVICE_CALL_NOT_PENDING | ✅ |
| C4 | cancelled不可恢复 | No restore method exists — terminal state | ✅ |
| — | Same seat 1 pending | `create_call()` checks `get_pending_by_seat()` → 409 | ✅ |

## 5. State Machine

```
         create_call()
              │
              ▼
         ┌──────────┐
         │ pending   │
         └─────┬─────┘
          ┌────┴────┐
          ▼         ▼
    ┌─────────┐  ┌──────────┐
    │ resolved │  │ cancelled │
    └─────────┘  └──────────┘
    (terminal)    (terminal)
```

## 6. Error Codes

| Error Code | HTTP | Trigger |
|---|---|---|
| `PENDING_CALL_EXISTS` | 409 | Same seat already has pending call |
| `SERVICE_CALL_NOT_FOUND` | 404 | call_id doesn't exist |
| `SERVICE_CALL_NOT_PENDING` | 400 | resolve/cancel on non-pending call |

## 7. Smoke Test Results (12/12 passed)

| # | Test | Expected | Result |
|---|---|---|---|
| 1 | POST create coffee seat=3 | 201 + created | ✅ |
| 2 | POST same seat again | 409 PENDING_CALL_EXISTS | ✅ |
| 3 | POST different seat | 201 water seat=5 | ✅ |
| 4 | GET list | 2 calls returned | ✅ |
| 5 | GET current seat=3 | coffee call returned | ✅ |
| 6 | GET current seat=99 | null | ✅ |
| 7 | POST resolve call=1 | resolved, resolved_at set | ✅ |
| 8 | POST resolve again | 400 SERVICE_CALL_NOT_PENDING | ✅ |
| 9 | POST cancel on resolved | 400 SERVICE_CALL_NOT_PENDING | ✅ |
| 10 | POST cancel call=2 (pending) | cancelled | ✅ |
| 11 | POST cancel non-existent | 404 SERVICE_CALL_NOT_FOUND | ✅ |
| 12 | GET list (verify statuses) | resolved + cancelled | ✅ |

## 8. Architecture Compliance

- ✅ Router layer: thin — only request parsing, error mapping, response building
- ✅ Service layer: owns all business rules and event publishing
- ✅ Repository layer: no business logic, no EventBus access
- ✅ Typed domain exceptions: `NotFoundError`, `ConflictError`, `ValidationError`
- ✅ Dependency injection via FastAPI `Depends(get_db)`
- ✅ Event publishing only from Service, never from Repository or Router
- ✅ All 3 events already registered in `WebSocketEventHandler.BROADCAST_EVENTS`
