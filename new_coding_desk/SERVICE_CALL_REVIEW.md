# ServiceCall 模块代码审查报告

**审查日期**: 2026-06-01
**审查范围**: `backend/services/service_call_service.py`、`backend/models/service_call.py`、`backend/repositories/base.py`、`backend/api/service_calls.py`、`backend/websocket/event_handler.py`
**审查维度**: 状态机正确性 (state_machine)、非法恢复路径 (illegal_recovery)、事件发布正确性 (event_correctness)

---

## 1. 执行摘要

本次审查覆盖 ServiceCall 模块的三个维度，共发现 **13 个真实发现**（0 HIGH, 2 MEDIUM, 11 LOW），**1 个 dismissed（判定为符合设计的正常行为）**。

**整体结论**: ServiceCall 模块的状态机设计和事件发布机制在单线程路径上是正确且完备的。业务规则 C1-C4 在代码层面得到了一致执行，所有三个事件（created/resolved/cancelled）的发布时机、payload 格式和 WebSocket 广播注册均符合 `EVENT_BUS_SPEC` 规范。**核心风险集中在并发场景**: 缺少行级锁或乐观锁导致 `resolve_call` 和 `cancel_call` 之间存在 TOCTOU 竞态条件；模型层缺少 status 字段的数据库级约束（CHECK 约束或 Python Enum），属于防御深度不足。此外，错误码 `SERVICE_CALL_NOT_PENDING` 与 `API_SPEC` 定义的 `SERVICE_CALL_ALREADY_RESOLVED` 不一致。

---

## 2. 按维度分述

### 2.1 状态机正确性 (state_machine)

#### MEDIUM: TOCTOU 竞态条件 —— resolve_call 与 cancel_call 之间无并发保护

**文件**: `backend/services/service_call_service.py:110-153`
**涉及**: `backend/repositories/base.py:47-48, 63-67`、`backend/database.py:28-34`

**问题描述**:

`resolve_call` 和 `cancel_call` 的执行路径均为:
1. `_get_call(call_id)` -- 调用 `BaseRepository.get_by_id()` (`base.py:47-48`)，执行普通 `SELECT`，**无行级锁**
2. `_assert_pending(call)` -- 检查内存中 `call.status != "pending"` (`service_call_service.py:102-108`)
3. `call.status = "resolved"` (或 `"cancelled"`) -- 修改内存属性
4. `self.repo.save(call)` -- 调用 `self.db.commit()` (`base.py:65`)，执行盲目 UPDATE（仅按主键，**无 WHERE 子句限制旧状态**）

FastAPI 的 `Depends(get_db)` 为每个 HTTP 请求创建独立的 `SessionLocal()` (`database.py:28-34`)。两个并发请求使用不同的数据库会话，互不可见对方的未提交写入。

**具体竞态时间线**:
```
T1: 请求A (_get_call)  SELECT ... WHERE id=1 → status="pending"
T2: 请求B (_get_call)  SELECT ... WHERE id=1 → status="pending"
T3: 请求A 通过 _assert_pending → 设置 status="resolved"
T4: 请求A commit() → DB 写入 "resolved"
T5: 请求B 通过 _assert_pending → 设置 status="cancelled"
T6: 请求B commit() → DB 写入 "cancelled"（覆盖了 resolved）
```

**无缓解措施**: 全代码库搜索 `with_for_update`、`FOR UPDATE`、`version_id`、`optimistic` 锁均为零命中。`ServiceCall` 模型没有 `version_id` 列 (`service_call.py:14-23`)。数据库未开启 WAL 模式 (`database.py:16-19`)。

#### MEDIUM: status 字段缺少数据库级约束和 Python Enum 类型

**文件**: `backend/models/service_call.py:21`

**问题描述**: `status` 列定义为 `Column(String(20), nullable=False, default="pending")`，无 `CHECK` 约束，无 `Enum` 类型，无 `@validates` 装饰器。虽然当前服务层代码仅写入 `"pending"`、`"resolved"`、`"cancelled"` 三个合法值，但如果将来有任何代码路径或原始 SQL 写入任意字符串（如 `"foobar"`、`"deleted"`、`"in_progress"`），会无错误地持久化到数据库。

`default="pending"` 仅对新实例生效（SQLAlchemy Column default），对更新不生效。Meeting 模型也存在相同模式，说明这是一个系统性的防御深度缺失。

---

### 2.2 非法恢复路径 (illegal_recovery)

本维度所有发现均为 **LOW** 或 **dismissed**，总体结论：**不存在非法恢复路径**。

#### LOW (确认安全): cancel_call 正确阻止对已解决 (resolved) 调用的取消

`cancel_call()` (`service_call_service.py:141`) 调用 `_assert_pending(call)`，对 `status="resolved"` 的调用必然抛出 `ValidationError`。C3 规则（resolved 不可取消）得到正确执行。

#### LOW (确认安全): resolve_call 正确阻止对已取消 (cancelled) 调用的处理

`resolve_call()` (`service_call_service.py:117`) 同样以 `_assert_pending` 守卫，`status="cancelled"` 的调用无法通过。C1/C2 规则得到正确执行。

#### LOW (确认安全): 无 PUT/PATCH 端点可绕过状态机

`backend/api/service_calls.py` 仅定义了 `POST` 和 `GET` 端点。全代码库搜索 `@router\.(put|patch)` 在所有 `backend/api/*.py` 中返回零匹配。即使存在 PUT/PATCH 端点，也必须经过服务层的 `_assert_pending` 守卫。

#### LOW (确认安全): 无方法可将状态回退为 "pending"

服务层仅有两条单向迁移路径（pending→resolved、pending→cancelled）。代码库中不存在 `restore_call`、`reopen_call` 或任何将状态写回 `"pending"` 的方法。`BaseRepository.save()` 仅从这两个受守卫的服务方法中调用。

#### LOW: BaseRepository.create() 接受未过滤的 kwargs —— 潜在的状态机绕过风险

**文件**: `backend/repositories/base.py:38`

`BaseRepository.create(**kwargs: Any)` 将任意 kwargs 原样传给模型构造函数。`ServiceCall` 模型的 `status` 字段通过 Column default 默认为 `"pending"`，但调用方可通过传入 `status='resolved'` 覆盖。当前唯一调用方 `ServiceCallService.create_call()` 硬编码了 `status="pending"` (`service_call_service.py:66`)，所以当前是安全的。但仓库层没有守卫机制防止未来的调用方绕过生命周期状态机。

#### DISMISSED: create_call 不复用或重新打开已解决/已取消的调用

该发现被判定为 **非问题**。`create_call` 仅在存在 pending 调用时阻止创建，对于已解决/已取消的调用不匹配过滤器，因此创建新记录（新 ID）。这是符合业务规则 C4 的设计行为：已完成的调用不可变且保留历史记录。座位在调用完成后可自由发起新的独立服务请求。

---

### 2.3 事件发布正确性 (event_correctness)

本维度所有发现均为 **LOW**，总体结论：**事件发布机制正确完备**。

#### LOW (确认正确): 三个事件的发布时机均正确

所有三个事件在对应的生命周期方法中发布，且都在业务规则校验通过后、DB commit 成功后:
- `create_call` → `service_call_created` (line 69)
- `resolve_call` → `service_call_resolved` (line 123)
- `cancel_call` → `service_call_cancelled` (line 146)

每个方法的执行顺序为: 校验 → `repo.create()/save()`（内部 commit）→ `event_bus.publish()`。校验失败会抛出异常（`ConflictError` / `NotFoundError` / `ValidationError`），在到达 publish 行之前即传播出去。`EventBus.publish()` 捕获所有 handler 异常且从不重新抛出，一旦到达 publish 行即保证事件分发。

每个方法仅有一个无条件的 publish 调用，无循环、无重试，不可能重复发布。

#### LOW (确认正确): 事件 payload 与 EVENT_BUS_SPEC 完全匹配

- `service_call_created`: `{call_id, seat_id, service_type}` — 匹配 SPEC 第 563-568 行
- `service_call_resolved`: `{call_id}` — 匹配 SPEC 第 595-598 行
- `service_call_cancelled`: `{call_id}` — 匹配 SPEC 第 625-628 行

发布者名称（`ServiceCallService`）和事件名称也完全匹配 SPEC。

#### LOW (确认正确): 三个事件均已注册到 WebSocketEventHandler.BROADCAST_EVENTS

`backend/websocket/event_handler.py:58-60` 包含全部三个 service_call 事件。`register_all()` 类方法（line 116-117）遍历 `BROADCAST_EVENTS` 并逐一订阅。与 `EVENT_BUS_SPEC` 第 14 节矩阵一致。

#### LOW: Commit-before-publish 模式一致但未文档化

所有三个状态变更方法均采用 commit 先于 publish 的策略: `repo.create()/repo.save()`（内部 `db.commit()`）→ `event_bus.publish()`。这避免了 DB 失败时产生虚假事件，是合理的设计选择，但代码注释和文档中未说明此排序决策。

#### LOW: 错误码不一致 —— SERVICE_CALL_NOT_PENDING vs SERVICE_CALL_ALREADY_RESOLVED

**文件**: `backend/services/service_call_service.py:107`

`API_SPEC` 第 11 节第 929 行定义的错误码为 `SERVICE_CALL_ALREADY_RESOLVED`，但 `_assert_pending()` 对 resolved 和 cancelled 两种状态统一抛出 `error_code="SERVICE_CALL_NOT_PENDING"`。路由器 (`api/service_calls.py:106-107, 124-125`) 将此 error_code 原样传给客户端。

这不影响事件发布正确性（`ValidationError` 在 publish 之前抛出，不会产生错误事件），但属于 SPEC 合规性差距。

---

## 3. 严重程度分布

| 严重程度 | 数量 | 占比 |
|---------|------|------|
| HIGH    | 0    | 0%   |
| MEDIUM  | 2    | 15%  |
| LOW     | 11   | 85%  |
| DISMISSED | 1  | -    |

**解读**: 无 HIGH 严重性问题说明不存在可导致数据损坏或系统崩溃的单路径缺陷。两个 MEDIUM 问题分别涉及并发安全（TOCTOU）和防御深度（status 约束），在低并发场景下不容易触发但构成潜在风险。LOW 问题主要为确认性发现和文档改进建议。

---

## 4. 架构合规性评估

| 项目 | 状态 | 说明 |
|------|------|------|
| 仓库层无业务逻辑 | 通过 | `BaseRepository` 仅提供通用 CRUD，无 EventBus/WebSocket 访问 |
| 服务层执行所有业务规则 | 通过 | C1-C4 在 `ServiceCallService` 中集中执行 |
| API 层仅路由和异常转换 | 通过 | Router 仅创建 Service 实例并转换异常为 HTTP 响应 |
| 事件发布在服务层 | 通过 | 三个事件均在 Service 方法中发布，符合 EVENT_BUS_SPEC |
| WebSocket 广播注册 | 通过 | `WebSocketEventHandler.BROADCAST_EVENTS` 包含全部三个事件 |
| SPEC 一致性 | 1 偏差 | 错误码 `SERVICE_CALL_NOT_PENDING` 与 API_SPEC 的 `SERVICE_CALL_ALREADY_RESOLVED` 不一致 |
| 并发安全 | 未通过 | 缺少行级锁或乐观锁保护 `resolve_call` 和 `cancel_call` |

---

## 5. 风险矩阵

| 风险 | 严重程度 | 可能性 | 影响 | 触发条件 |
|------|---------|--------|------|---------|
| 并发 resolve/cancel 竞态导致状态被覆盖 | MEDIUM | 低（当前 SQLite DELETE journal 模式提供部分串行化；切换 WAL 或 PostgreSQL 后可能性升高） | 已被 resolve 的调用被静默覆盖为 cancelled（或反之），终端状态被破坏 | 两个用户/客户端同时对同一 call_id 发送 resolve 和 cancel 请求 |
| 非法 status 值被写入数据库 | MEDIUM | 低（当前代码路径安全，但无守卫阻止未来引入的写入） | status 字段出现不可预期的值，导致业务逻辑异常 | 新增代码路径或原始 SQL 写入未校验的 status 值 |
| 错误码与 SPEC 不一致 | LOW | 确定（每次非 pending 操作都会返回错误的 error_code） | 客户端依赖 SPEC 定义的错误码进行分支处理时行为异常 | 客户端代码硬编码了 `SERVICE_CALL_ALREADY_RESOLVED` 的错误处理逻辑 |
| 仓库层 kwargs 绕过 | LOW | 极低（当前无触发路径） | 新增的仓库调用可创建非 pending 状态的调用，绕过生命周期 | 未来的开发人员直接调用 `repo.create(status='resolved', ...)` |

---

## 6. 推荐修复方案（按优先级排序）

### 6.1 [MEDIUM] 修复 TOCTOU 竞态条件

**方案A（推荐）—— 乐观锁**: 在 `ServiceCall` 模型中添加 `version_id` 列。

```python
# backend/models/service_call.py
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.orm import mapped_column
from backend.database import Base

class ServiceCall(Base):
    __tablename__ = "service_calls"

    id = Column(Integer, primary_key=True, autoincrement=True)
    meeting_id = Column(Integer, ForeignKey("meetings.id"), nullable=False)
    seat_id = Column(Integer, nullable=False)
    service_type = Column(String(50), nullable=False)
    status = Column(String(20), nullable=False, default="pending")
    version_id = Column(Integer, nullable=False, default=1)  # 新增
    created_at = Column(DateTime, default=datetime.utcnow)
    resolved_at = Column(DateTime, nullable=True)

    __mapper_args__ = {"version_id_col": version_id}
```

当两个并发请求尝试更新同一条记录时，第二个 `commit()` 会因为 version 不匹配而抛出 `StaleDataError`，服务层可以捕获并返回 409 Conflict。

**方案B —— 悲观锁**: 在 `ServiceCallRepository` 中添加 `get_by_id_for_update()` 方法，使用 `SELECT ... FOR UPDATE`。（适合高并发场景，但对 SQLite 支持有限。）

### 6.2 [MEDIUM] 添加 status 字段的数据库级约束

```python
# backend/models/service_call.py
from sqlalchemy import CheckConstraint

class ServiceCall(Base):
    __tablename__ = "service_calls"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'resolved', 'cancelled')",
            name="ck_service_call_status",
        ),
    )
    # ... 其余列定义
```

或使用 Python Enum:
```python
import enum
class CallStatus(str, enum.Enum):
    PENDING = "pending"
    RESOLVED = "resolved"
    CANCELLED = "cancelled"

# 模型中
status = Column(Enum(CallStatus), nullable=False, default=CallStatus.PENDING)
```

### 6.3 [LOW] 修复错误码不一致

将 `service_call_service.py:107` 的错误码从 `"SERVICE_CALL_NOT_PENDING"` 改为 `"SERVICE_CALL_ALREADY_RESOLVED"`（匹配 API_SPEC），或者在 API_SPEC 中将定义改为 `SERVICE_CALL_NOT_PENDING`（匹配当前实现）。二选一即可。

### 6.4 [LOW] 在仓库层添加 status 守卫

在 `ServiceCallRepository.create()` 中重写以拦截非 pending 的 status:

```python
class ServiceCallRepository(BaseRepository[ServiceCall]):
    model = ServiceCall

    def create(self, **kwargs: Any) -> ServiceCall:
        if kwargs.get("status", "pending") != "pending":
            raise ValueError("New service calls must have status='pending'")
        return super().create(**kwargs)
```

### 6.5 [LOW] 文档化 commit-before-publish 模式

在 `ServiceCallService` 类文档字符串或方法注释中明确说明: "DB commit 在事件发布之前完成，以确保 DB 失败不产生虚假事件。"

---

## 附录: 审查覆盖范围

```
backend/
├── api/service_calls.py           ← 审查: 端点完整性、异常映射
├── models/service_call.py         ← 审查: 模型定义、约束
├── repositories/base.py           ← 审查: 通用 CRUD、并发安全
├── services/service_call_service.py ← 审查: 业务规则、状态机、事件发布
├── websocket/event_handler.py     ← 审查: 广播注册、消息格式
├── database.py                    ← 审查: session 生命周期
└── exceptions.py                  ← 审查: 异常类型
```
