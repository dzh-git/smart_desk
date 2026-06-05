# SmartDesk Event Bus Specification

Version: 2.0

Status: Speech Integration Contract

Last Updated: 2026-06-05

---

# 1. Purpose

EventBus decouples domain services from WebSocket broadcasting.

Allowed flow:

```text
Service
-> EventBus.publish()
-> WebSocketEventHandler
-> WebSocketService.broadcast()
```

Forbidden flow:

```text
Service -> WebSocketService
Router  -> EventBus.publish()
Repository -> EventBus.publish()
```

Speech WebSocket endpoints may receive client audio/control messages, but they
must delegate speech decisions to service code. `speech_module/` is legacy
reference code and must not be modified by SmartDesk implementation tasks.

---

# 2. Base Event Schema

```python
class BaseEvent:
    event_name: str
    meeting_id: int | None
    timestamp: datetime
    payload: dict
```

Events are in-process notifications. They are not persisted. Speech final
records are persisted separately in `translation_records`.

---

# 3. Event Categories

## Seat Events

```text
seat_occupied
seat_vacant
checkin_prompt
check_in
speaker_seat_set
speaker_seat_clear
```

## Meeting Events

```text
meeting_started
meeting_ended
```

## Vote Events

```text
vote_started
vote_updated
vote_closed
```

## Service Call Events

```text
service_call_created
service_call_resolved
service_call_cancelled
```

## Translation Events

```text
translation_interim
translation_final
translation_interim_cancelled
```

---

# 4. Existing Business Events

Existing seat, meeting, vote, and service-call events keep their current
publishers and payloads:

| Event | Publisher | Broadcast |
|---|---|---|
| `seat_occupied` | SeatService | YES |
| `seat_vacant` | SeatService | YES |
| `checkin_prompt` | SeatService | YES |
| `check_in` | SeatService | YES |
| `speaker_seat_set` | SeatService | YES |
| `speaker_seat_clear` | SeatService | YES |
| `meeting_started` | MeetingService | YES |
| `meeting_ended` | MeetingService | YES |
| `vote_started` | VoteService | YES |
| `vote_updated` | VoteService | YES |
| `vote_closed` | VoteService | YES |
| `service_call_created` | ServiceCallService | YES |
| `service_call_resolved` | ServiceCallService | YES |
| `service_call_cancelled` | ServiceCallService | YES |

---

# 5. Translation Events

## translation_interim

Publisher: `SpeechStreamService`

Subscribers: `WebSocketEventHandler`

Broadcast: YES

Persistence: NO

Payload:

```json
{
  "utterance_id": "utt_1_3_000042",
  "seat_id": 3,
  "revision": 4,
  "source_lang": "zh",
  "target_lang": "en",
  "source_text": "我认为这个方案需要重新",
  "translated_text": "",
  "is_final": false
}
```

Meaning: streaming ASR produced an updated interim transcript for the current
utterance. Clients update local interim UI state and do not persist this event.

## translation_final

Publisher: `TranslationService`

Subscribers: `WebSocketEventHandler`

Broadcast: YES

Persistence: YES, through `translation_records`

Payload:

```json
{
  "utterance_id": "utt_1_3_000042",
  "translation_id": 42,
  "seat_id": 3,
  "source_lang": "zh",
  "target_lang": "en",
  "source_text": "我认为这个方案需要重新评估。",
  "translated_text": "I think this plan needs to be re-evaluated.",
  "source_type": "offline_rescore"
}
```

Meaning: the backend has finalized an utterance using offline ASR rescore,
persisted the record, and broadcast the final transcript.

## translation_interim_cancelled

Publisher: `SpeechStreamService`

Subscribers: `WebSocketEventHandler`

Broadcast: YES

Persistence: NO

Payload:

```json
{
  "utterance_id": "utt_1_3_000042",
  "seat_id": 3,
  "reason": "speaker_seat_changed"
}
```

Meaning: an interim utterance was discarded and will not produce a final
record. Speaker Seat hard switch is the primary reason.

---

# 6. WebSocket Mapping

The following EventBus events are broadcast to `/ws/{meeting_id}`:

```text
seat_occupied
seat_vacant
checkin_prompt
check_in
speaker_seat_set
speaker_seat_clear
meeting_started
meeting_ended
vote_started
vote_updated
vote_closed
service_call_created
service_call_resolved
service_call_cancelled
translation_interim
translation_final
translation_interim_cancelled
```

`translation_interim` and `translation_interim_cancelled` are ephemeral UI
events. `translation_final` is the durable event that corresponds to a database
record.

---

# 7. Event Handler Registration

WebSocket event handlers are registered at application startup for the complete
broadcast event list. Runtime dynamic registration is forbidden.

```python
event_bus.subscribe(event_name, websocket_handler)
```

---

# 8. EventBus Interface

```python
class EventBus:
    def publish(self, event: BaseEvent) -> None:
        ...

    def subscribe(self, event_name: str, handler) -> None:
        ...
```
