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
4. Backend publishes `translation_interim` events for live caption display.
5. Backend RMS endpoint detection decides the utterance boundary.
6. Backend runs final ASR, persists the final record, and publishes
   `translation_final`.
7. The same speech WebSocket stays open and a new utterance can start.

Fallback path:

1. Frontend sends `end_hint`.
2. Backend finalizes the current buffer immediately if possible.
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
- `service_call_created`
- `service_call_resolved`
- `service_call_cancelled`

The frontend should re-fetch affected HTTP resources after business events.
Speech interim events update the live transcript directly.
