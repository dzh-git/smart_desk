我建议你不要给 Claude 一次性实现五个 Service。

正确方式是：

```text
一个 Service
↓
实现
↓
审查
↓
修复
↓
下一个 Service
```

否则很容易出现：

```text
Meeting 改了数据库
↓
Seat 依赖旧数据库
↓
Vote 又改接口
↓
最后全部返工
```

下面是我建议的  **Phase 4 全套提示词** 。

---

# Phase 4.1 MeetingService

Phase 4.1 — Implement Meeting Module

参考：

docs/system_architecture.md
docs/API_SPEC.md
docs/DATABASE_SCHEMA.md
docs/EVENT_BUS_SPEC.md
docs/CLAUDE_RULES.md

实现范围：

ORM

Meeting
Agenda
Attendee

Repository

MeetingRepository
AttendeeRepository

Service

MeetingService

Router

meetings.py

---

实现接口：

create_meeting()

list_meetings()

get_meeting()

get_active_meeting()

start_meeting()

end_meeting()

create_agenda()

list_agendas()

delete_agenda()

create_attendee()

list_attendees()

delete_attendee()

---

业务规则：

Rule M1

同一时间仅允许一个 active meeting。

start_meeting() 前必须检查。

---

Rule M2

meeting.status：

pending
active
finished

状态流转：

pending → active → finished

finished 不可回退。

---

Rule M3

start_meeting()

发布：

meeting_started

---

Rule M4

end_meeting()

发布：

meeting_ended

---

禁止：

修改其他模块。

输出：

MEETING_IMPLEMENTATION_REPORT.md

---

# 审查 MeetingService

审查 Meeting Module。

不要修改代码。

检查：

1.Router 是否访问数据库
2.Router 是否访问 Repository
3.Repository 是否存在业务逻辑
4.Service 是否符合 API_SPEC.md
5.Service 是否符合 DATABASE_SCHEMA.md
6.Event 发布是否正确

输出：

MEETING_REVIEW.md

---

# Phase 4.2 SeatService

这是最核心模块。

Phase 4.2 — Implement Seat Module

参考：

docs/system_architecture.md
docs/API_SPEC.md
docs/DATABASE_SCHEMA.md
docs/EVENT_BUS_SPEC.md
docs/CLAUDE_RULES.md

实现：

SeatState ORM

SpeakerSeat ORM

SeatRepository

SeatService

Seat Router

---

状态机：

vacant

occupied_unchecked

checked_in

---

实现：

seat_occupied()

seat_vacant()

check_in()

get_seats()

set_speaker_seat()

clear_speaker_seat()

get_speaker_seat()

---

Rule S1

seat_occupied

vacant
→ occupied_unchecked

发布：

seat_occupied

checkin_prompt

---

Rule S2

check_in

occupied_unchecked
→ checked_in

发布：

check_in

---

Rule S3

seat_vacant

任意状态
→ vacant

发布：

seat_vacant

---

Rule S4

同一时间仅允许一个 Speaker Seat。

设置新 Speaker 时：

自动覆盖旧 Speaker。

---

发布：

seat_occupied

seat_vacant

checkin_prompt

check_in

speaker_seat_set

speaker_seat_clear

---

禁止：

修改其他模块。

输出：

SEAT_IMPLEMENTATION_REPORT.md

---

# 审查 SeatService

审查 Seat Module。

不要修改代码。

重点检查：

1.状态机是否合法

vacant
occupied_unchecked
checked_in

是否存在非法跳转

---

2.是否存在多个 Speaker Seat

---

3.Event 是否正确发布

---

4.Router 是否越层调用

---

输出：

SEAT_REVIEW.md

---

# Phase 4.3 VoteService

这是第二复杂模块。

Phase 4.3 — Implement Vote Module

参考：

所有 docs

实现：

Vote ORM

VoteRecord ORM

VoteRepository

VoteService

Vote Router

---

实现：

create_vote()

get_vote()

list_votes()

cast_vote()

close_vote()

get_statistics()

---

Rule V1

同一时间仅允许一个 open vote。

---

Rule V2

vote.status：

open
closed

---

Rule V3

关闭后禁止投票。

---

Rule V4

attendee_id + vote_id

唯一。

同一 attendee 只能投一次。

---

Rule V5

支持：

is_anonymous

---

发布：

vote_started

vote_updated

vote_closed

---

禁止：

修改其他模块。

输出：

VOTE_IMPLEMENTATION_REPORT.md

---

# 审查 VoteService

审查 Vote Module。

不要修改代码。

重点检查：

1.重复投票

2.关闭后投票

3.多个 open vote

4.统计正确性

5.Event 发布正确性

输出：

VOTE_REVIEW.md

---

# Phase 4.4 ServiceCallService

Phase 4.4 — Implement Service Call Module

实现：

ServiceCall ORM

ServiceCallRepository

ServiceCallService

service_calls.py

---

service_type：

coffee
tea
water
other

---

status：

pending
resolved
cancelled

---

实现：

create_call()

list_calls()

resolve_call()

cancel_call()

---

Rule C1

pending
→ resolved

---

Rule C2

pending
→ cancelled

---

Rule C3

resolved 不可取消

---

Rule C4

cancelled 不可恢复

---

发布：

service_call_created

service_call_resolved

service_call_cancelled

---

禁止：

修改其他模块。

输出：

SERVICE_CALL_IMPLEMENTATION_REPORT.md

---

# 审查 ServiceCallService

审查 Service Call Module。

不要修改代码。

检查：

1.状态机是否合法

2.是否允许非法恢复

3.Event 是否正确

输出：

SERVICE_CALL_REVIEW.md

---

# Phase 4.5 TranslationService

最后做。

因为它后面要迁移旧代码。

Phase 4.5 — Implement Translation Module

参考：

SpeechModule Frozen API

实现：

TranslationRecord ORM

TranslationRepository

TranslationService

translations.py

---

调用接口：

speech.preload()

speech.process_interim(audio, session_key)

speech.process_final(audio, session_key)

speech.reset_interim(session_key)

speech.get_history(meeting_id, seat_id=None)

---

实现：

process_interim()

process_final()

get_history()

reset_session()

---

Rule T1

translation_interim

不发布 Event

不进入 WebSocket

直接 HTTP 返回

---

Rule T2

translation_final

保存数据库

发布：

translation_final

---

Rule T3

历史查询来自：

translation_records

---

禁止：

实现 SpeechModule 内部逻辑

仅调用接口

---

输出：

TRANSLATION_IMPLEMENTATION_REPORT.md

---

# 最后统一审查

五个模块全部完成后：

全项目架构审查。

不要修改代码。

检查：

1.Router → Service → Repository 是否成立

2.Service 是否直接访问 WebSocket

3.Repository 是否包含业务逻辑

4.EventBus 是否符合 EVENT_BUS_SPEC.md

5.WebSocket 是否符合 WEBSOCKET_PROTOCOL.md

6.数据库是否符合 DATABASE_SCHEMA.md

7.API 是否符合 API_SPEC.md

8.是否存在架构违规

输出：

FINAL_ARCHITECTURE_AUDIT.md

按照这个顺序推进，完成五个 Service 后，再进入“迁移旧代码逻辑（SpeechModule、Serial、Translation算法）”阶段。这样风险最低。
