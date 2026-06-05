# 语音上行从 HTTP chunk 改为 WebSocket 音频流

语音识别通道从逐 chunk HTTP POST 改为双 WebSocket 架构：通道 A（`/ws/{meeting_id}`）保持会议事件广播，新增通道 B（`/ws/speech/{meeting_id}?seat=N`）专用于 Speaker Seat 上行 PCM16 音频。后端在内存缓存整句 PCM，VAD 触发后走向离线 ASR rescore → 翻译 → 写库，而非直接把流式 partial 写入历史。

替换的方案是继续用 HTTP POST 按 chunk 上传音频（`POST /api/translations` 的 `final=false` / `final=true`）。不选 HTTP 的原因是：HTTP 请求的 TCP/TLS 握手开销对高频 interim 不友好；interim 只返回给上传端，管理员无法看到流式文本；`final=true` 要求客户端精准判断句子结束，前端 VAD 在浏览器环境下不可靠。

选择 WebSocket 音频流的原因：一次握手后零协议开销；后端 Server VAD 统一判定断句，保证 final 文本的可信度；天然支持流式 ASR；为 `translation_interim` 广播到所有客户端打下基础。

旧 `POST /api/translations` 端点保留兼容，但内部委托给新 `process_final_file()` 路径。
