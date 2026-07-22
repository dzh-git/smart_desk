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
{"type": "start", "language_mode": "auto"}
```

Starts an utterance session and returns:

```json
{
  "type": "started",
  "utterance_id": "utt_1_1_000001",
  "session_key": "speech_1_1",
  "language_mode": "auto"
}
```

`language_mode` is `auto`, `zh`, or `en` and defaults to `auto` for older
clients. Invalid values return `INVALID_LANGUAGE_MODE`. The selected route is
locked for one utterance and inherited by automatic rollover/reconnection.

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
4. After 300 ms noise calibration and two confirming onset frames, the backend
   publishes `translation_interim` events for live caption display. Frames
   below the adaptive voice gate are not sent to ASR. The absolute onset floor
   is 5 mRMS so clean low-output browser microphones are still admitted.
5. Semantic sentence boundaries are terminal punctuation plus a 0.9 second
   pause, terminal punctuation confirmed by following content, or a 2 second
   natural pause. English Zipformer hypotheses pass through a local online
   punctuation/casing model. The 0.9 second pause is only a candidate: an
   incomplete tail such as `Do we have any` remains forming, while later words
   can reveal internal boundaries such as `Any questions? Do we have any
   assignments?`. Commas and visual wrapping do not trigger translation. The
   45 second hard duration limit commits remaining text.
6. On an automatic duration rollover, the backend publishes
   `translation_finalizing`, fully resets the streaming cache, and starts the
   next utterance immediately. The final 300 ms of PCM is replayed once to
   seed acoustic context; replay text and audio are not persisted twice.
7. `zh` uses streaming Paraformer. `en` uses the local sherpa-onnx Zipformer
   online stream, accepting each PCM frame once. `auto` probes 1.2 seconds of
   admitted speech, locks the detected route for the utterance, and replays the
   probe PCM into the selected stream so sentence onset is retained. English
   text is post-processed by the local sherpa-onnx CNN-BiLSTM punctuation model;
   missing punctuation degrades to readable unpunctuated text without stopping
   ASR. When the
   Zipformer model is missing, English visibly falls back to one-second bounded
   SenseVoice snapshots (`sensevoice_rolling_fallback`). SenseVoiceSmall still
   performs final language detection/correction; Chinese audio is rescored by
   Paraformer-large. Translation and persistence run in a bounded single-worker
   queue, then publish `translation_final`.
   Explicit `end_hint` uses the same queue.

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

Published for immediate live source captions. It is not persisted and does not
translate incomplete text. Semantic sentence identity is independent from the
optional two-line visual caption.

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
    "translated_text": "",
    "requested_language": "auto",
    "detected_language": "zh",
    "recognition_engine": "paraformer_streaming",
    "sentence_id": "utt_1_1_000001:s000001",
    "sentence_sequence": 1,
    "sentence_source_text": "Current sentence being formed.",
    "sentence_state": "forming",
    "caption": {
      "previous_line": "Previous short caption line.",
      "current_line": "Current short caption line.",
      "mode": "two_line"
    }
  }
}
```

Clients keep only the newest source revision for each `utterance_id` and update
the forming lyric row by `sentence_id`. For English, a completed Zipformer row
is first published with `recognition_status: "correcting"` and
`source_locked: false`; the local SenseVoice correction may replace it once.
When `source_locked: true` arrives, clients must never replace that row's
`source_text` again, even if a delayed event has a higher revision.

The live lyric viewport applies display-only English wrapping: after 30 words
it waits for the next sentence-ending punctuation, after 40 words it accepts
the next comma/semicolon/other clause punctuation, and at 50 words it forces a
word-boundary line break. This does not alter WebSocket text, sentence IDs,
translation input, or persisted meeting records.

PCM ingress is buffered in an ordered 50-frame queue. `end_hint` drains it
before finalization; `cancel` clears it. The status endpoint exposes queue depth,
audio backlog, recognition route and CPU thread budget.

## `translation_sentence`

Published twice for each completed semantic sentence: first with `pending`,
then with `ok` or `unavailable`. English adds a sentence-recognition correction
step before translation. Completed jobs are processed FIFO and are not
replaced by later sentences.

```json
{
  "event": "translation_sentence",
  "meeting_id": 1,
  "timestamp": 1748700000,
  "payload": {
    "utterance_id": "utt_1_1_000001",
    "sentence_id": "utt_1_1_000001:s000001",
    "sentence_sequence": 1,
    "seat_id": 1,
    "revision": 8,
    "source_lang": "zh",
    "target_lang": "en",
    "source_text": "第一句完成了。",
    "translated_text": "The first sentence is complete.",
    "translation_status": "ok"
  }
}
```

Clients retain the meeting's sentence pairs per seat. The fixed-height lyric viewport
keeps the newest completed/forming row at the bottom and scrolls older pairs upward.
A forming row has no translation;
after completion it shows pending, then the result. Source and target scroll or
disappear together. `translation_error` is optional for unavailable results.

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
    "source_lang": "unknown",
    "target_lang": "unknown",
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

Published after final ASR and persistence. Clients remove the matching legacy
interim and update persisted history, but do not clear sentence lyric pairs.

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
    "source_type": "speech_ws",
    "translation_status": "ok",
    "recognition_status": "ok"
  }
}
```

Final language pairs are `zh→en` or `en→zh`. On a non-fatal model failure,
`translation_status` is `unavailable`, `translation_error` explains the local
model problem, and `recognition_status` may be `degraded` when streaming text
was used as the fallback.

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
