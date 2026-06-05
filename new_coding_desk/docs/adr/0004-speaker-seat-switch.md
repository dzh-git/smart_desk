# Speaker Seat 切换为硬切换，旧 interim 丢弃

管理员切换 Speaker Seat 时，旧 seat 的 `/ws/speech` WebSocket 连接立即被服务端强制关闭，清理对应的 SpeechStreamSession，当前 interim 文本丢弃不写库、不 final。

系统定义"同一时间只有一个 Speaker Seat"，Speaker Seat 是 DB 持久化的单一发言席。旧连接继续处理会让"当前发言席"语义模糊，且静默丢弃音频会导致前端状态不一致（前端以为还在识别，后端已忽略）。"处理完当前 utterance 再切换"（软切换）会带来权限歧义——管理员切换到 seat 5 后，seat 3 的语音仍在 final，此时谁才是 speaker？

切换时可选广播 `translation_interim_cancelled` 事件（含 `reason: "speaker_seat_changed"`），让前端从 interimMap 中删除对应条目。UI 可短暂显示"发言席已切换，本段识别已取消"后移除。
