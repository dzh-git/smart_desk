# SmartDesk WebSocket Protocol

SmartDesk uses two backend-owned WebSocket channels. The frontend never
connects directly to FunASR.

## Channels

### Meeting Broadcast Channel

```text
/ws/{meeting_id}?seat=N
```

Use this channel for meeting-wide server events. Clients do not perform
business writes over this channel.

### Speech Uplink Channel

```text
/ws/speech/{meeting_id}?seat=N
```

Only the current Speaker Seat may connect. The backend validates the active
meeting and speaker seat before accepting speech streaming.

Audio format:

- PCM signed 16-bit little-endian
- 16 kHz
- mono
- sent as binary WebSocket frames

## Speech Control Messages

Frontend to backend JSON messages:

```json
{"type": "start"}
```

Starts an utterance session and returns:

```json
{
  "type": "started",
  "utterance_id": "utt_1_1_000001",
  "session_key": "speech_1_1"
}
```

```json
{"type": "end_hint"}
```

Forces the backend to finalize the buffered utterance. This is a fallback; the
primary path is backend VAD auto-final.

```json
{"type": "cancel"}
```

Cancels the current interim utterance. Cancelled interim text is not persisted.

## Speech Flow

Primary path:

1. Speaker Seat connects to `/ws/speech/{meeting_id}?seat=N`.
2. Frontend sends `start`.
3. Frontend streams PCM16 binary frames.
4. After 500 ms noise calibration and three onset frames, the backend
   publishes `translation_interim` events for live caption display. Frames
   below the adaptive voice gate are not sent to ASR.
5. Punctuation-aware pause thresholds decide complete sentence/clause
   boundaries. After 30 seconds the next real sentence/clause boundary rolls
   the utterance; 45 seconds is the hard duration limit. A provisional period
   appended at the current text tail does not trigger the soft boundary.
6. On an automatic duration rollover, the backend publishes
   `translation_finalizing`, fully resets the streaming cache, and starts the
   next utterance immediately. The final 300 ms of PCM is replayed once to
   seed acoustic context; replay text and audio are not persisted twice.
7. Translation and persistence run in a bounded single-worker queue, then
   publish `translation_final`. Explicit `end_hint` still runs final ASR.

Fallback path:

1. Frontend sends `end_hint`.
2. Backend finalizes confirmed voice immediately if possible. A pure-silence
   buffer ends quietly without an error or persisted record.
3. Backend publishes `translation_final`.

Speaker Seat switch:

1. Setting or clearing the speaker seat invalidates the old speech connection.
2. Pending interim text for the old speaker is cancelled.
3. Backend broadcasts `translation_interim_cancelled`.
4. The new Speaker Seat may open a new speech WebSocket.

## Event Envelope

Broadcast events use:

```json
{
  "event": "event_name",
  "meeting_id": 1,
  "timestamp": 1748700000,
  "payload": {}
}
```

## `translation_interim`

Published for live speech captions. It is not persisted and is not translated.

```json
{
  "event": "translation_interim",
  "meeting_id": 1,
  "timestamp": 1748700000,
  "payload": {
    "utterance_id": "utt_1_1_000001",
    "seat_id": 1,
    "revision": 4,
    "source_lang": "zh",
    "target_lang": "en",
    "source_text": "Current punctuated interim text.",
    "caption": {
      "previous_line": "Previous short caption line.",
      "current_line": "Current short caption line.",
      "mode": "two_line"
    }
  }
}
```

Clients keep only the newest revision for each `utterance_id`.

## `translation_finalizing`

Published when an automatic segment enters pending history while translation
and persistence continue in the background. Clients atomically hand the live
caption to `next_utterance_id`, retaining the old lines until the next
utterance has produced its own line, so the live box never becomes empty.

```json
{
  "event": "translation_finalizing",
  "meeting_id": 1,
  "timestamp": 1748700000,
  "payload": {
    "utterance_id": "utt_1_1_000001",
    "seat_id": 1,
    "source_lang": "zh",
    "target_lang": "en",
    "source_text": "Completed realtime source text.",
    "boundary_reason": "soft_sentence_limit",
    "next_utterance_id": "utt_1_1_000002",
    "rollover_overlap_ms": 300,
    "caption": {
      "previous_line": "Previous caption line.",
      "current_line": "Completed realtime source text.",
      "mode": "two_line"
    }
  }
}
```

The last three fields are optional for compatibility with older clients.

## `translation_final`

Published after final ASR and persistence. Clients remove the matching interim
caption and display the final history record.

```json
{
  "event": "translation_final",
  "meeting_id": 1,
  "timestamp": 1748700000,
  "payload": {
    "utterance_id": "utt_1_1_000001",
    "translation_id": 42,
    "seat_id": 1,
    "source_lang": "zh",
    "target_lang": "en",
    "source_text": "Final punctuated source text.",
    "translated_text": "Final translated text or [translation not available].",
    "source_type": "speech_ws"
  }
}
```

## `translation_interim_cancelled`

Published when an interim utterance is discarded.

```json
{
  "event": "translation_interim_cancelled",
  "meeting_id": 1,
  "timestamp": 1748700000,
  "payload": {
    "utterance_id": "utt_1_1_000001",
    "seat_id": 1,
    "reason": "speaker_seat_changed"
  }
}
```

## Non-Speech Events

The meeting broadcast channel also carries:

- `seat_occupied`
- `seat_vacant`
- `checkin_prompt`
- `check_in`
- `speaker_seat_set`
- `speaker_seat_clear`
- `meeting_started`
- `meeting_ended`
- `vote_started`
- `vote_updated`
- `vote_closed`
- `agenda_updated`
- `service_call_created`
- `service_call_resolved`
- `service_call_cancelled`

The frontend should re-fetch affected HTTP resources after business events.
Speech interim events update the live transcript directly.

## `agenda_updated`

Published after agenda creation, deletion, or agenda state changes. Clients do
not perform agenda writes over WebSocket; they re-fetch
`GET /api/meetings/{meeting_id}/agendas` after receiving this event.

```json
{
  "event": "agenda_updated",
  "meeting_id": 1,
  "timestamp": 1781344800,
  "payload": {
    "meeting_id": 1,
    "agenda_id": 2,
    "action": "set_current",
    "current_agenda_id": 2
  }
}
```

`payload.action` values:

- `create`
- `delete`
- `set_current`
- `advance`
- `complete`
- `skip`

Frontend handling:

- Ignore the event if `message.meeting_id` does not match the current effective
  meeting id.
- For `/display`, the effective meeting id may be the active meeting id or the
  ended meeting id used for preserved results.
- On a matching event, re-fetch agendas and derive current topic/progress from
  the returned `Agenda[]`.
