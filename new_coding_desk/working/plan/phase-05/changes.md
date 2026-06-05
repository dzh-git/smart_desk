# Phase 05: 座位端与核心交互 — 变更记录

## 概述

实现座位平板端（Seat Tablet），接入真实签到、投票和服务呼叫流程。

## 修改文件清单

### 修复（Phase 05 Review）

#### 1. seat_vacant() 离座时同步解除参会者绑定

**文件:** `backend/services/seat_service.py`
- `seat_vacant()` 现在会在离座时查找并清除绑定的参会者。
- 设置 `attendee.seat_id = None` 和 `attendee.checked_in = False`。
- 已 vacant 的座位仍保持幂等（不尝试清除不存在的绑定）。
- 发布事件行为不变。

**新增测试:**
- `tests/test_seat_service.py`:
  - `test_vacant_clears_attendee_seat_id` — 验证 attendee.seat_id 被置为 None
  - `test_vacant_clears_checked_in_flag` — 验证 attendee.checked_in 被置为 False
  - `test_vacant_allows_recheckin_after_vacate` — 验证同一 attendee 离座后可再次签到
- `tests/test_dev_api.py`:
  - `test_vacate_clears_attendee_binding` — 开发接口离座后 attendee 绑定被清除
  - `test_vacate_allows_recheckin_via_dev` — 开发接口离座后可再次签到

#### 2. useSeatData 重复请求修复

**文件:** `frontend/src/hooks/useSeatData.ts`
- 删除了未使用的 `promises` 数组和副作用赋值。
- 使用一次 `Promise.all` 并行获取 attendees、agendas、translations。
- `fetchCurrentServiceCall` 单独请求并带有失败容错。
- 每个资源每次 refresh 只请求一次。

#### 3. 座位端核心交互测试增强

**文件:** `frontend/src/__tests__/seat.test.tsx`
- 签到测试：选择 attendee 后点击 Confirm Check-in，断言 API 被调用。
- 投票提交测试：选择选项后点击 Submit Vote，断言请求体正确。
- 投票修改测试：两次提交不同选项，断言两个请求体内容正确。
- 服务呼叫创建测试：点击 Coffee 按钮后断言 POST 请求。
- 服务呼叫取消测试：点击 Cancel 按钮后断言 API 被调用。
- `checkin_prompt` 事件触发数据刷新测试。
- WebSocket 断线测试使用同步 `wsDisconnect()` 替代定时器竞争。

### 新增文件（原始 Phase 05）

1. **src/hooks/useSeatData.ts**
   - 座位端独立数据 hook
   - 并行请求：active meeting、seats、speaker seat、active vote、attendees、agendas、current service call、translations
   - WebSocket 连接 `/ws/{meeting_id}?seat={seat_id}`
   - 断线时触发 overlay，禁用写操作
   - 提供 `unboundAttendees` 供签到选择

2. **src/__tests__/seat.test.tsx**
   - 17 个测试用例覆盖所有 SeatTablet 场景
   - 包含 loading、error、no meeting、三种座位状态
   - 签到 API、参会者选择
   - 演示控制环境变量开关
   - 投票展示、服务呼叫创建/当前/取消
   - WebSocket 断线禁用写操作
   - 语音占位且无伪造麦克风行为

### 修改文件

3. **src/App.tsx**
   - 新增 URL 参数解析 (`?seat=1..10`)
   - 默认路径显示管理端
   - 非法 seat 参数显示明确错误页面（含返回管理端按钮）
   - 管理端和座位端通过 `window.location.href` 切换

4. **src/components/SeatTablet.tsx** (完全重写)
   - 三种座位状态展示：vacant / occupied_unchecked / checked_in
   - 签到流程：参会者选择 → checkin API → 刷新
   - 演示控制（Occupy/Vacate）仅在 `isDemoControlsEnabled()` 返回 true 时显示
   - 投票：仅展示 active/open vote，提交/更新投票
   - 服务呼叫：Coffee / Tea / Water / Other 四个类型，创建/当前/取消
   - 有 pending 请求时禁止重复创建
   - 语音区域显示"语音识别接口预留"占位
   - WebSocket 断线 overlay + 禁用写操作

5. **src/components/AdminDashboard.tsx**
   - 座位预览控件仅在 `isDemoControlsEnabled()` 返回 true 时显示
   - 管理端头部预览按钮受同一开关控制

6. **src/components/AdminHeader.tsx**
   - `onModeSwitch` 和 `previewSeat` 变为可选属性
   - 预览按钮在未提供时不显示

7. **src/components/shared.tsx**
   - 新增 `isDemoControlsEnabled()` 函数

8. **src/hooks/useWebSocket.ts**
   - 新增可选 `seatId` 参数
   - URL 构造支持 `?seat={seatId}`

9. **src/api/resources.ts**
   - 新增 API 方法：`checkinSeat`, `devOccupySeat`, `devVacateSeat`
   - 新增投票方法：`fetchVote`, `submitVote`
   - 新增服务呼叫方法：`fetchCurrentServiceCall`, `createServiceCall`, `cancelServiceCall`

## 架构决策

- 使用 `isDemoControlsEnabled()` 函数而非模块级 const，便于测试 mock
- 投票重复提交通过后端 upsert（V4 规则）实现，前端允许重新选择后提交
- 服务呼叫创建时后端验证唯一 pending 限制，前端也做 UI 层防护
- WebSocket 断开时仅前端 overlay，不依赖后端

## 未涉及

- 语音模块麦克风、VAD、ASR 未实现
- 管理端写操作（创建投票、关闭会议等）未实现（已推迟至 Phase 06）
