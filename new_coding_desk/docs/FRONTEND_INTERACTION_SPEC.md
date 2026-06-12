# Frontend Interaction Spec

本文档描述当前前端交互，并明确区分当前已经实现的事实、下一轮必须实现的目标、以及 deferred 功能。本文档不设计新后端接口，不修改代码。

## 1. 路由与角色入口

| 路由 | 角色 | 当前事实 |
|---|---|---|
| `/` | 默认入口 | 自动跳转到 `/admin`。 |
| `/?seat=N` | 旧座位入口 | 自动跳转到 `/seat/N`。 |
| `/admin` | 主持人端 | 进入主持人控制台。 |
| `/seat/:seatId` | 座位端 | 进入 1 到 10 号座位平板；非法座位显示错误页。 |
| `/display` | 大屏端 | 显示会议标题和当前/最近投票结果。 |

demo 模式规则：

- `VITE_ENABLE_DEMO_CONTROLS=true` 时，主持人端显示座位预览入口。
- `VITE_ENABLE_DEMO_CONTROLS=true` 时，座位端显示返回主持人端按钮和 demo 占座/离座按钮。
- 普通座位端不显示返回主持人端按钮。

## 2. 主持人端流程

### 当前已经实现的事实

1. 进入 `/admin`。
2. 前端加载 active meeting、座位、发言席、投票、服务请求、字幕记录、议程、参会人。
   - 字幕记录使用 `fetchTranslations(meetingId)` 拉取全会议公开字幕历史，不传 `seat_id`。
3. 如果没有 active meeting，页面显示 `No Active Meeting` 和创建会议表单。
4. 主持人填写标题和可选描述，点击 `Create Pending Meeting` 创建 pending 会议。
5. 当前页面显示刚创建的 pending 会议，点击 `Start Meeting` 后会议进入 active。
6. active 会议中，主持人可以查看会议概览、座位状态、参会人、议程、投票、服务请求、会议结果和字幕。
7. 主持人点击座位可选中座位，并设置或清除发言席。
8. 主持人可新增/删除参会人，新增/删除议程。
9. 主持人可创建 open 投票；座位端可提交或更新投票。
10. 主持人可关闭 open 投票；关闭后主持人端和大屏端可展示投票结果。
11. 主持人可处理 pending 服务请求。
12. 主持人点击 `End Meeting` 并确认后，后端结束会议。

### 下一轮必须实现的目标

- 主持人端必须能选择当前 UI 阶段，至少包括：
  - `general`：普通会议进行；
  - `agenda_discussion`：议程讨论视图。
- `agenda_discussion` 只要求作为主持人端可选 UI 阶段，不要求完整当前议题系统。
- **`uiPhase` 存储规则**：
  - `uiPhase` 只作为主持人端本地 UI 状态。
  - 只支持 `general` 和 `agenda_discussion`。
  - 不写入后端。
  - 不通过 WebSocket 广播。
  - 不影响座位端和大屏端。
  - 刷新页面后默认回到 `general`。
  - 不实现完整当前议题系统。
- 会议结束后，主持人端必须展示会议结果。
- **`endedMeetingId` 存储规则**：
  - 主持人端点击 `End Meeting` 成功后，必须保存刚结束的 `meetingId` 为 `endedMeetingId`。
  - `endedMeetingId` 至少保存在 React state。
  - 为了刷新后仍能查看刚结束会议结果，建议同步写入 `sessionStorage`。
  - 进入 `meeting_ended` 结果视图后，不能只依赖 `GET /api/meetings/active`。
  - 必须使用 `endedMeetingId` 拉取投票结果、字幕记录、服务请求历史。

### Deferred

- 会议列表和选择已有会议。
- 启动刷新前已经存在的 pending 会议。
- 完整当前议题系统：当前议题选择、推进、完成、跳过、排序。
- 座位端专门议程展示。
- 大屏端当前议题、发言人、字幕展示。
- 主持人控制大屏。
- 参会人编辑。
- 主持人端手动分配参会人到座位。
- 投票 draft/publish/archive/reopen。
- 真实认证和权限系统。

## 3. 座位端流程

### 当前已经实现的事实

1. 进入 `/seat/:seatId`。
2. 前端校验座位号必须是 1 到 10 的整数。
3. 前端加载 active meeting、座位、发言席、投票、服务请求、字幕记录、议程和参会人。
   - 字幕记录使用 `fetchTranslations(meetingId)` 拉取全会议公开字幕历史，默认不按当前座位过滤。
   - `fetchTranslations(meetingId, seatId?)` 的可选 `seatId` 能力作为 API client 可选参数保留，但座位端默认不传。
4. 如果没有 active meeting，页面显示 `Waiting for Meeting`。
5. demo 模式下，空座可点击 `Occupy Seat (Demo)` 进入已占用未签到状态。
6. 已占用未签到时，用户选择未绑定参会人，点击 `Confirm Check-in` 签到。
7. 签到后，座位端显示参会人信息、发言席状态、投票区域、服务呼叫区域、语音识别区域和字幕。
8. open 投票存在时，已签到座位可 `Submit Vote` 或 `Update Vote`。
9. 已签到座位可发起 `Coffee`、`Tea`、`Water`、`Other` 服务呼叫。
10. 有 pending 服务呼叫时，座位端显示当前请求，并可点击 `Cancel`。
11. 字幕区域显示实时 interim 字幕和最终翻译记录。
12. 只有当前座位是发言席、已签到、会议 WebSocket 已连接、语音模型 ready 且浏览器支持麦克风时，语音 `Start` 可用。

### 下一轮必须实现的目标

- 座位端需要遵守分离后的状态口径：
  - `meetingStatus` 控制会议是否可写；
  - `voteStatus` 控制投票是否可提交；
  - `uiPhase=agenda_discussion` 不强制要求座位端展示完整议题。

### Deferred

- 座位端专门议程展示。
- 座位端完整当前议题展示。
- 非 demo 模式下的占座入口。

## 4. 大屏端流程

### 当前已经实现的事实

1. 进入 `/display`。
2. 前端加载当前 active meeting。
3. 如果存在 active meeting，页面显示会议标题。
4. 前端加载当前 open 投票和会议投票结果。
5. 如果有 open 投票，页面显示当前投票统计。
6. 如果没有 open 投票但有已关闭投票，页面显示最近关闭的投票结果。
7. 如果没有投票，页面显示 `No votes yet`。
8. 点击 `Refresh` 可手动刷新。
9. 有 active meeting 时，大屏连接会议 WebSocket；收到投票开始、投票更新、投票关闭或会议结束事件后重新加载。

### 下一轮必须实现的目标

- 投票结束后，大屏端必须继续显示投票结果。
- 如果会议结束时有投票结果，大屏端应保留最近投票结果。
- DisplayView 在收到 `meeting_ended` WebSocket 事件时，应保存当前 `meetingId` 为 `endedMeetingId`。
- 会议结束后，大屏端继续用该 `endedMeetingId` 拉取最近投票结果。
- 如果页面是在会议结束后才打开，自动查找历史会议暂时 deferred。
- 不实现会议列表。
- 不实现历史会议选择。

### Deferred

- 当前议题展示继续 deferred。
- 发言人展示继续 deferred。
- 字幕展示继续 deferred。
- 主持人控制大屏继续 deferred。
- 无 active meeting 时，大屏不会通过 WebSocket 自动感知会议开始；自动唤醒 deferred。
- 会议列表和选择已有会议 deferred。
- 历史会议选择 deferred。

## 5. 关键按钮点击结果

### 主持人端

| 按钮 | 当前结果 |
|---|---|
| `Refresh` / `Retry` / `Retry Now` | 重新加载主持人端数据。 |
| `Create Pending Meeting` | 创建 pending 会议；成功后页面显示该 pending 会议的启动入口。 |
| `Start Meeting` | 启动当前页面创建的 pending 会议；成功后进入 active 会议控制台。 |
| `End Meeting` | 弹出确认框；确认后结束 active 会议；成功后保存刚结束的 `meetingId` 为 `endedMeetingId`（建议写入 `sessionStorage`）；然后展示会议结果。 |
| 座位卡片 | 本地选中或取消选中座位。 |
| `Set Speaker` | 将选中座位设为发言席；成功后刷新状态。 |
| `Clear Speaker` | 清除当前发言席；成功后刷新状态。 |
| `Add Attendee` | 新增参会人；成功后清空输入并刷新。 |
| 删除参会人按钮 | 删除该参会人；成功后刷新。 |
| `Add Agenda` | 新增议程项；成功后清空输入并刷新。 |
| 删除议程按钮 | 删除该议程项；成功后刷新。 |
| `+ Add option` | 本地新增投票选项输入框。 |
| `Create Vote` | 创建 open 投票；成功后主持人端、座位端、大屏端通过刷新或 WS 进入投票展示。 |
| `Close Vote` | 关闭 open 投票；成功后主持人端和大屏端显示投票结果。 |
| `Resolve` | 将 pending 服务请求处理为 resolved；成功后刷新。 |
| `Seat N Preview` / `Open Seat Tablet View` | 跳转到对应座位端；不改变后端状态。 |

### 座位端

| 按钮 | 当前结果 |
|---|---|
| `Refresh` / `Retry` / `Retry Now` | 重新加载座位端数据。 |
| `Back` | demo 模式下返回 `/admin`；不改变后端状态。 |
| `Occupy Seat (Demo)` | 将空座标记为已占用未签到；成功后刷新。 |
| 参会人选项 | 本地选中或取消选中参会人。 |
| `Confirm Check-in` | 将选中参会人签到到当前座位；成功后刷新。 |
| `Vacate (Demo)` / `Vacate Seat (Demo)` | 将当前座位离座；成功后刷新。 |
| 投票选项 | 本地选中或取消选中投票选项。 |
| `Submit Vote` | 提交当前投票选项；成功后刷新统计。 |
| `Update Vote` | 更新当前参会人的投票选项；成功后刷新统计。 |
| `Coffee` / `Tea` / `Water` / `Other` | 创建对应服务请求；成功后显示 pending 请求。 |
| 服务请求 `Cancel` | 取消当前 pending 服务请求；成功后刷新。 |
| 语音 `Start` | 请求麦克风权限，连接 speech WebSocket，并开始上传 PCM16 音频。 |
| 语音 `Stop` | 发送结束提示，关闭 speech WebSocket，并停止麦克风采集。 |
| 语音 `Cancel` | 发送取消消息，关闭 speech WebSocket，并停止麦克风采集。 |

### 大屏端

| 按钮 | 当前结果 |
|---|---|
| `Refresh` | 重新加载 active meeting 和投票结果。 |

## 6. 状态口径约束

- `meetingStatus` 和 `voteStatus` 必须分开表达。
- `voting_closed` 不再作为核心会议阶段；它只是 `voteStatus=closed`。
- `uiPhase` 是主持人端本地 UI 阶段，只支持 `general` 和 `agenda_discussion`。
- `uiPhase` 不写入后端、不通过 WebSocket 广播、不影响座位端和大屏端；刷新后默认回到 `general`。
- `agenda_discussion` 是主持人端可选 UI 阶段，不要求完整当前议题系统。
- 大屏字幕、当前议题、发言人展示继续 deferred。
- 会议结束后的结果展示必须使用刚结束的 `meetingId` 拉取历史数据，不允许只依赖 active meeting。
- `endedMeetingId` 在 `End Meeting` 成功后或收到 `meeting_ended` WS 事件时保存，至少保存在 React state，建议同步写入 `sessionStorage`。
- **字幕范围规则**：座位端字幕记录为全会议公开字幕历史，默认不按座位过滤。`fetchTranslations(meetingId, seatId?)` 的可选 `seatId` 能力作为 API client 可选参数保留，但座位端默认不传。主持人端也使用 `fetchTranslations(meetingId)`（不传 `seatId`）。大屏端字幕展示 deferred。
