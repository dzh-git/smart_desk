# SmartDesk Database Schema

SmartDesk v1 uses SQLite through SQLAlchemy repositories. Repository classes
own database access; services own business rules and event publication.

## Tables

### `meetings`

| Column | Type | Notes |
|---|---|---|
| `id` | integer | Primary key. |
| `title` | string | Meeting title. |
| `description` | text | Optional description. |
| `status` | string | `pending`, `active`, or `finished`. |
| `created_at` | datetime | Creation time. |
| `started_at` | datetime nullable | Start time. |
| `ended_at` | datetime nullable | End time. |

Only one active meeting is supported.

### `agendas`

| Column | Type | Notes |
|---|---|---|
| `id` | integer | Primary key. |
| `meeting_id` | integer | FK to `meetings.id`. |
| `title` | string | Agenda title. |
| `sort_order` | integer | Display order. |
| `status` | string | `pending`, `active`, `completed`, or `skipped`. |
| `started_at` | datetime nullable | Set when the item becomes active. |
| `completed_at` | datetime nullable | Set when the item is completed. |
| `skipped_at` | datetime nullable | Set when the item is skipped. |

Agenda state is backend persisted. Only one agenda item may be active for a
meeting. Status mutation rules are documented in `API_SPEC.md`.

### `people`

| Column | Type | Notes |
|---|---|---|
| `id` | string | Stable primary key returned by Android local identity recognition. |
| `name` | string | Canonical display name. |
| `active` | boolean | Whether identity may be used for check-in. |
| `created_at` | datetime | Creation time. |

A Person is stable across meetings. Face templates refer to `people.id`, never
to a temporary attendee row.

### `attendees`

| Column | Type | Notes |
|---|---|---|
| `id` | integer | Primary key. |
| `meeting_id` | integer | FK to `meetings.id`. |
| `person_id` | string nullable | Optional FK to `people.id`. Unique per meeting when present. |
| `name` | string | Attendee name. |
| `title` | string | Attendee title. |
| `seat_id` | integer nullable | Bound seat. |
| `checked_in` | boolean | Check-in state. |

Seat binding must stay consistent with `seat_states.attendee_id`.

### `seat_states`

| Column | Type | Notes |
|---|---|---|
| `seat_id` | integer | Primary key, 1 through 9; seat 1 is the host seat. |
| `status` | string | `vacant`, `occupied_unchecked`, or `checked_in`. |
| `attendee_id` | integer nullable | Bound attendee. |
| `updated_at` | datetime | Last update. |

The table always represents the current state of the 9 physical seats.

### `speaker_seat`

| Column | Type | Notes |
|---|---|---|
| `id` | integer | Singleton row. |
| `seat_id` | integer nullable | Current speaker seat. |
| `updated_at` | datetime | Last update. |

Meeting end does not automatically clear speaker seat.

### `votes`

| Column | Type | Notes |
|---|---|---|
| `id` | integer | Primary key. |
| `meeting_id` | integer | FK to `meetings.id`. |
| `title` | string | Vote title. |
| `options_json` | text | JSON list of options. |
| `is_anonymous` | boolean | Anonymous display flag. |
| `status` | string | `open` or `closed`. |
| `created_at` | datetime | Creation time. |
| `closed_at` | datetime nullable | Close time. |

### `vote_records`

| Column | Type | Notes |
|---|---|---|
| `id` | integer | Primary key. |
| `vote_id` | integer | FK to `votes.id`. |
| `attendee_id` | integer | FK to `attendees.id`. |
| `option` | string | Selected option. |
| `created_at` | datetime | Vote time. |

Repeated voting by the same attendee updates the existing vote record.

### `service_calls`

| Column | Type | Notes |
|---|---|---|
| `id` | integer | Primary key. |
| `meeting_id` | integer | FK to `meetings.id`. |
| `seat_id` | integer | Requesting seat. |
| `service_type` | string | Backend-supported service type. |
| `status` | string | `pending`, `resolved`, or `cancelled`. |
| `created_at` | datetime | Creation time. |
| `resolved_at` | datetime nullable | Resolution time. |

### `translation_records`

| Column | Type | Notes |
|---|---|---|
| `id` | integer | Primary key. |
| `meeting_id` | integer | FK to `meetings.id`. |
| `seat_id` | integer | Speaker seat. |
| `source_lang` | string | Usually `zh` or `auto`. |
| `target_lang` | string | Usually `en` or `auto`. |
| `source_text` | text | Final punctuated ASR text. |
| `translated_text` | text | Real translation or `[translation not available]`. |
| `created_at` | datetime | Creation time. |
| `utterance_id` | string nullable | Links final record to speech utterance. |
| `source_type` | string nullable | `speech_ws`, `manual_upload`, or `seed`. |

Only final speech results are persisted. Interim captions are WebSocket-only.

## Migration Policy

SQLite schema updates must be idempotent. Existing demo databases may be
deleted during cleanup, but code-level migrations must preserve existing rows
when users keep a local database.

The Android identity migration adds nullable `attendees.person_id` without
guessing mappings for historical attendees. Existing deployments receive a
partial unique index on `(meeting_id, person_id)` for non-null values.

## Repository Ownership

| Repository | Owns |
|---|---|
| `MeetingRepository` | `meetings`, `agendas` |
| `PersonRepository` | `people` |
| `AttendeeRepository` | `attendees` |
| `SeatRepository` | `seat_states`, `speaker_seat` |
| `VoteRepository` | `votes`, `vote_records` |
| `ServiceCallRepository` | `service_calls` |
| `TranslationRepository` | `translation_records` |
