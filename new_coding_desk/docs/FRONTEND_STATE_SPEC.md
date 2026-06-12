# Frontend State Spec

本文档冻结 SmartDesk 前端页面状态机口径。它区分当前已经实现的事实、下一轮必须实现的目标、以及 deferred 功能。本文档只描述前端状态，不要求修改后端协议。

## 1. 状态分层

前端状态必须分为三层，不再把投票结束当作核心会议阶段。

### 1.1 Meeting Status

`meetingStatus` 表示会议生命周期，只包含会议本身的阶段：

| meetingStatus | 含义 | 当前事实 |
|---|---|---|
| `no_meeting` | 没有活动会议，也没有当前页面可操作的 pending 会议。 | 已实现。 |
| `meeting_created` | 当前页面创建了 pending 会议，但还未开始。 | 已实现，但只保存在当前页面 state，刷新后丢失。 |
| `meeting_active` | 会议已开始且未结束。 | 已实现。 |
| `meeting_ended` | 会议已结束，进入结果查看阶段。 | 后端支持 finished；前端下一轮必须补齐结果保留视图。 |

### 1.2 Vote Status

`voteStatus` 独立于 `meetingStatus`：

| voteStatus | 含义 | 当前事实 |
|---|---|---|
| `none` | 当前会议没有 open 投票，也没有可展示的最近投票结果。 | 已实现为空状态。 |
| `open` | 当前存在 open 投票。 | 已实现。 |
| `closed` | 最近一次投票已关闭，可展示结果。 | 已实现投票结果展示。 |

说明：

- 原先文档里的 `voting` 应理解为 `meetingStatus=meeting_active` 且 `voteStatus=open`。
- 原先文档里的 `voting_closed` 不是核心会议阶段，应理解为 `meetingStatus=meeting_active` 且 `voteStatus=closed`。
- 投票关闭后会议仍然是 `meeting_active`，除非主持人结束会议。

### 1.3 Optional UI Phase

`uiPhase` 是主持人端下一轮可选的 UI 阶段，不等同于后端会议状态：

| uiPhase | 含义 | 范围 |
|---|---|---|
| `general` | 默认会议进行阶段。 | 下一轮必须实现阶段选择入口。 |
| `agenda_discussion` | 主持人选择“议程讨论”视图或阶段。 | 下一轮可选 UI 阶段，只要求选择和展示阶段标签，不要求完整当前议题系统。 |

#### 存储规则

- `uiPhase` 只作为主持人端本地 UI 状态。
- 只支持 `general` 和 `agenda_discussion`。
- 不写入后端。
- 不通过 WebSocket 广播。
- 不影响座位端和大屏端。
- 刷新页面后默认回到 `general`。
- 不实现完整当前议题系统。

说明：

- `agenda_discussion` 不要求实现当前议题选择、议题推进、完成/跳过、排序系统。
- 大屏当前议题展示继续 deferred。

## 2. 状态显示规则

### `meetingStatus=no_meeting`

| 端 | 当前/目标显示 | 可点击 | 禁用或不显示 |
|---|---|---|---|
| 主持人端 | 无活动会议提示、创建会议表单。 | `Create Pending Meeting`、`Refresh`。 | `Start Meeting`、`End Meeting`、投票、服务处理、发言席控制、参会人/议程管理。 |
| 座位端 | `Waiting for Meeting`。 | `Refresh`；demo 模式可返回主持人端。 | 签到、投票、服务呼叫、语音。 |
| 大屏端 | 等待会议或无投票结果。 | `Refresh`。 | 当前议题、发言人、字幕、投票结果。 |

切换：

- `Create Pending Meeting` 成功调用 `POST /api/meetings` 后，进入 `meeting_created`。
- 刷新发现 active meeting 时，进入 `meeting_active`。

### `meetingStatus=meeting_created`

| 端 | 当前/目标显示 | 可点击 | 禁用或不显示 |
|---|---|---|---|
| 主持人端 | 当前页面刚创建的 pending 会议和启动入口。 | `Start Meeting`、`Refresh`。 | `End Meeting`、投票、服务处理、发言席控制。 |
| 座位端 | 等待会议开始。 | `Refresh`。 | 签到、投票、服务呼叫、语音。 |
| 大屏端 | 等待会议开始。 | `Refresh`。 | 当前议题、发言人、字幕、投票结果。 |

切换：

- `Start Meeting` 成功调用 `POST /api/meetings/{meeting_id}/start` 后，进入 `meeting_active`。
- 其他端收到 `meeting_started` WebSocket 事件后重新拉取 active meeting，进入 `meeting_active`。

当前事实：

- 主持人端不能选择已有 pending 会议；会议列表和选择已有会议 deferred。

### `meetingStatus=meeting_active`, `voteStatus=none`

| 端 | 当前/目标显示 | 可点击 | 禁用或不显示 |
|---|---|---|---|
| 主持人端 | 会议概览、座位、参会人、议程、服务请求、字幕、投票创建入口、会议结果区域。 | `End Meeting`、发言席控制、参会人/议程新增删除、`Create Vote`、`Resolve`、`Refresh`。下一轮必须提供会议阶段选择。 | `Start Meeting`、`Close Vote`。 |
| 座位端 | 座位状态、签到区、服务区、字幕区；已签到后允许服务呼叫。 | `Confirm Check-in`、服务呼叫、demo 占座/离座、发言席语音。 | 投票提交。 |
| 大屏端 | 会议标题；无投票时显示无投票状态。 | `Refresh`。 | 当前议题、发言人、字幕展示 deferred。 |

切换：

- 主持人点击 `Create Vote`，调用 `POST /api/votes` 成功后，`voteStatus=open`。
- 收到 `vote_started` 后，`voteStatus=open`。
- 主持人点击 `End Meeting`，调用 `POST /api/meetings/{meeting_id}/end` 成功后，`meetingStatus=meeting_ended`。
- 收到 `meeting_ended` 后，`meetingStatus=meeting_ended`。

下一轮目标：

- 主持人端必须能选择当前 UI 阶段：`general` 或 `agenda_discussion`。
- 阶段选择只影响前端展示，不新增后端会议阶段。

### `meetingStatus=meeting_active`, `uiPhase=agenda_discussion`

| 端 | 当前/目标显示 | 可点击 | 禁用或不显示 |
|---|---|---|---|
| 主持人端 | 议程列表和“议程讨论”阶段标签。 | 阶段选择、`Create Vote`、`End Meeting`、发言席控制、参会人/议程新增删除。 | `Start Meeting`。 |
| 座位端 | 会议进行中状态、座位状态、字幕。 | 签到、服务呼叫、发言席语音。 | 专门议程展示当前 deferred；无 open 投票时不显示投票提交。 |
| 大屏端 | 会议标题。 | `Refresh`。 | 当前议题、发言人、字幕展示继续 deferred。 |

说明：

- 下一轮只要求主持人端可选择并显示 `agenda_discussion` 阶段。
- 不要求完整“当前议题系统”。

### `meetingStatus=meeting_active`, `voteStatus=open`

| 端 | 当前/目标显示 | 可点击 | 禁用或不显示 |
|---|---|---|---|
| 主持人端 | 当前 open 投票、实时统计、关闭投票入口、会议概览、座位、服务、字幕。 | `Close Vote`、`End Meeting`、`Resolve`、发言席控制、`Refresh`。 | `Create Vote` 不显示或禁用。 |
| 座位端 | 当前 open 投票、选项、已投状态、统计、服务呼叫、字幕。 | 已签到座位可选投票项并 `Submit Vote` 或 `Update Vote`；服务呼叫；发言席语音。 | 未签到不能投票；未选项不能提交；WS 断开时写操作禁用。 |
| 大屏端 | 会议标题、当前投票标题、选项票数和百分比。 | `Refresh`。 | 当前议题、发言人、字幕展示继续 deferred。 |

切换：

- 座位端提交或更新投票调用 `POST /api/votes/{vote_id}/submit`，仍保持 `voteStatus=open`，并刷新统计。
- 收到 `vote_updated` 后保持 `voteStatus=open` 并刷新统计。
- 主持人点击 `Close Vote` 调用 `POST /api/votes/{vote_id}/close` 成功后，`voteStatus=closed`。
- 收到 `vote_closed` 后，`voteStatus=closed`。
- 结束会议后，`meetingStatus=meeting_ended`。

### `meetingStatus=meeting_active`, `voteStatus=closed`

| 端 | 当前/目标显示 | 可点击 | 禁用或不显示 |
|---|---|---|---|
| 主持人端 | 最近关闭投票结果、会议结果区域、可创建新投票入口。 | `Create Vote`、`End Meeting`、阶段选择、服务处理、发言席控制、`Refresh`。 | `Close Vote`。 |
| 座位端 | 最近关闭投票结果；如果能识别本人投票则显示本人选择。 | 服务呼叫、发言席语音、`Refresh`。 | 投票提交/更新。 |
| 大屏端 | 最近关闭投票结果。 | `Refresh`。 | 当前议题、发言人、字幕展示继续 deferred。 |

特别规则：

- 投票结束后，主持人端必须能看到投票结果。
- 投票结束后，大屏端必须能看到投票结果。
- 结果不能因为没有 open 投票而消失。

### `meetingStatus=meeting_ended`

| 端 | 当前/目标显示 | 可点击 | 禁用或不显示 |
|---|---|---|---|
| 主持人端 | 会议已结束状态、会议结果、历史投票结果、最终字幕记录、服务请求历史。 | `Refresh`、查看结果；可创建下一场会议。 | `End Meeting`、`Create Vote`、`Close Vote`、发言席控制、参会人/议程编辑、服务处理。 |
| 座位端 | 会议结束或等待下一场会议状态。 | `Refresh`。 | 签到、投票、服务呼叫、语音上传。 |
| 大屏端 | 会议结束状态；保留最近投票结果。 | `Refresh`。 | 当前议题、发言人、字幕展示继续 deferred。 |

会议结束后的结果数据来源（`endedMeetingId` 存储规则）：

- 主持人端点击 `End Meeting` 成功后，必须保存刚结束的 `meetingId` 为 `endedMeetingId`。
- 收到 `meeting_ended` WebSocket 事件时，也必须保存当前 `meetingId` 为 `endedMeetingId`。
- `endedMeetingId` 至少保存在 React state。
- 为了刷新后仍能查看刚结束会议结果，建议同步写入 `sessionStorage`。
- 进入 `meeting_ended` 后，主持人端不得只依赖 `GET /api/meetings/active`。
- 主持人端必须使用 `endedMeetingId` 拉取：
  - `GET /api/votes?meeting_id={endedMeetingId}` 和各投票 statistics；
  - `GET /api/translations?meeting_id={endedMeetingId}`；
  - `GET /api/service-calls?meeting_id={endedMeetingId}`。
- 大屏端（DisplayView）在收到 `meeting_ended` WebSocket 事件时，应保存当前 `meetingId` 为 `endedMeetingId`。
- 会议结束后，大屏端继续用该 `endedMeetingId` 拉取最近投票结果。
- 如果大屏页面是在会议结束后才打开，自动查找历史会议暂时 deferred。
- 如果会议结束时有 open 投票，后端会关闭该投票；前端必须刷新并展示关闭后的结果。

## 3. 状态切换表

| 来源状态 | 触发 | API / WebSocket | 目标状态 |
|---|---|---|---|
| `no_meeting` | `Create Pending Meeting` | `POST /api/meetings` | `meeting_created` |
| `meeting_created` | `Start Meeting` | `POST /api/meetings/{meeting_id}/start` | `meeting_active`, `voteStatus=none` |
| 任意端 | 会议开始事件 | `meeting_started` WS | `meeting_active`, `voteStatus` 重新拉取 |
| `meeting_active` | 主持人选择 `agenda_discussion` | 前端 UI 阶段选择 | `meeting_active`, `uiPhase=agenda_discussion` |
| `meeting_active` | 主持人选择 `general` | 前端 UI 阶段选择 | `meeting_active`, `uiPhase=general` |
| `meeting_active`, `voteStatus!=open` | `Create Vote` | `POST /api/votes` | `meeting_active`, `voteStatus=open` |
| 任意 active 状态 | 投票开始事件 | `vote_started` WS | `meeting_active`, `voteStatus=open` |
| `voteStatus=open` | 座位提交或更新投票 | `POST /api/votes/{vote_id}/submit`, `vote_updated` WS | `meeting_active`, `voteStatus=open` |
| `voteStatus=open` | `Close Vote` | `POST /api/votes/{vote_id}/close` | `meeting_active`, `voteStatus=closed` |
| 任意 active 状态 | 投票关闭事件 | `vote_closed` WS | `meeting_active`, `voteStatus=closed` |
| 任意 active 状态 | `End Meeting` | `POST /api/meetings/{meeting_id}/end` | `meeting_ended`，保存 `endedMeetingId`（React state + sessionStorage） |
| 任意 active 状态 | 会议结束事件 | `meeting_ended` WS | `meeting_ended`，保存 `endedMeetingId`（React state；大屏端也保存） |
| `meeting_ended` | 创建下一场会议 | `POST /api/meetings` | `meeting_created` |

## 4. 通用按钮规则

| 按钮 | 启用条件 | 禁用条件 |
|---|---|---|
| `Create Pending Meeting` | `no_meeting` 或 `meeting_ended`，标题非空。 | 已有 active 会议；请求处理中。 |
| `Start Meeting` | `meeting_created`，有 pending `meetingId`。 | 无 pending meeting；请求处理中。 |
| `End Meeting` | `meeting_active`。 | `no_meeting`、`meeting_created`、`meeting_ended`。 |
| 阶段选择 | `meeting_active`。 | `no_meeting`、`meeting_created`、`meeting_ended`。 |
| `Create Vote` | `meeting_active` 且 `voteStatus!=open`。 | `voteStatus=open`；无会议；会议已结束。 |
| `Close Vote` | `meeting_active` 且 `voteStatus=open`。 | 无 open 投票。 |
| 发言席控制 | `meeting_active`。 | 无 active 会议；会议已结束；请求处理中。 |
| 参会人/议程新增删除 | `meeting_active`。 | 无 active 会议；会议已结束；请求处理中。 |
| `Confirm Check-in` | active 会议、座位已占用未签到、已选择参会人、WS connected。 | 无会议、会议未开始或已结束、未选择参会人、WS disconnected。 |
| 座位投票提交 | `meeting_active`、`voteStatus=open`、座位已签到、已选择选项、WS connected。 | 投票关闭、未签到、未选项、WS disconnected。 |
| 服务呼叫 | `meeting_active`、座位已签到、无 pending 服务请求、WS connected。 | 未签到、会议结束、已有 pending 请求、WS disconnected。 |
| 语音 `Start` | 当前座位为发言席、已签到、会议 active、WS connected、语音模型 ready、浏览器支持麦克风。 | 非发言席、未签到、会议结束、模型未 ready、WS disconnected。 |
| 大屏 `Refresh` | 始终可点击。 | 无。 |

## 5. 字幕范围规则

### 当前规则（Task 7 确定）

- **主持人端**：字幕记录为全会议公开字幕历史，拉取时不传 `seat_id`（`fetchTranslations(meetingId)`）。
- **座位端**：字幕记录为全会议公开字幕历史，拉取时不传 `seat_id`（`fetchTranslations(meetingId)`），**不按当前座位过滤**。
- **大屏端**：字幕展示继续 deferred（本轮不实现）。
- **API client 可选能力**：`fetchTranslations(meetingId, seatId?)` 的 `seatId` 参数作为可选能力保留，座位端默认不传。如需按座位过滤，调用方主动传入 `seatId`。
- **后端子记录来源**：后端 `/api/translations` 支持 `meeting_id` 必选参数和 `seat_id` 可选参数。前端默认只传 `meeting_id`。
- **WebSocket 广播**：`translation_interim`、`translation_final`、`translation_interim_cancelled` 按 meeting room 广播，不按 seat 过滤。前端在收到广播后按 utterance_id 更新本地 interim 状态，并通过 HTTP 拉取刷新 final 记录。

### UI 排序规则

- 历史字幕按 `created_at` 升序排列（时间早的在上）。
- `created_at` 相同时按 `id` 升序作为 tie-breaker。
- 不使用 `reverse()`。排序逻辑在 `TranscriptPanel.tsx` 的 `sortFinalsOldestFirst()` 函数中。

### 历史变更说明

- Task 6 曾实现「座位端字幕按 seat 过滤」，座位端默认拉取 `/api/translations?meeting_id=...&seat_id=N`。
- Task 7 将此行为修正为「全会议公开字幕历史」，座位端默认拉取 `/api/translations?meeting_id=...`（不含 `seat_id`）。

## 6. 已实现、下一轮目标、Deferred

### 当前已经实现的事实

- 活动会议、座位、发言席、投票、服务、字幕、议程、参会人基础读取。
- 创建 pending 会议、启动当前页面创建的 pending 会议、结束 active 会议。
- 创建/关闭投票，投票关闭后主持人端和大屏端可展示结果。
- 座位签到、投票、服务呼叫、发言席语音上传。
- 大屏展示会议标题和当前/最近投票结果。

### 下一轮必须实现的目标

- 主持人端必须提供当前 UI 阶段选择能力，至少支持 `general` 和 `agenda_discussion`。
- `uiPhase` 只作为主持人端本地 UI 状态，不写入后端、不通过 WebSocket 广播、不影响座位端和大屏端；刷新页面后默认回到 `general`。
- `agenda_discussion` 只作为 UI 阶段，不要求完整当前议题系统。
- 会议结束后，前端必须保存刚结束的 `meetingId` 为 `endedMeetingId`。
- `endedMeetingId` 至少保存在 React state，建议同步写入 `sessionStorage`。
- 主持人端在 `meeting_ended` 下必须使用 `endedMeetingId` 拉取投票结果、字幕记录、服务请求历史，不能只依赖 active meeting。
- 大屏端（DisplayView）在收到 `meeting_ended` WS 事件时必须保存 `endedMeetingId`，并继续用其拉取最近投票结果。
- 如果大屏页面是在会议结束后才打开，自动查找历史会议暂时 deferred。

### Deferred

- 会议列表和选择已有会议。
- 启动刷新前已经存在的 pending meeting。
- 完整当前议题系统：当前议题选择、推进、完成、跳过、排序。
- 座位端专门议程展示。
- 大屏端当前议题、发言人、字幕展示。
- 主持人控制大屏。
- 参会人编辑。
- 主持人端手动分配参会人到座位。
- 投票 draft/publish/archive/reopen。
- 真实认证和权限系统。
- 服务请求 accepted/processing。
