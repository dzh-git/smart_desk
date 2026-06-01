# SmartDesk System Architecture

Version: 1.0
Status: Architecture Baseline
Last Updated: 2026-06-01

---

# 1. Project Overview

SmartDesk 是一个面向会议场景的智能会议桌系统。

系统由：

* 10 个智能座位（Arduino + TOF + LED）
* 11 个平板终端（10座位 + 1管理台）
* NUC 中央服务器
* Speech Module（ASR + Translation）

组成。

核心能力：

* 自动入座检测
* 签到管理
* 发言席管理
* 实时语音识别
* 实时双语翻译
* 投票管理
* 服务呼叫
* WebSocket 实时同步

---

# 2. Architecture Principles

## P1. 单一职责

每个模块只负责一类业务。

禁止：

* 一个模块同时负责业务和通信
* 一个模块同时负责数据库和WebSocket

---

## P2. Service First

所有业务逻辑必须位于 Service 层。

禁止：

Router 直接操作数据库。

错误：

```python
@router.post(...)
db.add(...)
```

正确：

```python
@router.post(...)
meeting_service.create(...)
```

---

## P3. Repository Isolation

数据库只能通过 Repository 访问。

禁止：

```python
session.query(...)
```

散落在各个 Service 中。

---

## P4. Event Driven

模块之间通过 EventBus 通信。

禁止：

```python
seat_service
    ↓
直接调用
    ↓
ws_service
```

正确：

```text
seat_service
    ↓
SeatOccupiedEvent
    ↓
EventBus
    ↓
ws_service
```

---

## P5. Speech Module Independence

SpeechModule 必须保持独立。

允许：

```python
speech.process_final(...)
```

禁止：

SpeechModule 导入：

* FastAPI
* WebSocket
* Arduino
* Vue

---

# 3. System Architecture

```text
                    ┌────────────────┐
                    │   Frontend     │
                    │ Vue + Vite     │
                    └───────┬────────┘
                            │
                  HTTP      │      WebSocket
                            │
┌───────────────────────────▼─────────────────────────┐
│                    FastAPI                          │
│                                                     │
│ Router → Service → Repository → SQLite              │
│            ↓                                        │
│         EventBus                                    │
└────────────┬───────────────────────────────┬────────┘
             │                               │
             │                               │
             ▼                               ▼

      SpeechModule                    Hardware Layer
      (ASR + MT)                 Arduino + TOF + LED
```

---

# 4. Module Responsibilities

## 4.1 Router Layer

目录：

```text
backend/api/
```

职责：

* 参数校验
* 调用 Service
* 返回响应

禁止：

* 数据库操作
* WebSocket操作
* 业务逻辑

---

## 4.2 Service Layer

目录：

```text
backend/services/
```

职责：

实现全部业务逻辑。

包含：

```text
MeetingService
SeatService
VoteService
ServiceCallService
TranslationService
DashboardService
```

---

### MeetingService

负责：

* 创建会议
* 结束会议
* 议程管理
* 参会者管理

---

### SeatService

负责：

* 入座
* 离座
* 签到
* 发言席管理

---

### VoteService

负责：

* 发起投票
* 投票统计
* 关闭投票

---

### ServiceCallService

负责：

* 茶
* 水
* 咖啡
* 其他服务

---

### TranslationService

负责：

* 调用 SpeechModule
* 翻译结果持久化
* 发布翻译事件

---

### DashboardService

负责：

* 聚合管理员首页数据
* meeting
* speaker seat
* active vote
* service calls
* seats

用于：

```http
GET /api/dashboard
```

---

## 4.3 Repository Layer

目录：

```text
backend/repositories/
```

职责：

唯一数据库访问入口。

包含：

```text
MeetingRepository
VoteRepository
AttendeeRepository
ServiceCallRepository
TranslationRepository
```

禁止：

业务逻辑。

---

## 4.4 EventBus

目录：

```text
backend/events/
```

职责：

模块解耦。

统一事件发布中心。

---

事件示例：

```python
SeatOccupiedEvent
SeatVacatedEvent

MeetingStartedEvent
MeetingEndedEvent

VoteStartedEvent
VoteUpdatedEvent
VoteClosedEvent

TranslationFinalEvent

ServiceCallCreatedEvent
```

说明：

```text
seat_occupied
由 SeatService 发布

HardwareService 不发布业务事件
```

---

## 4.5 WebSocket Layer

目录：

```text
backend/websocket/
```

职责：

* 房间管理
* 客户端连接管理
* 广播消息

禁止：

业务逻辑。

---

## 4.6 Hardware Layer

目录：

```text
backend/hardware/
```

职责：

* 串口管理
* Arduino通信
* LED控制

禁止：

数据库操作。

禁止：

WebSocket操作。

---

## 4.7 Speech Module

目录：

```text
speech_module/
```

职责：

* VAD
* Streaming ASR
* Offline ASR
* Translation
* History

必须可以独立运行：

```bash
python tests/test_dataset.py
```

不依赖：

* FastAPI
* WebSocket
* Arduino

---

# 5. Data Flow

## Seat Check-in

```text
TOF
↓
HardwareService
↓
SeatService
↓
seat_occupied
↓
EventBus
↓
WebSocket

SeatService
↓
checkin_prompt
↓
EventBus
↓
WebSocket
↓
Tablet
```

说明：

```text
seat_occupied
=
物理状态变化事件

checkin_prompt
=
业务提示事件

二者必须分离
```

---

## Translation Flow

```text
Browser Audio
↓
Translation API
↓
TranslationService
↓
SpeechModule
↓
TranslationFinalEvent
↓
WebSocket
↓
All Tablets
```

---

## Vote Flow

```text
Admin
↓
Vote API
↓
VoteService
↓
VoteStartedEvent
↓
WebSocket
↓
All Tablets
```

---

# 6. Dependency Rules

允许：

```text
Router
 ↓
Service
 ↓
Repository
```

允许：

```text
Service
 ↓
EventBus
```

允许：

```text
TranslationService
 ↓
SpeechModule
```

---

禁止：

```text
Router
 ↓
Repository
```

---

禁止：

```text
Repository
 ↓
Service
```

---

禁止：

```text
SpeechModule
 ↓
FastAPI
```

---

禁止：

```text
SpeechModule
 ↓
WebSocket
```

---

禁止：

```text
Hardware
 ↓
Database
```

---

# 7. Public Interfaces

系统对外仅暴露：

## HTTP API

```text
/api/meetings
/api/checkin
/api/votes
/api/service-calls
/api/translate
```

---

## WebSocket

```text
/ws/{meeting_id}
```

---

## SpeechModule

```python
preload()

process_interim(
    audio,
    session_key
)

process_final(
    audio,
    session_key
)

reset_interim(
    session_key
)

get_history(
    meeting_id,
    seat_id=None
)
```

---

# 8. Testing Strategy

每个模块必须能够独立测试。

---

SpeechModule：

```bash
pytest speech_module/tests
```

---

VoteService：

```bash
pytest tests/test_vote_service.py
```

---

SeatService：

```bash
pytest tests/test_seat_service.py
```

---

WebSocket：

```bash
pytest tests/test_ws.py
```

---

Hardware：

```bash
pytest tests/test_serial.py
```

---

# 9. Claude Code Development Rules

Claude Code 每次修改范围不得超过一个模块。

推荐：

```text
仅修改：

speech_module/sentence_merge.py

目标：

解决重复句问题

禁止修改其他文件
```

---

禁止：

```text
修复整个项目
```

---

新增功能必须遵守：

```text
新增 Service
↓
新增 Event
↓
新增 API
```

流程。

禁止跨层直接修改。

---

# 10. Versioning

V1 Scope:

* 10座位
* 单会议实时运行
* 中文↔英文翻译
* 投票
* 服务呼叫
* 翻译历史

不包含：

* TTS
* 会议录音回放
* 多会议并发
* 多发言人同时识别
* 云端部署

1.Seat 状态机状态修改为：vacant、occupied_unchecked、checked_in。 2.同一时间仅允许一个Speaker Seat。 3.只允许投一次。 4.Service Call状态机增加cancelled。 5.Translation记录表补充：translation_records、id、meeting_id
seat_id、source_lang、target_lang、source_text、translated_text、created_at。 6.全部使用：attendee_id 作为业务主键。

Architecture Freeze:

除重大问题外，不允许修改本文件定义的模块边界。
