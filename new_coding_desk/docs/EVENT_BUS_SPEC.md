# SmartDesk Event Bus Specification

Version: 1.0

Status: Frozen

Architecture:

```text
Service
↓
EventBus.publish()
↓
Event Handler
↓
WebSocketService.broadcast()
```

---

# 1. Purpose

EventBus 用于实现模块解耦。

禁止：

```python
seat_service.set_speaker()

ws_service.broadcast(...)
```

正确：

```python
seat_service.set_speaker()

event_bus.publish(
    SpeakerSeatSetEvent(...)
)
```

---

# 2. Event Rules

## E1

事件必须由 Service 发布。

禁止：

```text
Router 发布事件
Repository 发布事件
WebSocket 发布事件
```

---

## E2

事件必须为业务事件。

正确：

```text
VoteStartedEvent
```

错误：

```text
DatabaseUpdatedEvent
```

---

## E3

事件为进程内事件。

V1 不使用：

```text
Kafka
RabbitMQ
Redis Stream
```

---

## E4

事件默认不持久化。

仅用于：

```text
模块通知
WebSocket广播
```

---

# 3. Base Event Schema

所有事件统一格式：

```python
class BaseEvent:
    event_name: str
    meeting_id: int | None
    timestamp: datetime
    payload: dict
```

---

# 4. Event Publishing Flow

```text
HardwareService
↓
SeatService
↓
seat_occupied
↓
EventBus
↓
WebSocketEventHandler
↓
WebSocketService
```

---

# 5. Event Categories

## Seat Events

```text
seat_occupied
seat_vacant
checkin_prompt
check_in
speaker_seat_set
speaker_seat_clear
```

---

## Meeting Events

```text
meeting_started
meeting_ended
```

---

## Vote Events

```text
vote_started
vote_updated
vote_closed
```

---

## Service Call Events

```text
service_call_created
service_call_resolved
service_call_cancelled
```

---

## Translation Events

translation_final

---

# 6. Seat Events

## seat_occupied

Publisher

```text
SeatService
```

Subscribers

```text
WebSocketEventHandler
```

Payload

```json
{
  "seat_id": 3
}
```

Meaning

```text
SeatService确认座位状态从 vacant
变为 occupied_unchecked 后发布
```

Broadcast

```text
YES
```

---

## seat_vacant

Publisher

```text
SeatService
```

Subscribers

```text
WebSocketEventHandler
```

Payload

```json
{
  "seat_id": 3
}
```

Meaning

```text
SeatService确认座位状态变为 vacant 后发布
```

Broadcast

```text
YES
```

---

## checkin_prompt

Publisher

```text
SeatService
```

Subscribers

```text
WebSocketEventHandler
```

Payload

```json
{
  "seat_id": 3
}
```

Broadcast

```text
YES
```

---

## check_in

Publisher

```text
SeatService
```

Subscribers

```text
WebSocketEventHandler
```

Payload

```json
{
  "seat_id": 3,
  "attendee_id": 8
}
```

Broadcast

```text
YES
```

---

## speaker_seat_set

Publisher

```text
SeatService
```

Subscribers

```text
WebSocketEventHandler
```

Payload

```json
{
  "seat_id": 5
}
```

Broadcast

```text
YES
```

---

## speaker_seat_clear

Publisher

```text
SeatService
```

Subscribers

```text
WebSocketEventHandler
```

Payload

```json
{}
```

Broadcast

```text
YES
```

---

# 7. Meeting Events

## meeting_started

Publisher

```text
MeetingService
```

Subscribers

```text
WebSocketEventHandler
```

Payload

```json
{
  "meeting_id": 1
}
```

Broadcast

```text
YES
```

---

## meeting_ended

Publisher

```text
MeetingService
```

Subscribers

```text
WebSocketEventHandler
```

Payload

```json
{
  "meeting_id": 1
}
```

Broadcast

```text
YES
```

---

# 8. Vote Events

## vote_started

Publisher

```text
VoteService
```

Subscribers

```text
WebSocketEventHandler
```

Payload

```json
{
  "vote_id": 1,
  "title": "Approve Budget"
}
```

Broadcast

```text
YES
```

---

## vote_updated

Publisher

```text
VoteService
```

Subscribers

```text
WebSocketEventHandler
```

Payload

```json
{
  "vote_id": 1
}
```

Broadcast

```text
YES
```

Notes

```text
不广播具体投票内容

避免泄露投票结果
```

---

## vote_closed

Publisher

```text
VoteService
```

Subscribers

```text
WebSocketEventHandler
```

Payload

```json
{
  "vote_id": 1
}
```

Broadcast

```text
YES
```

---

# 9. Service Call Events

## service_call_created

Publisher

```text
ServiceCallService
```

Subscribers

```text
WebSocketEventHandler
```

Payload

```json
{
  "call_id": 1,
  "seat_id": 4,
  "service_type": "coffee"
}
```

Broadcast

```text
YES
```

---

## service_call_resolved

Publisher

```text
ServiceCallService
```

Subscribers

```text
WebSocketEventHandler
```

Payload

```json
{
  "call_id": 1
}
```

Broadcast

```text
YES
```

---

## service_call_cancelled

Publisher

```text
ServiceCallService
```

Subscribers

```text
WebSocketEventHandler
```

Payload

```json
{
  "call_id": 1
}
```

Broadcast

```text
YES
```

---

# 10. Translation Events

## translation_final

Publisher

```text
TranslationService
```

Subscribers

```text
WebSocketEventHandler
```

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

Broadcast

```text
YES
```

---

# 11. WebSocket Mapping

EventBus Event

↓

WebSocket Event

一一对应：

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

translation_final
```

---

# 12. Event Handler Registration

V1 固定注册：

```python
event_bus.subscribe(
    event_name,
    websocket_handler
)
```

启动时完成。

禁止运行时动态注册。

---

# 13. EventBus Interface

```python
class EventBus:

    def publish(
        self,
        event: BaseEvent
    ) -> None:
        ...

    def subscribe(
        self,
        event_name: str,
        handler
    ) -> None:
        ...
```

---

# 14. Responsibility Matrix

| Event                  | Publisher          | Broadcast |
| ---------------------- | ------------------ | --------- |
| seat_occupied          | SeatService        | YES       |
| seat_vacant            | SeatService        | YES       |
| checkin_prompt         | SeatService        | YES       |
| check_in               | SeatService        | YES       |
| speaker_seat_set       | SeatService        | YES       |
| speaker_seat_clear     | SeatService        | YES       |
| meeting_started        | MeetingService     | YES       |
| meeting_ended          | MeetingService     | YES       |
| vote_started           | VoteService        | YES       |
| vote_updated           | VoteService        | YES       |
| vote_closed            | VoteService        | YES       |
| service_call_created   | ServiceCallService | YES       |
| service_call_resolved  | ServiceCallService | YES       |
| service_call_cancelled | ServiceCallService | YES       |
|                        |                    |           |
| translation_final      | TranslationService | YES       |
