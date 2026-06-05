# utterance_id 由后端生成

每条语音 utterance 的唯一标识由后端在收到 `start` 控制消息后生成，返回给前端。前端所有后续 interim/final 事件均使用此 ID。

utterance_id 关联后端多项业务状态：meeting_id、seat_id、speaker session、interim revision、final record、VAD segment、断线清理、Speaker Seat 切换。由后端生成可以保证唯一性、防止前端重连后冲突、避免伪造或乱序。

格式为 `utt_{meeting_id}_{seat_id}_{segment_seq}`，例如 `utt_1_3_000042`。segment_seq 由 `SpeechStreamSession` 内部维护的自增计数器生成。

前端在同一个 WebSocket 连接内连续说多句话时，无需重新发送 `start`——后端在每次 VAD 触发 final 后自动开启新 utterance，通过 `utterance_started` 消息通知前端新的 ID。
