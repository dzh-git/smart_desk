# SmartDesk WebSocket Protocol

Version: 1.0

Status: Frozen

---

# 1. Purpose

WebSocket 用于：

```text
服务端
↓
客户端
```

实时事件同步。

禁止：

```text
客户端
↓
WebSocket
↓
服务端业务调用
```

V1 WebSocket 仅用于服务端广播。

业务操作全部走 HTTP API。

---

# 2. Endpoint

```text
/ws/{meeting_id}
```

Example

```text
/ws/1
```

---

# 3. Supported Clients

```text
Admin Tablet

Seat Tablet 1
Seat Tablet 2
...
Seat Tablet 10
```

---

# 4. Connection Lifecycle

## Connect

Client

```text
WebSocket Connect
```

Server

```json
{
  "event": "connected",
  "meeting_id": 1,
  "timestamp": 1748700000,
  "payload": {}
}
```

---

## Disconnect

连接关闭。

不发送业务事件。

---

# 5. Message Format

所有广播统一格式：

```json
{
  "event": "event_name",
  "meeting_id": 1,
  "timestamp": 1748700000,
  "payload": {}
}
```

---

# 6. Common Fields

## event

事件名称。

例如：

```text
vote_started
translation_final
```

---

## meeting_id

所属会议。

---

## timestamp

Unix Timestamp

单位：

```text
seconds
```

---

## payload

业务数据。

---

# 7. Connection Management

## Room Model

一个会议对应一个 Room。

```text
meeting_id
↓
room
↓
connections
```

---

## Example

```text
meeting_id=1

connections:
    Admin
    Seat1
    Seat2
    Seat3
```

---

# 8. Broadcast Rules

默认：

```text
Room Broadcast
```

即：

```text
同会议所有客户端
```

全部接收。

---

# 9. Event Definitions

## connected

Payload

```json
{}
```

---

## seat_occupied

Payload

```json
{
  "seat_id": 3
}
```

---

## seat_vacant

Payload

```json
{
  "seat_id": 3
}
```

---

## checkin_prompt

Payload

```json
{
  "seat_id": 3
}
```

说明：

```text
仅Seat3平板显示签到弹窗
```

虽然广播给所有客户端。

只有目标客户端处理。

---

## check_in

Payload

```json
{
  "seat_id": 3,
  "attendee_id": 8
}
```

---

## speaker_seat_set

Payload

```json
{
  "seat_id": 5
}
```

---

## speaker_seat_clear

Payload

```json
{}
```

---

## meeting_started

Payload

```json
{
  "meeting_id": 1
}
```

---

## meeting_ended

Payload

```json
{
  "meeting_id": 1
}
```

---

## vote_started

Payload

```json
{
  "vote_id": 1,
  "title": "Approve Budget"
}
```

---

## vote_updated

Payload

```json
{
  "vote_id": 1
}
```

说明：

```text
不包含统计结果
```

---

## vote_closed

Payload

```json
{
  "vote_id": 1
}
```

---

## service_call_created

Payload

```json
{
  "call_id": 1,
  "seat_id": 4,
  "service_type": "coffee"
}
```

---

## service_call_resolved

Payload

```json
{
  "call_id": 1
}
```

---

## service_call_cancelled

Payload

```json
{
  "call_id": 1
}
```

---

## translation_final

Payload

```json
{
  "translation_id": 15,
  "seat_id": 3,
  "source_lang": "en",
  "target_lang": "zh",
  "source_text": "Hello everyone",
  "translated_text": "大家好"
}
```

---

# 10. Not Broadcast Events

以下事件不进入 WebSocket：

```text
translation_interim
```

原因：

```text
interim结果由HTTP直接返回
```

避免高频广播。

---

# 11. WebSocket Service Interface

```python
class WebSocketService:

    async def connect(
        meeting_id: int,
        websocket
    ):
        ...

    async def disconnect(
        meeting_id: int,
        websocket
    ):
        ...

    async def broadcast(
        meeting_id: int,
        message: dict
    ):
        ...
```

---

# 12. EventBus Integration

唯一允许方式：

```text
Service
↓
Publish Event
↓
EventBus
↓
WebSocketEventHandler
↓
WebSocketService.broadcast()
```

禁止：

```text
Service
↓
WebSocketService
```

直接调用。

---

# 13. V1 Scope

支持：

```text
单会议

11客户端以内

广播消息
```

不支持：

```text
客户端消息

点对点消息

跨会议广播

消息持久化
```
