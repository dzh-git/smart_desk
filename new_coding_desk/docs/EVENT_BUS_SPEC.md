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
| `MeetingService` | `agenda_updated` after agenda create/delete/set-current/advance/complete/skip |
| `SeatService` | `seat_occupied`, `seat_vacant`, `checkin_prompt`, `check_in`, `speaker_seat_set`, `speaker_seat_clear`, `translation_interim_cancelled` on speaker switch |
| `VoteService` | `vote_started`, `vote_updated`, `vote_closed` |
| `ServiceCallService` | `service_call_created`, `service_call_resolved`, `service_call_cancelled` |
| `SpeechStreamService` | `translation_interim`, `translation_sentence`, `translation_interim_cancelled` |
| `TranslationService` | `translation_final` |

## Broadcast Events

The WebSocket broadcaster forwards:

- seat events: `seat_occupied`, `seat_vacant`, `checkin_prompt`, `check_in`
- speaker events: `speaker_seat_set`, `speaker_seat_clear`
- meeting events: `meeting_started`, `meeting_ended`
- agenda events: `agenda_updated`
- vote events: `vote_started`, `vote_updated`, `vote_closed`
- service call events: `service_call_created`, `service_call_resolved`, `service_call_cancelled`
- speech/translation events: `translation_interim`, `translation_sentence`, `translation_interim_cancelled`, `translation_finalizing`, `translation_final`

## Agenda Event Rules

`agenda_updated`:

- published by `MeetingService`;
- published after agenda `create`, `delete`, `set_current`, `advance`,
  `complete`, or `skip`;
- broadcast to the meeting room;
- contains `meeting_id`, `agenda_id`, `action`, and `current_agenda_id`;
- does not carry the full agenda list;
- clients re-fetch `GET /api/meetings/{meeting_id}/agendas`.

Payload shape:

```json
{
  "meeting_id": 1,
  "agenda_id": 2,
  "action": "set_current",
  "current_agenda_id": 2
}
```

Allowed `action` values:

- `create`
- `delete`
- `set_current`
- `advance`
- `complete`
- `skip`

Clients must ignore `agenda_updated` when the event `meeting_id` does not match
the current effective meeting id.

## Speech Event Rules

`translation_interim`:

- source revisions are published by `SpeechStreamService`;
- ephemeral;
- contains `utterance_id`, `seat_id`, `revision`, language direction,
  `source_text`, optional `caption`, and the current `sentence_id`,
  `sentence_sequence`, `sentence_source_text`, `sentence_state`;
- not persisted;
- visual line wrapping is independent from semantic sentence completion.

`translation_sentence`:

- ephemeral sentence-level lyric event published as `pending`, then as `ok` or
  `unavailable` for the same `sentence_id`;
- English sentence events additionally carry `recognition_status` and
  `source_locked`; a `correcting` raw stream result may be replaced once by
  local SenseVoice, and a locked source must remain immutable thereafter;
- completed sentences use an ordered FIFO worker and are never replaced by a
  newer sentence;
- clients retain the meeting's source/translation pairs per seat; the fixed-height
  lyric viewport keeps the newest pair at the bottom and scrolls older pairs upward;
- terminal punctuation requires a short pause or following content; commas and
  visual length wrapping do not complete a sentence.

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
- For `translation_sentence`, update only the matching `sentence_id`; do not
  clear lyric pairs on `translation_finalizing` or `translation_final`.
- For `translation_final`, remove matching interim caption and display the
  persisted final record.
- For `translation_interim_cancelled`, remove matching interim caption.
