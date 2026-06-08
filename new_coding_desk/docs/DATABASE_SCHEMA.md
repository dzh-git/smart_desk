# SmartDesk Database Schema

Version: 1.0

Status: Frozen

Database:

```text
SQLite
```

Scope:

```text
Single Active Meeting
10 Seats
Local Deployment
```

---

# 1. Design Principles

## D1. Business Driven

数据库设计服务于业务模型。

禁止为实现方便增加冗余表。

---

## D2. Repository Boundary

每张表必须归属唯一 Repository。

禁止多个 Repository 共同维护同一业务状态。

---

## D3. Immutable History

历史数据只新增。

禁止修改历史翻译记录。

禁止修改历史投票记录。

---

# 2. Entity Relationship

```text
Meeting
 ├── Agenda
 ├── Attendee
 ├── Vote
 │     └── VoteRecord
 ├── ServiceCall
 └── TranslationRecord

SeatState

SpeakerSeat
```

---

# 3. meetings

会议主表。

## Table

```sql
meetings
```

| Field       | Type       | Nullable |
| ----------- | ---------- | -------- |
| id          | INTEGER PK | NO       |
| title       | TEXT       | NO       |
| description | TEXT       | YES      |
| status      | TEXT       | NO       |
| created_at  | DATETIME   | NO       |
| started_at  | DATETIME   | YES      |
| ended_at    | DATETIME   | YES      |

---

## Status

```text
pending
active
finished
```

---

## Constraints

```text
仅允许一个 active meeting
```

由 Service 保证。

---

## Repository

```text
MeetingRepository
```

---

# 4. agendas

## Table

```sql
agendas
```

| Field      | Type       |
| ---------- | ---------- |
| id         | INTEGER PK |
| meeting_id | INTEGER FK |
| title      | TEXT       |
| sort_order | INTEGER    |

---

## Index

```sql
(meeting_id, sort_order)
```

---

## Repository

```text
MeetingRepository
```

---

# 5. attendees

会议参会人员。

---

## Table

```sql
attendees
```

| Field      | Type         |
| ---------- | ------------ |
| id         | INTEGER PK   |
| meeting_id | INTEGER FK   |
| name       | TEXT         |
| title      | TEXT         |
| seat_id    | INTEGER NULL |
| checked_in | BOOLEAN      |

---

## Rules

```text
name 不要求唯一

业务主键为 attendee_id
```

---

## Index

```sql
(meeting_id)
```

---

## Repository

```text
AttendeeRepository
```

---

# 6. seat_states

座位实时状态。

---

## Table

```sql
seat_states
```

| Field       | Type         |
| ----------- | ------------ |
| seat_id     | INTEGER PK   |
| status      | TEXT         |
| attendee_id | INTEGER NULL |
| updated_at  | DATETIME     |

---

## Status

```text
vacant

occupied_unchecked

checked_in
```

---

## Rules

```text
seat_id 固定为 1~10

系统初始化时自动创建10条记录
```

---

## Example

```text
seat_id=3

status=checked_in

attendee_id=12
```

---

## Repository

```text
SeatRepository
```

---

# 7. speaker_seat

当前发言席。

---

## Table

```sql
speaker_seat
```

| Field      | Type       |
| ---------- | ---------- |
| id         | INTEGER PK |
| seat_id    | INTEGER    |
| updated_at | DATETIME   |

---

## Rules

```text
表中永远只允许存在一条记录

系统初始化自动创建

id 固定为 1

seat_id 可为空
```

---

## Example

```text
id=1

seat_id=5
```

---

## Repository

```text
SeatRepository
```

---

# 8. votes

投票定义。

---

## Table

```sql
votes
```

| Field        | Type          |
| ------------ | ------------- |
| id           | INTEGER PK    |
| meeting_id   | INTEGER FK    |
| title        | TEXT          |
| options_json | TEXT          |
| is_anonymous | BOOLEAN       |
| status       | TEXT          |
| created_at   | DATETIME      |
| closed_at    | DATETIME NULL |

---

## Status

```text
open
closed
```

---

## Rules

```text
同一时间最多一个 open vote
```

由 VoteService 保证。

---

## Repository

```text
VoteRepository
```

---

# 9. vote_records

投票记录。

---

## Table

```sql
vote_records
```

| Field       | Type       |
| ----------- | ---------- |
| id          | INTEGER PK |
| vote_id     | INTEGER FK |
| attendee_id | INTEGER FK |
| option      | TEXT       |
| created_at  | DATETIME   |

---

## Constraints

唯一约束：

```sql
(vote_id, attendee_id)
```

---

## Purpose

保证：

```text
一个人只能投一次
```

---

## Repository

```text
VoteRepository
```

---

# 10. service_calls

服务请求。

Rule:

同一 seat
同时仅允许一个 pending service call

由 ServiceCallService 保证

---

## Table

```sql
service_calls
```

| Field        | Type          |
| ------------ | ------------- |
| id           | INTEGER PK    |
| meeting_id   | INTEGER FK    |
| seat_id      | INTEGER       |
| service_type | TEXT          |
| status       | TEXT          |
| created_at   | DATETIME      |
| resolved_at  | DATETIME NULL |

---

## Service Type

```text
coffee

tea

water

other
```

---

## Status

```text
pending

resolved

cancelled
```

---

## Repository

```text
ServiceCallRepository
```

---

# 11. translation_records

翻译历史。

翻译当前为占位：`translated_text` 字段返回 `[translation not available]`，真实机器翻译为 deferred/future 能力。

---

## Table

```sql
translation_records
```

| Field           | Type       |
| --------------- | ---------- |
| id              | INTEGER PK |
| meeting_id      | INTEGER FK |
| seat_id         | INTEGER    |
| source_lang     | TEXT       |
| target_lang     | TEXT       |
| source_text     | TEXT       |
| translated_text | TEXT       |
| utterance_id    | TEXT NULL  |
| source_type     | TEXT NULL  |
| created_at      | DATETIME   |

---

## Rules

```text
只允许新增

禁止修改

utterance_id 用于 interim/final 对齐，旧数据允许 NULL

source_type 用于区分来源：speech_ws、manual_upload、seed 等，旧数据允许 NULL
```

---

## Index

```sql
(meeting_id)

(seat_id)
```

---

## Repository

```text
TranslationRepository
```

---

# 12. Foreign Key Rules

## agendas

```text
meeting_id
→ meetings.id
```

---

## attendees

```text
meeting_id
→ meetings.id
```

---

## votes

```text
meeting_id
→ meetings.id
```

---

## vote_records

```text
vote_id
→ votes.id

attendee_id
→ attendees.id
```

---

## service_calls

```text
meeting_id
→ meetings.id
```

---

## translation_records

```text
meeting_id
→ meetings.id
```

---

# 13. Required Indexes

```sql
agendas(meeting_id, sort_order)

attendees(meeting_id)

votes(meeting_id, status)

vote_records(vote_id)

vote_records(attendee_id)

service_calls(meeting_id, status)

translation_records(meeting_id)

translation_records(seat_id)
```

---

# 14. Initialization Data

系统首次启动时：

自动创建：

```text
seat_states

seat_id:
1~10
```

状态：

```text
vacant
```

---

自动创建：

```text
speaker_seat
```

记录：

```text
seat_id = NULL
```

---

# 15. Repository Ownership

MeetingRepository

```text
meetings
agendas
```

---

AttendeeRepository

```text
attendees
```

---

SeatRepository

```text
seat_states
speaker_seat
```

---

VoteRepository

```text
votes
vote_records
```

---

ServiceCallRepository

```text
service_calls
```

---

TranslationRepository

```text
translation_records
```

---

# 16. Tables Summary

```text
meetings
agendas
attendees

seat_states
speaker_seat

votes
vote_records

service_calls

translation_records
```

Total:

9 Tables
