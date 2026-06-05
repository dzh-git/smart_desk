# SmartDesk API Specification

Version: 1.1

Status: Frozen

---

# 1. Unified Response Format

## Success

```json
{
  "success": true,
  "message": "OK",
  "data": {}
}
```

## Failure

```json
{
  "success": false,
  "message": "Seat already checked in",
  "data": null,
  "error_code": "SEAT_ALREADY_CHECKED_IN"
}
```

---

# 2. HTTP Status Codes

| Status | Meaning        |
| ------ | -------------- |
| 200    | Success        |
| 201    | Created        |
| 400    | Bad Request    |
| 404    | Not Found      |
| 409    | Conflict       |
| 500    | Internal Error |

---

# 3. Dashboard APIs

用于管理员首页初始化。

## Get Dashboard

Endpoint

```http
GET /api/dashboard
```

Caller

```text
Admin Tablet
```

Service

```text
MeetingService
```

Response

```json
{
  "meeting": {},
  "speaker_seat": 3,
  "active_vote": {},
  "pending_service_calls": [],
  "seats": []
}
```

---

# 4. Meeting APIs

## List Meetings

```http
GET /api/meetings
```

Caller

```text
Admin Tablet
```

Service

```text
MeetingService
```

---

## Create Meeting

```http
POST /api/meetings
```

Request

```json
{
  "title": "Board Meeting",
  "description": "Quarterly Review"
}
```

Caller

```text
Admin Tablet
```

Service

```text
MeetingService
```

Status

```text
201 Created
```

---

## Get Meeting

```http
GET /api/meetings/{meeting_id}
```

Caller

```text
Admin Tablet
```

Service

```text
MeetingService
```

---

## Get Active Meeting

```http
GET /api/meetings/active
```

Caller

```text
Admin Tablet
Seat Tablet
```

Service

```text
MeetingService
```

---

## Start Meeting

```http
POST /api/meetings/{meeting_id}/start
```

Caller

```text
Admin Tablet
```

Service

```text
MeetingService
```

Event

```text
meeting_started
```

---

## End Meeting

```http
POST /api/meetings/{meeting_id}/end
```

Caller

```text
Admin Tablet
```

Service

```text
MeetingService
```

Event

```text
meeting_ended
```

---

# 5. Agenda APIs

## List Agendas

```http
GET /api/meetings/{meeting_id}/agendas
```

Caller

```text
Admin Tablet
```

Service

```text
MeetingService
```

---

## Create Agenda

```http
POST /api/meetings/{meeting_id}/agendas
```

Caller

```text
Admin Tablet
```

Service

```text
MeetingService
```

Request

```json
{
  "title": "Financial Report",
  "sort_order": 1
}
```

---

# 6. Attendee APIs

## List Attendees

```http
GET /api/meetings/{meeting_id}/attendees
```

Caller

```text
Admin Tablet
Seat Tablet
```

Service

```text
MeetingService
```

---

## Add Attendee

```http
POST /api/meetings/{meeting_id}/attendees
```

Caller

```text
Admin Tablet
```

Service

```text
MeetingService
```

Request

```json
{
  "name": "John",
  "title": "CEO"
}
```

---

# 7. Seat APIs

Seat Status

```text
vacant
occupied_unchecked
checked_in
```

---

## List Seats

```http
GET /api/seats
```

Caller

```text
Admin Tablet
```

Service

```text
SeatService
```

---

## Confirm Check-in

```http
POST /api/seats/{seat_id}/checkin
```

Caller

```text
Seat Tablet
```

Service

```text
SeatService
```

Request

```json
{
  "attendee_id": 8
}
```

Rules

```text
seat status = occupied_unchecked
```

Event

```text
check_in
```

---

## Get Speaker Seat

```http
GET /api/seats/speaker
```

Caller

```text
Admin Tablet
Seat Tablet
```

Service

```text
SeatService
```

---

## Set Speaker Seat

```http
POST /api/seats/speaker
```

Caller

```text
Admin Tablet
```

Service

```text
SeatService
```

Request

```json
{
  "seat_id": 5
}
```

Rules

```text
仅允许一个Speaker Seat
```

Event

```text
speaker_seat_set
```

---

## Clear Speaker Seat

```http
DELETE /api/seats/speaker
```

Caller

```text
Admin Tablet
```

Service

```text
SeatService
```

Event

```text
speaker_seat_clear
```

---

# 8. Vote APIs

## Get Active Vote

```http
GET /api/votes/active
```

Caller

```text
Seat Tablet
Admin Tablet
```

Service

```text
VoteService
```

---

## Create Vote

```http
POST /api/votes
```

Caller

```text
Admin Tablet
```

Service

```text
VoteService
```

Request

```json
{
  "meeting_id": 1,
  "title": "Approve Budget",
  "options": [
    "Agree",
    "Reject",
    "Abstain"
  ],
  "is_anonymous": true
}
```

Event

```text
vote_started
```

---

## Get Vote

```http
GET /api/votes/{vote_id}
```

Caller

```text
Seat Tablet
Admin Tablet
```

Service

```text
VoteService
```

---

## Submit Vote

```http
POST /api/votes/{vote_id}/submit
```

Caller

```text
Seat Tablet
```

Service

```text
VoteService
```

Request

```json
{
  "attendee_id": 5,
  "option": "Agree"
}
```

Rules

```text
只能投一次
```

Event

```text
vote_updated
```

---

## Get Vote Statistics

```http
GET /api/votes/{vote_id}/statistics
```

Caller

```text
Admin Tablet
```

Service

```text
VoteService
```

Response (匿名):

```json
{
  "vote_id": 1,
  "is_anonymous": true,
  "results": {
    "Agree": 5,
    "Reject": 2
  }
}
```

Response (记名):

```json
{
  "vote_id": 1,
  "is_anonymous": false,
  "results": {
    "Agree": [1, 3, 8],
    "Reject": [5]
  }
}
```

---

## Close Vote

```http
POST /api/votes/{vote_id}/close
```

Caller

```text
Admin Tablet
```

Service

```text
VoteService
```

Event

```text
vote_closed
```

---

# 9. Service Call APIs

## Create Service Call

```http
POST /api/service-calls
```

Caller

```text
Seat Tablet
```

Service

```text
ServiceCallService
```

Request

```json
{
  "seat_id": 4,
  "service_type": "coffee"
}
```

Event

```text
service_call_created
```

---

## List Service Calls

```http
GET /api/service-calls
```

Caller

```text
Admin Tablet
```

Service

```text
ServiceCallService
```

---

## Get Current Seat Service Call

```http
GET /api/service-calls/current?seat_id=4
```

Caller

```text
Seat Tablet
```

Service

```text
ServiceCallService
```

---

## Resolve Service Call

```http
POST /api/service-calls/{call_id}/resolve
```

Caller

```text
Admin Tablet
```

Service

```text
ServiceCallService
```

Event

```text
service_call_resolved
```

---

## Cancel Service Call

```http
POST /api/service-calls/{call_id}/cancel
```

Caller

```text
Seat Tablet
Admin Tablet
```

Service

```text
ServiceCallService
```

Event

```text
service_call_cancelled
```

---

# 10. Translation APIs

## Process Translation

```http
POST /api/translations
```

Caller

```text
Seat Tablet
```

Service

```text
TranslationService
```

FormData

```text
audio
meeting_id
seat_id
session_key
final
```

Rules

```text
final=false
→ process_interim()

final=true
→ process_final()
→ persist history
→ translation_final event
```

---

## Get Translation History

```http
GET /api/translations
```

Query

```text
meeting_id
seat_id(optional)
```

Caller

```text
Admin Tablet
```

Service

```text
TranslationService
```

---

# 11. Error Codes

```text
MEETING_NOT_FOUND

ACTIVE_MEETING_EXISTS

MEETING_ALREADY_FINISHED

ATTENDEE_NOT_FOUND

SEAT_NOT_FOUND

SEAT_OCCUPIED

SEAT_NOT_OCCUPIED

SEAT_ALREADY_CHECKED_IN

INVALID_SEAT_STATE

SPEAKER_SEAT_NOT_FOUND

VOTE_NOT_FOUND

VOTE_CLOSED

DUPLICATE_VOTE

INVALID_VOTE_OPTION

SERVICE_CALL_NOT_FOUND

SERVICE_CALL_ALREADY_RESOLVED

TRANSLATION_FAILED

SPEECH_MODULE_ERROR

INTERNAL_ERROR
```
