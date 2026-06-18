# Frontend State Spec

本文档冻结 SmartDesk 当前前端状态口径。核心原则：会议生命周期、投票状态、议题状态和主持人端本地 Workspace 必须分层表达。

## 1. 状态分层

### 1.1 `meetingStatus`

| meetingStatus | 含义 |
|---|---|
| `no_meeting` | 没有 active meeting，也没有当前页面可启动的 pending meeting。 |
| `meeting_created` | 当前页面创建了 pending meeting，尚未启动。 |
| `meeting_active` | 会议已启动且未结束。 |
| `meeting_ended` | 会议已结束，前端使用刚结束的 `meetingId` 展示结果。 |

后端会议状态值为 `pending`、`active`、`finished`；`meeting_ended` 是前端用于结果视图的本地状态口径。

### 1.2 `voteStatus`

`voteStatus` 不属于会议阶段。

| voteStatus | 含义 |
|---|---|
| `none` | 没有 open 投票，也没有可展示的最近投票结果。 |
| `open` | 当前会议存在 open 投票。 |
| `closed` | 最近一次投票已关闭，可展示结果。 |

`voting` 等价于 `meeting_active + voteStatus=open`。`voting_closed` 不是核心会议阶段。

### 1.3 `agendaStatus`

| agendaStatus | 含义 |
|---|---|
| `pending` | 未开始。 |
| `active` | 当前正在讨论。 |
| `completed` | 已完成。 |
| `skipped` | 已跳过。 |

允许转换：

- `pending -> active`
- `skipped -> active`
- `active -> completed`
- `active -> skipped`
- `active -> completed + next pending -> active`

禁止转换：

- `completed -> active`
- `completed -> skipped`
- `pending -> completed`
- `pending -> skipped`
- `skipped -> completed`
- `active -> pending`

规则：

- 同一 meeting 最多一个 active agenda。
- `complete` 和 `skip` 只能作用于当前 active agenda。
- `advance` 必须已有 active agenda。
- `set-current` 可把 pending/skipped 议题设为 current；completed 第一版不可重开。
- 已有 active 时切换 current agenda，前端先确认；后端调用成功后旧 active 自动 completed，新议题 active。

Agenda progress 由 `Agenda[]` 推导：

- `current_agenda` 是唯一 active agenda，否则为 `null`。
- `current_index` 是 current agenda 按 `sort_order` 排序后的 1-based index。
- `agendaFlowDone = total > 0 && active == 0 && pending == 0`。

### 1.4 `AdminWorkspace`

`AdminWorkspace` 是主持人端本地内容分组，不是会议阶段。

| AdminWorkspace | active meeting 下显示 |
|---|---|
| `overview` | 会议控制、会议桌、发言席、参会人。 |
| `agenda_vote` | Agenda Command Center、创建投票、投票面板、投票结果。 |
| `service_records` | 服务请求、会议记录。 |

存储规则：

- 只保存在 React state。
- 默认值是 `overview`。
- 刷新页面后回到 `overview`。
- 不写 `localStorage/sessionStorage`。
- 不写 URL。
- 不发 API 或 WebSocket。
- 不影响 `/seat/:seatId` 和 `/display`。

旧的 `Current Phase`、`General`、`Agenda Discussion`、`uiPhase` 已移除。

## 2. 页面状态显示

### `no_meeting`

| 端 | 显示 | 可点击 |
|---|---|---|
| 主持人端 | 无 active meeting；创建会议表单。 | `Create Pending Meeting`、`Refresh`。 |
| 座位端 | 等待会议。 | `Refresh`；demo 模式可返回主持人端。 |
| 大屏端 | 等待会议或无投票状态；低频检查新的 active meeting。 | `Refresh`。 |

### `meeting_created`

| 端 | 显示 | 可点击 |
|---|---|---|
| 主持人端 | 当前页面创建的 pending meeting。 | `Start Meeting`、`Refresh`。 |
| 座位端 | 等待会议开始。 | `Refresh`。 |
| 大屏端 | 等待会议开始。 | `Refresh`。 |

当前不支持刷新后选择已有 pending meeting；会议列表 deferred。

### `meeting_active`

| 端 | 显示 | 可点击 |
|---|---|---|
| 主持人端 | Workspace 控制台；会议总览、议程投票、服务记录按 Workspace 分组。 | 会议结束、发言席、参会人、议程控制、投票、服务处理、Workspace 切换。 |
| 座位端 | 座位状态、当前议题只读卡片、投票、服务、语音、字幕。 | 满足条件时签到、投票、服务呼叫、语音。 |
| 大屏端 | 会议标题、当前议题、议程进度、当前或最近投票结果。 | `Refresh`。 |

投票规则：

- `voteStatus=none` 或 `closed` 时，主持人可创建投票。
- `voteStatus=open` 时，主持人可关闭投票，不能创建第二个 open 投票。
- 投票关闭后，主持人端和大屏端保留投票结果。

议程规则：

- 主持人端是唯一议程控制端。
- 座位端和大屏端只读展示当前议题和进度。
- 三端收到 `agenda_updated` 后重新拉取 agendas。

### `meeting_ended`

| 端 | 显示 | 可点击 |
|---|---|---|
| 主持人端 | 会议已结束、最终议程进度、投票结果、字幕记录、服务历史。 | `Refresh`、查看结果、创建下一场会议。 |
| 座位端 | 会议结束或等待下一场会议。 | `Refresh`。 |
| 大屏端 | 会议已结束、最终议程进度、最近投票结果。 | `Refresh`。 |

结束后写操作禁用或隐藏：

- `End Meeting`
- `Create Vote`
- `Close Vote`
- `Set Speaker`
- `Clear Speaker`
- 参会人新增/删除
- 议程新增/删除/推进/完成/跳过
- `Resolve`
- 座位端签到、投票、服务呼叫、语音上传

## 3. 状态切换

| 触发 | API / WS | 结果 |
|---|---|---|
| 创建会议 | `POST /api/meetings` | `meeting_created`。 |
| 启动会议 | `POST /api/meetings/{id}/start` / `meeting_started` | `meeting_active`。 |
| 结束会议 | `POST /api/meetings/{id}/end` / `meeting_ended` | `meeting_ended`，保存 `endedMeetingId`。 |
| 创建投票 | `POST /api/votes` / `vote_started` | `voteStatus=open`。 |
| 座位投票 | `POST /api/votes/{id}/submit` / `vote_updated` | 保持 `voteStatus=open` 并刷新统计。 |
| 关闭投票 | `POST /api/votes/{id}/close` / `vote_closed` | `voteStatus=closed`。 |
| 议程变更 | Agenda HTTP API / `agenda_updated` | 重新拉取 `Agenda[]` 并推导 current/progress。 |
| Workspace 切换 | 前端本地 state | 只改变 `/admin` 可见内容。 |

## 4. 按钮规则

| 按钮 | 启用条件 | 禁用条件 |
|---|---|---|
| `Create Pending Meeting` | `no_meeting` 或 `meeting_ended`，标题非空。 | 已有 active meeting；请求中。 |
| `Start Meeting` | 当前页面存在 pending meeting。 | 无 pending meeting；请求中。 |
| `End Meeting` | `meeting_active`。 | 无 active meeting；会议已结束。 |
| Workspace 切换 | `meeting_active`。 | `no_meeting`、`meeting_created`、`meeting_ended` 结果视图不依赖 Workspace。 |
| `Create Vote` | `meeting_active` 且 `voteStatus!=open`。 | 无 active meeting；open 投票存在；会议结束。 |
| `Close Vote` | `meeting_active` 且 `voteStatus=open`。 | 无 open 投票；会议结束。 |
| 发言席控制 | `meeting_active`。 | 会议结束；请求中。 |
| 参会人新增/删除 | `meeting_active`。 | 会议结束；请求中。 |
| 议程新增/删除 | `meeting_active`；删除目标不是 active。 | 会议结束；active agenda。 |
| `Set Current` | `meeting_active`，目标是 pending/skipped。 | completed；会议结束；请求中。 |
| `Advance` | `meeting_active` 且存在 active agenda。 | 无 active agenda；会议结束；请求中。 |
| `Complete` | `meeting_active` 且目标是 current active agenda。 | 目标不是 active；会议结束；请求中。 |
| `Skip` | `meeting_active` 且目标是 current active agenda；前端二次确认。 | 目标不是 active；会议结束；请求中。 |
| `Confirm Check-in` | active meeting、座位已占用未签到、已选参会人、WS connected。 | 无 active meeting；未选参会人；WS disconnected。 |
| 座位投票提交 | active meeting、open 投票、已签到、已选项、WS connected。 | 投票关闭；未签到；未选项；WS disconnected。 |
| 服务呼叫 | active meeting、已签到、无 pending 请求、WS connected。 | 会议结束；未签到；已有 pending 请求。 |
| 语音 `Start` | 当前座位是发言席、已签到、active meeting、WS connected、模型 ready、浏览器支持麦克风。 | 非发言席；未签到；会议结束；模型未 ready。 |
| 大屏 `Refresh` | 始终可点击。 | 无。 |

## 5. 会议结束数据来源

- 主持人点击 `End Meeting` 成功后，保存刚结束的 `meetingId` 为 `endedMeetingId`。
- 大屏收到 `meeting_ended` 时，也保存当前 `meetingId` 为 `endedMeetingId`。
- `endedMeetingId` 至少保存在 React state；刷新恢复可使用 `sessionStorage`。
- 会议结束结果不能只依赖 `GET /api/meetings/active`。
- 主持人端使用 `endedMeetingId` 拉取：
  - `GET /api/votes?meeting_id={endedMeetingId}`
  - `GET /api/translations?meeting_id={endedMeetingId}`
  - `GET /api/service-calls?meeting_id={endedMeetingId}`
  - `GET /api/meetings/{endedMeetingId}/agendas`
- 大屏端使用 `endedMeetingId` 保留最近投票结果和最终议程进度。

## 6. 字幕规则

- 主持人端：全会议公开字幕历史，`fetchTranslations(meetingId)`。
- 座位端：全会议公开字幕历史，`fetchTranslations(meetingId)`，默认不传 `seat_id`。
- API client 保留 `fetchTranslations(meetingId, seatId?)` 可选能力。
- 大屏端字幕展示 deferred。
- 历史字幕按 `created_at` 升序；同时间按 `id` 升序。

## 7. Deferred

- 会议列表和选择已有会议。
- 刷新后恢复 pending meeting。
- 完整议题编辑器：英文标题、预计时长、目标说明、跳过原因、重开 completed。
- 大屏字幕和当前发言人展示。
- 主持人控制大屏。
- 参会人编辑。
- 主持人手动分配参会人到座位。
- 投票 draft/publish/archive/reopen。
- 真实认证和权限系统。
- 服务请求 accepted/processing。
