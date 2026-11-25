# Frontend Interaction Spec

本文档描述当前 SmartDesk 前端交互事实。它不描述历史计划，也不设计新功能。

## 1. 路由与角色入口

| 路由 | 角色 | 当前行为 |
|---|---|---|
| `/` | 默认入口 | 自动跳转到 `/admin`。 |
| `/?seat=N` | 旧座位入口 | 自动跳转到 `/seat/N`。 |
| `/admin` | 主持人端 | 会议创建、启动、结束、议程、投票、服务、发言席、会议记录和结果查看。 |
| `/host` | Seat 1 主持人平板 | 正式运行时由已绑定的 Seat 1 Android App 进入，原生维护 PIN 解锁后显示控制台。浏览器演示模式提供带标识的主持人平板预览。 |
| `/seat/1` | 兼容入口 | 重定向到 `/host`，不再渲染普通座位页面。 |
| `/seat/:seatId` | 参会者座位端 | Seat 2 到 9；非法座位显示错误。 |
| `/display` | 大屏端 | 会议状态、当前议题、议程进度、当前或最近投票结果。 |
| `/screen` | 大屏视频流端 | 只读全屏 WebRTC 视频流（嵌入中央主机 MediaMTX 中继）；自动轮询 host-display 状态；含 Refresh；无写操作。 |

演示模式：

- `npm run demo` 或 `VITE_ENABLE_DEMO_CONTROLS=true` 启用并标记演示模式。主持人端可直达各席，浏览器席位可用本席分配人员签到。
- 模拟离席需要后端启用 `ENABLE_DEMO_SEAT_API=true`。

## 2. 主持人端流程

Seat 1 Android App 启动进入 `/host`；PIN 解锁前不渲染控制台。解锁后使用与
`/admin` 相同的 `AdminDashboard`，无会议时可直接创建和启动会议。Seat 1 签到是
独立卡片：只有主持人点击后才在 formal 模式打开人脸层，debug 模式调用设备认证
放行接口；签到成功仍停留在控制台。长按维护入口 5 秒进入模板管理页，返回后仍为
`/host`。电脑浏览器 `/admin` 的既有入口不变。

1. 进入 `/admin` 后，前端加载 active meeting、座位、发言席、投票、服务请求、字幕记录、议程和参会人。
2. 无 active meeting 时，显示创建 pending meeting 表单。
3. 创建或恢复最新的 pending meeting 后，可在名单中录入参会者或选用已登记人员，点击座位后设置默认人员，再点击 `Start Meeting`。
4. 启动会议后进入 active meeting 控制台。
5. 主持人端使用本地 `AdminWorkspace` 分组显示内容：
   - `overview`：会议控制、会议桌座位总览、发言席控制、参会人。
   - `agenda_vote`：Agenda Command Center、创建投票、当前投票和投票结果。
   - `service_records`：服务请求和会议记录。
6. `AdminWorkspace` 只是本地 UI 分组，不是会议阶段；不写 storage、不写 URL、不发 API、不通过 WebSocket 同步；刷新后回到 `overview`。
7. 旧的 `当前阶段 / CURRENT PHASE`、`General`、`Agenda Discussion` 已移除。
8. Agenda Command Center 使用后端持久化 `agenda.status`：
   - 点击议题只 preview，不立即切换。
   - `Set Current` 可将 `pending`/`skipped` 议题设为当前；`completed` 不能重开。
   - 已有 active 议题时，切换前由前端确认；确认后旧 active 自动 completed，新议题 active。
   - `Advance` 完成当前 active 并激活下一个 pending。
   - `Complete` 只完成当前 active。
   - `Skip` 二次确认后跳过当前 active。
9. 主持人可创建/关闭投票，投票关闭后显示结果。
10. 主持人可处理 pending 服务请求。
11. 主持人可设置/清除发言席。
12. 主持人可新增/删除参会人，新增/删除非 active 议程。
13. 点击 `End Meeting` 成功后保存刚结束的 `meetingId` 为 `endedMeetingId`，并进入会议结束结果视图。
14. 会议结束结果不依赖 Workspace；主持人直接看到投票结果、字幕记录、服务历史和最终议程进度。

## 3. 座位端流程

1. 进入 `/seat/:seatId` 后，前端校验座位号；Seat 2–9 渲染参会者页，Seat 1 重定向主持人入口。
2. 座位端加载 active meeting、座位、发言席、投票、服务请求、字幕记录、议程和参会人。
3. 无 active meeting 时显示等待会议，并持续低频检测会议是否已开始。
4. 有本席分配人员时，正式 Android 平板使用原生人脸验证。浏览器演示可点击演示签到，主持人也可人工放行。
5. Android 平板使用确认离席。浏览器演示可模拟离席。
6. 已签到后显示参会人信息、当前议题只读卡片、投票、服务呼叫、语音识别和字幕区域。
7. 当前议题只读展示标题、状态和进度；座位端不显示议程控制按钮。
8. open 投票存在时，已签到座位可提交或更新投票。
9. 已签到且无 pending 服务请求时，可发起服务呼叫；有 pending 请求时可取消。
10. 只有当前座位是发言席、已签到、会议 WebSocket connected、语音模型 ready、浏览器支持麦克风时，语音 `Start` 可用。
11. 字幕记录默认显示全会议公开字幕历史，不按当前座位过滤。
12. 会议结束后，座位端不能继续签到、投票、服务呼叫或上传语音。

## 4. 大屏端流程

1. 进入 `/display` 后，前端加载 active meeting。
2. 有 active meeting 时显示会议标题、会议状态、当前议题和议程进度。
3. 有 open 投票时显示当前投票统计。
4. 无 open 投票但有 closed 投票时显示最近关闭投票结果。
5. 无投票时显示大屏友好的空状态。
6. 大屏端只提供 `Refresh`，不提供写操作。
7. 有 active meeting 时连接会议 WebSocket，收到投票、议程、会议结束等事件后刷新对应数据。
8. 等待会议、显示结束结果或连接恢复时，大屏低频检查服务端状态。投票与议程更新期间保留当前画面。
9. 收到 `meeting_ended` 后保存 `endedMeetingId`，继续展示刚结束会议的最近投票结果和最终议程进度。
10. 页面在会议结束后才首次打开时，自动查找历史会议仍然 deferred。

## 5. 关键按钮结果

### 主持人端

| 按钮 | 结果 |
|---|---|
| `Refresh` / `Retry` | 重新加载主持人端数据。 |
| `Create Pending Meeting` | 创建 pending meeting；成功后显示启动入口。 |
| `Start Meeting` | 启动 pending meeting；成功后进入 active meeting。 |
| `End Meeting` | 二次确认后结束会议，保存 `endedMeetingId` 并展示结果。 |
| Workspace 入口 | 只切换 `/admin` 可见内容分组，不触发 API/WS。 |
| 座位卡片 | 本地选中座位。 |
| `Set Speaker` / `Clear Speaker` | 设置或清除发言席；成功后刷新。 |
| `Add Attendee` / 删除参会人 | 新增或删除参会人；成功后刷新。 |
| `Add Agenda` / 删除议程 | 新增议程；删除非 active 议程。 |
| 议程时间线项 | 只 preview。 |
| `Set Current` | 将 preview 的 pending/skipped 议题设为当前。 |
| `Advance` | 完成当前 active，并进入下一个 pending。 |
| `Complete` | 完成当前 active，不自动进入下一项。 |
| `Skip` | 二次确认后跳过当前 active。 |
| `Create Vote` | 创建 open 投票。 |
| `Close Vote` | 关闭 open 投票并显示结果。 |
| `Resolve` | 处理 pending 服务请求。 |
| `Seat N Preview` | 打开对应座位端，不改变后端状态。 |

### 座位端

| 按钮 | 结果 |
|---|---|
| `Refresh` / `Retry` | 重新加载座位端数据。 |
| `Vacate Seat (Demo)` | demo 模式下离座。 |
| `Demo Check-in` | 演示模式下将本席分配人员签到。 |
| 投票选项 | 本地选择投票选项。 |
| `Submit Vote` / `Update Vote` | 提交或更新投票。 |
| `Coffee` / `Tea` / `Water` / `Other` | 创建服务请求。 |
| `Cancel` | 取消当前 pending 服务请求。 |
| 语音 `Start` | 连接 speech WebSocket 并上传 PCM16 音频。 |
| 语音 `Stop` | 立即释放麦克风，发送 `end_hint` 并等待字幕收尾。 |
| 语音 `Cancel` | 取消当前语音识别并清理本地 live caption。 |

### 大屏端

| 按钮 | 结果 |
|---|---|
| `Refresh` | 重新加载会议、议程和投票结果。 |

## 6. Deferred

- 会议列表和选择已有会议。
- 完整议题编辑器：英文标题、预计时长、目标说明、跳过原因、重开 completed。
- 大屏字幕和当前发言人展示。
- 参会人编辑。
- 投票 draft/publish/archive/reopen。
- 真实认证和权限系统。
