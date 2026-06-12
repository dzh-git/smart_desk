# SmartDesk Event Bus Specification

The EventBus decouples business services from WebSocket broadcasting. Services
publish typed events; `WebSocketEventHandler` forwards broadcastable events to
meeting WebSocket clients.

## Base Event Shape

```json
{
  "event": "event_name",
  "meeting_id": 1,
  "timestamp": 1748700000,
  "payload": {}
}
```

`meeting_id` is required for broadcast events. Seat and speaker-seat operations
derive it from the active meeting when one exists; callers do not pass arbitrary
meeting IDs from the frontend.

## Publishers

| Service | Events |
|---|---|
| `MeetingService` | `meeting_started`, `meeting_ended`, `vote_closed` when ending a meeting closes an open vote |
| `SeatService` | `seat_occupied`, `seat_vacant`, `checkin_prompt`, `check_in`, `speaker_seat_set`, `speaker_seat_clear`, `translation_interim_cancelled` on speaker switch |
| `VoteService` | `vote_started`, `vote_updated`, `vote_closed` |
| `ServiceCallService` | `service_call_created`, `service_call_resolved`, `service_call_cancelled` |
| `SpeechStreamService` | `translation_interim`, `translation_interim_cancelled` |
| `TranslationService` | `translation_final` |

## Broadcast Events

The WebSocket broadcaster forwards:

- seat events: `seat_occupied`, `seat_vacant`, `checkin_prompt`, `check_in`
- speaker events: `speaker_seat_set`, `speaker_seat_clear`
- meeting events: `meeting_started`, `meeting_ended`
- vote events: `vote_started`, `vote_updated`, `vote_closed`
- service call events: `service_call_created`, `service_call_resolved`, `service_call_cancelled`
- speech/translation events: `translation_interim`, `translation_interim_cancelled`, `translation_final`

## Speech Event Rules

`translation_interim`:

- published by `SpeechStreamService`;
- ephemeral;
- contains `utterance_id`, `seat_id`, `revision`, `source_text`, and optional `caption`;
- not persisted;
- not translated.

`translation_final`:

- published by `TranslationService`;
- created after final ASR;
- persisted in `translation_records`;
- contains `utterance_id`, `translation_id`, `source_text`, `translated_text`, and `source_type`.

`translation_interim_cancelled`:

- published when speaker seat changes, speech is cancelled, or pending interim text is discarded;
- clients remove the matching live caption;
- no database record is created.

## Speech Preload

Speech preload is an internal backend workflow, not a client broadcast event.
Meeting start and `/api/speech/preload` may trigger background model preload.
The frontend checks status with `GET /api/speech/status`.

## Client Handling Guidance

- For business events, re-fetch the relevant HTTP resources.
- For `translation_interim`, update the live caption in place by
  `utterance_id` and `revision`.
- For `translation_final`, remove matching interim caption and display the
  persisted final record.
- For `translation_interim_cancelled`, remove matching interim caption.
