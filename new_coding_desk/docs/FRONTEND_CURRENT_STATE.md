# Frontend Current State

本文档概述 SmartDesk 前端当前实现状态，明确区分当前已经实现的事实、下一轮必须实现的目标、以及 deferred 功能。

## 1. 路由与角色

| 路由 | 角色 | 当前状态 |
|---|---|---|
| `/` | 默认入口 | 自动跳转到 `/admin`。 |
| `/?seat=N` | 旧座位入口 | 自动跳转到 `/seat/N`。 |
| `/admin` | 主持人端 | 主持人控制台。 |
| `/seat/:seatId` | 座位端 | 1–10 号座位平板；非法座位显示错误页。 |
| `/display` | 大屏端 | 显示会议标题和当前/最近投票结果。 |

## 2. 当前已经实现的事实

### 主持人端

- 进入 `/admin` 后加载 active meeting、座位、发言席、投票、服务请求、字幕记录、议程、参会人。
- 无 active meeting 时显示 `No Active Meeting` 和创建会议表单。
- 创建 pending 会议、启动当前页面创建的 pending 会议、结束 active 会议。
- 查看会议概览、座位状态、参会人、议程、投票、服务请求、会议结果和字幕。
- 选中座位，设置或清除发言席。
- 新增/删除参会人，新增/删除议程。
- 创建 open 投票、关闭 open 投票。
- 处理 pending 服务请求。
- `End Meeting` 并确认后结束 active 会议。
- 字幕记录为全会议公开字幕历史，拉取不传 `seat_id`（`fetchTranslations(meetingId)`）。

### 座位端

- 进入 `/seat/:seatId` 后校验座位号（1–10）。
- 加载 active meeting、座位、发言席、投票、服务请求、字幕记录、议程和参会人。
- 无 active meeting 时显示 `Waiting for Meeting`。
- demo 模式下空座可占座，选择参会人签到。
- 已签到座位可提交/更新投票。
- 已签到座位可发起服务呼叫并取消。
- 字幕区域显示实时 interim 字幕和最终翻译记录。
- 当前座位为发言席且已签到时可启动/停止语音上传。
- **字幕记录为全会议公开字幕历史**，拉取时不传 `seat_id`（`fetchTranslations(meetingId)`），不按当前座位过滤。
- `fetchTranslations(meetingId, seatId?)` 的可选 `seatId` 能力作为 API client 可选参数保留，但座位端默认不传。

### 大屏端

- 进入 `/display` 后加载 active meeting 和投票结果。
- 显示会议标题、当前 open 投票统计、最近关闭投票结果。
- 连接会议 WebSocket，收到投票开始/更新/关闭/会议结束事件后重新加载。
- 点击 `Refresh` 手动刷新。

## 3. 下一轮必须实现的目标

### uiPhase 存储规则

- `uiPhase` 只作为主持人端本地 UI 状态。
- 只支持 `general` 和 `agenda_discussion`。
- 不写入后端。
- 不通过 WebSocket 广播。
- 不影响座位端和大屏端。
- 刷新页面后默认回到 `general`。
- 不实现完整当前议题系统。

### endedMeetingId 存储规则

- 主持人端点击 `End Meeting` 成功后，必须保存刚结束的 `meetingId` 为 `endedMeetingId`。
- `endedMeetingId` 至少保存在 React state。
- 为了刷新后仍能查看刚结束会议结果，建议同步写入 `sessionStorage`。
- 进入 `meeting_ended` 结果视图后，不能只依赖 `GET /api/meetings/active`。
- 必须使用 `endedMeetingId` 拉取：
  - 投票结果；
  - 字幕记录；
  - 服务请求历史。

### 大屏端会议结束后结果来源

- DisplayView 在收到 `meeting_ended` WebSocket 事件时，应保存当前 `meetingId` 为 `endedMeetingId`。
- 会议结束后，大屏端继续用该 `endedMeetingId` 拉取最近投票结果。
- 如果页面是在会议结束后才打开，自动查找历史会议暂时 deferred。
- 不实现会议列表。
- 不实现历史会议选择。

## 4. Deferred（本轮不实现）

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
