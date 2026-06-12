# SmartDesk Demo Runbook

This runbook describes the local v1 demo path after project cleanup.

## Prerequisites

- Windows 10/11.
- Python 3.12+.
- Node.js 20+.
- Browser: current Chrome or Edge.
- Microphone access for manual voice demo.
- Required model data in `models/` and `.hf_cache/` if speech and translation
  have already been downloaded.

Install dependencies:

```powershell
pip install -r requirements.txt
cd frontend
npm install
cd ..
```

## Start

Run:

```powershell
.\start.bat
```

Expected local URLs:

- frontend: `http://127.0.0.1:5173`
- backend API: `http://127.0.0.1:8000`
- backend docs: `http://127.0.0.1:8000/docs`

Stop with:

```powershell
.\kill.bat
```

## Demo Environment Variables

`start.bat` is expected to enable demo-friendly defaults. For manual startup,
set these variables as needed:

```powershell
set ENABLE_DEMO_SEED=true
set ENABLE_DEMO_SEED_WHEN_NO_ACTIVE=true
set ENABLE_DEMO_SEAT_API=true
set VITE_ENABLE_DEMO_CONTROLS=true
```

Optional real translation:

```powershell
set ENABLE_TRANSLATION_MODEL=true
```

If translation is disabled, final records use `[translation not available]`.

## Manual Demo Flow

1. Open admin page: `http://127.0.0.1:5173/`.
2. Confirm an active meeting is visible.
3. Confirm the table shows 10 seats.
4. Open Speaker Seat tablet: `http://127.0.0.1:5173/?seat=1`.
5. If seat 1 is not the Speaker Seat, set it from admin UI or API:

```powershell
curl -X POST http://127.0.0.1:8000/api/seats/speaker `
  -H "Content-Type: application/json" `
  -d "{\"seat_id\":1}"
```

6. On the seat page, click **Start** in Voice Recognition.
7. Grant microphone permission.
8. Speak Chinese.
9. Watch the admin transcript live caption update.
10. Stop speaking and wait for backend auto-final.
11. Confirm the final transcript appears in history.
12. Optionally click **Stop** to send `end_hint` as a manual fallback.
13. Query final records:

```powershell
curl "http://127.0.0.1:8000/api/translations?meeting_id=1"
```

Use the active meeting ID returned by `/api/meetings/active`.

## Expected Speech Behavior

- Live captions update through `translation_interim`.
- Live captions are not saved to the database.
- Silence triggers backend auto-final through RMS endpoint detection.
- `end_hint` remains a fallback.
- Final records are saved in `translation_records`.
- Final records are broadcast through `translation_final`.
- Optional translation runs only when `ENABLE_TRANSLATION_MODEL=true`.

## Automated Demo Validation

Run backend tests:

```powershell
pytest -q
```

Run frontend checks:

```powershell
cd frontend
npm run typecheck
npm run lint
npm test -- --run
npm run build
npm run e2e:speech
```

The Playwright E2E speech test uses PCM fixtures and does not require a physical
microphone.

## Full Command Reference

### Frontend Commands

| Command | Script | Description | Notes |
|---------|--------|-------------|-------|
| Install deps | `cd frontend && npm install` | Install frontend dependencies | Run once after clone |
| Dev server | `cd frontend && npm run dev` | Start Vite dev server | Default http://localhost:5173 |
| Lint | `cd frontend && npm run lint` | ESLint check | Uses ESLint v9 flat config |
| Typecheck | `cd frontend && npm run typecheck` | TypeScript type check | Uses tsconfig.app.json |
| Build | `cd frontend && npm run build` | Production build | Vite build |
| Unit tests | `cd frontend && npm test -- --run` | Vitest unit/integration tests | --run = single run (not watch) |
| Playwright install | `cd frontend && npx playwright install chromium` | Install Chromium browser for Playwright | Run once |
| Playwright run | `cd frontend && npx playwright test <spec> --config=playwright.config.ts --timeout=180000` | Run targeted Playwright test | Set VITE_ENABLE_DEMO_CONTROLS=true |
| Playwright (PowerShell with demo) | `cd frontend; $env:VITE_ENABLE_DEMO_CONTROLS='true'; npx playwright test <spec> --config=playwright.config.ts --timeout=180000` | Run with demo controls enabled | Needed for demo-dependent tests |

> **Note:** `npm run typecheck` exists. There is no `npm run e2e` script; Playwright is invoked directly with `npx playwright test`.

### Backend Commands

| Command | Description | Notes |
|---------|-------------|-------|
| Install deps | `pip install -r requirements.txt` | Install Python dependencies |
| Start server | `python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000` | FastAPI dev server |
| Run tests | `pytest` or `pytest -q` | Python test suite |
| Run tests (verbose) | `pytest -v` | Verbose output |

### Unified Start/Stop Scripts

| Script | Description |
|--------|-------------|
| `start.bat` | Kill old processes, start backend + frontend, open browser |
| `kill.bat` | Kill backend/frontend processes by PID file, port, command line, window title (4-layer) |

> **Note:** There is no `docker-compose.yml` or `Makefile` in this project. All commands are run directly.

### Environment Variables

| Variable | Purpose | Required for Tests |
|----------|---------|-------------------|
| `ENABLE_DEMO_SEED=true` | Auto-create seed meeting on backend start | Yes |
| `ENABLE_DEMO_SEED_WHEN_NO_ACTIVE=true` | Create seed meeting when no active meeting exists | Yes |
| `ENABLE_DEMO_SEAT_API=true` | Enable demo seat occupy/vacate endpoints | Yes (seat tests) |
| `VITE_ENABLE_DEMO_CONTROLS=true` | Show demo controls in frontend (Occupy Seat, preview bar) | Yes (all seat tests) |
| `ENABLE_TRANSLATION_MODEL=true` | Enable real translation model | No (optional) |

### Playwright Test Suite

All E2E tests are in `frontend/e2e/`. Tests must be run with the backend running and appropriate env vars.

| Test File | Purpose | Requires Demo Controls |
|-----------|---------|----------------------|
| `task1-ended-meeting.spec.ts` | Task 1: Admin ended meeting view | No (uses API for setup) |
| `task2-ended-meeting-display.spec.ts` | Task 2: Display ended meeting via WS | Yes† |
| `task3-admin-ui-phase.spec.ts` | Task 3: Phase selector UI | No |
| `task4-button-rules.spec.ts` | Task 4: Button enable/disable rules | Yes |
| `task5-full-meeting-flow.spec.ts` | Task 5: Full meeting lifecycle acceptance | Yes† |
| `task6-low-priority-fixes.spec.ts` | Task 6: Low-priority frontend fixes | Yes† |
| `deterministic-caption.spec.ts` | Speech: deterministic caption test | No |
| `speech-consistency.spec.ts` | Speech: WS consistency test | No |

† Requires `ENABLE_DEMO_SEAT_API=true` for seat occupy API.

### Running All Frontend Checks

```powershell
cd frontend
npm run lint
npm run typecheck
npm run build
npm test -- --run
```

### Running All Playwright E2E Tests

```powershell
cd frontend
$env:VITE_ENABLE_DEMO_CONTROLS='true'
npx playwright test e2e/task1-ended-meeting.spec.ts --config=playwright.config.ts --timeout=180000
npx playwright test e2e/task2-ended-meeting-display.spec.ts --config=playwright.config.ts --timeout=180000
npx playwright test e2e/task3-admin-ui-phase.spec.ts --config=playwright.config.ts --timeout=180000
npx playwright test e2e/task4-button-rules.spec.ts --config=playwright.config.ts --timeout=180000
npx playwright test e2e/task5-full-meeting-flow.spec.ts --config=playwright.config.ts --timeout=180000
npx playwright test e2e/task6-low-priority-fixes.spec.ts --config=playwright.config.ts --timeout=180000
```

### Backend Tests

```powershell
pytest
```

If backend dependencies (torch, funasr, etc.) are missing, some speech-related tests will be skipped. Core meeting/vote/service tests should still pass.

## Full Acceptance Checklist

Before marking a release as ready, verify:

1. **Frontend builds** — `npm run build` exits 0
2. **Lint passes** — `npm run lint` exits 0
3. **No type errors** — `npm run typecheck` exits 0
4. **Unit tests pass** — `npm test -- --run` exits 0
5. **Backend tests pass** — `pytest` exits 0
6. **All Playwright E2E tests pass** — each of the 6 task specs passes
7. **Manual acceptance** — follow the manual steps below for each task

## Task 5 — 完整会议流程验收

### 前提条件

- 后端已启动（`start.bat` 或手动启动，需 `ENABLE_DEMO_SEAT_API=true`, `ENABLE_DEMO_SEED=true`）
- 前端 dev server 已启动（需 `VITE_ENABLE_DEMO_CONTROLS=true`）
- Playwright 测试环境已准备（`npx playwright install chromium`）

### 自动化验收

运行 Task 5 Playwright 测试：

```powershell
cd frontend
$env:VITE_ENABLE_DEMO_CONTROLS='true'
npx playwright test e2e/task5-full-meeting-flow.spec.ts --config=playwright.config.ts --timeout=180000
```

### 手动验收步骤

1. 打开 `/admin` 页面。
2. **验证**：无会议状态显示 "No Active Meeting"，只显示 "Create Pending Meeting" 按钮。
3. 输入会议标题，点击 **Create Pending Meeting**。
4. **验证**："Pending Meeting" 卡片出现，"Start Meeting" 按钮可用。
5. 点击 **Start Meeting**。
6. **验证**：会议进入 active 状态，显示摘要卡片和阶段选择控件。
7. 点击 **Agenda Discussion** 按钮。
8. **验证**：页面显示 "Agenda Discussion Mode" 提示。
9. 输入议程标题并点击 **Add Agenda**。
10. **验证**：议程项显示在列表中。
11. 切换回 **General**。
12. **验证**："Agenda Discussion Mode" 提示消失。
13. 填写投票标题和选项，点击 **Create Vote**。
14. **验证**：投票创建成功，"Close Vote" 按钮出现。
15. 打开 `/seat/1` 页面。
16. Demo 模式下点击 **Occupy Seat (Demo)**。
17. 选择参会人，点击 **Confirm Check-in**。
18. **验证**：显示 "Checked In" 状态。
19. "Active Vote" 区域可见，选择选项后点击 **Submit Vote**。
20. **验证**：显示 "Your vote" 确认。
21. 打开 `/display` 页面。
22. **验证**：大屏显示当前投票（"Vote In Progress"）。
23. 回到 `/admin`，点击 **Close Vote**。
24. **验证**：主持人端投票结果显示关闭状态。
25. 回到 `/display`。
26. **验证**：大屏显示 "Vote Result"。
27. 回到 `/admin`，点击 **End Meeting**，确认。
28. **验证**：主持人端显示 "Meeting Ended" 视图：
    - 投票结果保留
    - 写操作按钮隐藏
    - "New Meeting" 按钮可见
29. **验证**：`/display` 显示 "Meeting Ended"，结果保留。
30. **验证**：`/seat/1` 显示 "Waiting for Meeting"，无操作按钮。
31. 刷新 `/display`，验证结束状态持久化。

## Troubleshooting

No active meeting:

- Delete the local disposable database if present.
- Start with demo seed variables enabled.

Speech button disabled:

- Confirm the page URL has a valid `?seat=N`.
- Confirm the seat is checked in.
- Confirm the seat is the Speaker Seat.
- Confirm backend WebSocket is reachable.

No live caption:

- Confirm microphone permission.
- Wait for first model preload if models are cold.
- Check `GET /api/speech/status`.
- Check backend logs.

Unexpected ASR text:

- ASR accuracy is model and audio dependent.
- Current v1 demo validates the speech pipeline and UI consistency, not final
  transcription accuracy.

## Task 6 — 低优先级前端问题修复

### 前提条件

- 后端已启动（`start.bat` 或手动启动，需 `ENABLE_DEMO_SEAT_API=true`, `ENABLE_DEMO_SEED=true`）
- 前端 dev server 已启动（需 `VITE_ENABLE_DEMO_CONTROLS=true`）
- Playwright 测试环境已准备（`npx playwright install chromium`）

### 自动化验收

运行 Task 6 Playwright 测试：

```powershell
cd frontend
$env:VITE_ENABLE_DEMO_CONTROLS='true'
npx playwright test e2e/task6-low-priority-fixes.spec.ts --config=playwright.config.ts --timeout=180000
```

### 手动验收步骤

#### 1. 座位端字幕可见范围（Task 6 → Task 7 修正）

> **⚠️ Task 7 更新**：Task 6 的「座位端字幕按 seat 过滤」产品预期已被 Task 7 修正。
> 当前座位端行为为 **全会议公开字幕历史**（meeting-wide），默认不按座位过滤。
> `fetchTranslations(meetingId, seatId)` 的可选 `seatId` 参数作为 API client 可选能力保留，
> 供未来实现按座位过滤功能使用，但座位端默认不传 `seatId`。

1. 打开 `/admin` 页面，创建并启动会议。
2. 打开 `/seat/1`，Demo 模式下占座并签到。
3. 打开 `/seat/2`，Demo 模式下占座并签到。
4. **验证**：在浏览器开发者工具的 Network 标签中，`/seat/1` 发起的 `/api/translations` 请求 URL **不应**包含 `seat_id` 参数。
5. **验证**：`/seat/2` 发起的 `/api/translations` 请求 URL **不应**包含 `seat_id` 参数。
6. **验证**：`/admin` 页面的 `/api/translations` 请求 URL 不应包含 `seat_id` 参数。
7. **验证**：座位 1 产生 final translation 后，座位 1、座位 2、座位 3、管理员都能看到该 final record。

#### 2. 语音模型 preload

1. 在 active meeting 状态下，**验证**：主持人端页面显示 "Speech Model:" 区域和 "Preload Speech Model" 按钮。
2. 点击 **Preload Speech Model**。
3. **验证**：按钮短暂显示 "Preloading..." 后显示 "Preload triggered" 或 "Preload failed" 反馈。
4. 会议结束后（End Meeting），**验证**："Preload Speech Model" 按钮不可见。
5. 无会议或会议已结束状态下，**验证**："Preload Speech Model" 按钮不可见。
6. **验证**：语音 Start 按钮启用条件不变（仍需要当前发言席、已签到、meeting active、WS connected、模型 ready、浏览器支持麦克风）。

#### 3. 同名参会人投票提交风险修复

1. 在 active meeting 状态下，添加两个同名参会人（如 "John Doe" / "John Doe"，可用 API 或后台添加）。
2. 打开 `/seat/1`，Demo 模式占座，选择其中一个 "John Doe" 签到。
3. 主持人端创建投票。
4. 在 `/seat/1` 提交投票。
5. **验证**：投票 API 请求中的 `attendee_id` 等于签到绑定的 attendee id（不是通过姓名反查的第一个同名参会人）。
6. 用 API 检查 `/api/votes/{vote_id}/statistics`，**验证**提交的 attendee 正确。

#### 4. 大屏端无 active meeting 自动感知会议开始

1. 打开 `/display`。
2. **验证**：无 active meeting 状态时显示 "Waiting for Meeting"。
3. 打开 `/admin`，创建并启动一个新会议。
4. **验证**：`/display` 在大约 7 秒内自动显示新会议标题，无需手动点击 Refresh。
5. 在 `/admin` 结束会议。
6. **验证**：`/display` 显示 "Meeting Ended" 并保留投票结果（Task 2 兼容）。
7. **验证**：会议结束后大屏仍处于 ended result 状态，不会被轮询覆盖为空状态。
8. 打开 `/admin`，创建并启动第二场新会议。
9. **验证**：`/display` 在 7 秒内自动切换到新会议，不再显示旧会议结果。
10. **验证**：页面上的 Refresh 按钮仍然可用且有效。

## Task 1 — 会议结束后保留会议结果视图（主持人端）

### 前提条件

- 后端已启动（`start.bat` 或手动启动）
- 前端 dev server 已启动

### 手动验收步骤

1. 打开 `/admin` 页面。
2. 创建会议（输入标题，点击 **Create Pending Meeting**）。
3. 点击 **Start Meeting**。
4. 在右侧面板填写投票标题和选项，点击 **Create Vote**。
5. 打开 `/seat/1`（可在 admin 页面的 Seat Preview 下拉选择 1 后点击 **Open Seat Tablet View**）。
6. Demo 模式下点击 **Occupy Seat (Demo)**。
7. 选择参会人（如 Alice Wang），点击 **Confirm Check-in**。
8. 填写投票选项，提交投票。
9. 回到 `/admin`。
10. 在 Vote Panel 中点击 **Close Vote**。
11. **验证**：关闭后的投票结果可见（百分比、票数、Meeting Results 面板显示投票统计）。
12. 点击 **End Meeting**，在弹出的确认对话框中选择确定。
13. **验证**：主持人端显示会议已结束结果视图：
    - 页面顶部显示 "Meeting Ended" 横幅和会议标题
    - Meeting Control 区域显示 "Meeting Ended" 卡片，内含 "This meeting has ended. Results are shown below." 提示
    - 投票结果仍然可见
    - 字幕记录（如有）仍然可见
    - 服务请求历史仍然可见
    - 不显示 "No Active Meeting" 空状态
14. **验证**：会议结束后写操作已禁用或隐藏：
    - End Meeting 按钮不可见（替换为 "New Meeting" 按钮）
    - Create Vote 表单不可见
    - Set Speaker / Clear Speaker 按钮不可见
    - Conference Room — Seat Overview 表格不可见
    - Add Attendee 表单和删除按钮不可见
    - Add Agenda 表单和删除按钮不可见
    - Resolve 按钮不可见
    - Close Vote 按钮不可见
    - Connection Lost 覆盖层不可见
15. **验证**：如果实现了 sessionStorage，刷新 `/admin` 页面后：
    - 会议结果视图仍然可见
    - 投票结果、字幕、服务历史仍然显示
16. （可选）点击 **New Meeting** 按钮回到 No Active Meeting 视图，可创建新会议。

## Task 2 — 大屏端会议结束后保留投票结果

### 前提条件

- 后端已启动（`start.bat` 或手动启动）
- 前端 dev server 已启动
- 环境变量设置：`ENABLE_DEMO_SEAT_API=true`，`VITE_ENABLE_DEMO_CONTROLS=true`

### 手动验收步骤

1. 打开 `/admin` 页面。
2. 创建会议（输入标题，点击 **Create Pending Meeting**）。
3. 点击 **Start Meeting**。
4. 在右侧面板填写投票标题和选项，点击 **Create Vote**。
5. 打开 `/seat/1`（可在 admin 页面的 Seat Preview 下拉选择 1 后点击 **Open Seat Tablet View**）。
6. Demo 模式下点击 **Occupy Seat (Demo)**。
7. 选择参会人（如 Alice Wang），点击 **Confirm Check-in**。
8. 填写投票选项，提交投票。
9. 打开 `/display`。
10. **验证**：大屏端显示当前投票结果（投票标题、选项、票数、百分比）。
11. 回到 `/admin`。
12. 点击 **Close Vote**。
13. **验证**：`/display` 显示关闭后的投票结果（"Vote Result" 状态），而不是 "Vote In Progress"。
14. 回到 `/admin`。
15. 点击 **End Meeting**，在弹出的确认对话框中选择确定。
16. **验证**：`/display` 显示会议已结束状态：
    - 页面顶部标题显示 "Meeting Ended"
    - 页面主体显示琥珀色横幅 "This meeting has ended. Results are preserved below."
    - 投票结果仍然可见
    - 不显示空白、等待会议状态或 "No votes yet"
17. **验证**：如果实现了 sessionStorage，刷新 `/display` 页面后：
    - 会议已结束状态仍然可见
    - 投票结果仍然可见
18. 回到 `/admin` 创建下一场会议并启动。
19. 回到 `/display`，点击 **Refresh** 按钮。
20. **验证**：`/display` 显示新会议标题，而不是旧会议结果（需要手动刷新才能切换到新会议）。

## Task 3 — 主持人端增加最小阶段选择 UI

### 前提条件

- 后端已启动（`start.bat` 或手动启动）
- 前端 dev server 已启动

### 手动验收步骤

1. 打开 `/admin` 页面。
2. 创建会议（输入标题，点击 **Create Pending Meeting**）。
3. 点击 **Start Meeting**。
4. **验证**：主持人端在摘要卡片下方显示阶段选择控件：
   - 显示 "Current Phase:" 标签
   - 显示 "General" 和 "Agenda Discussion" 按钮（分段控件样式）
   - 默认 "General" 按钮被选中（蓝色背景）
5. 点击 **Agenda Discussion** 按钮。
6. **验证**：页面显示议程讨论阶段标识：
   - 阶段选择控件右侧出现琥珀色 "Agenda Discussion" 徽章
   - 议程区域出现琥珀色边框和浅琥珀色背景
   - 显示 "Agenda Discussion Mode — Agenda items are emphasised below." 提示文本
7. **验证**：议程区域仍然可见且更明显：
   - Add Agenda 表单可用
   - 已有议程项可见
8. 在 Agenda Title 输入框输入一条议程（如 "Review Budget"），点击 **Add Agenda**。
9. **验证**：该议程正常显示在 Agenda 列表中。
10. 点击 **General** 按钮。
11. **验证**：页面回到普通会议阶段显示：
    - "Agenda Discussion" 徽章消失
    - 议程区域回到默认样式（无边框/背景强调）
    - "Current Phase:" 显示 "General"
12. 在 Vote Panel 创建投票（填写标题和选项，点击 **Create Vote**）。
13. **验证**：投票创建正常，不受阶段选择影响。
14. 点击 **Close Vote**。
15. **验证**：投票结果正常显示，不受阶段选择影响。
16. 点击 **End Meeting**，在弹出的确认对话框中选择确定。
17. **验证**：会议结束结果视图仍然正常（Task 1 兼容）：
    - 页面顶部显示 "Meeting Ended"
    - 投票结果仍然可见
    - 阶段选择控件不再显示（"Current Phase:" 不可见）
18. 点击 **New Meeting** 回到无会议视图，创建并启动下一场会议。
19. **验证**：阶段选择控件重新出现，默认状态为 "General"。
20. 刷新 `/admin` 页面。
21. **验证**：如果仍有 active meeting，阶段默认回到 "General"。

## Task 4 — 统一前端按钮启用 / 禁用规则

### 前提条件

- 后端已启动（`start.bat` 或手动启动，需 `ENABLE_DEMO_SEAT_API=true`)
- 前端 dev server 已启动（需 `VITE_ENABLE_DEMO_CONTROLS=true`）

### 手动验收步骤

1. 打开 `/admin` 页面。
2. **验证**：`no_meeting` 状态：
   - 只显示 "Create Pending Meeting" 按钮，标题为空时按钮禁用
   - "End Meeting"、"Create Vote"、"Close Vote" 按钮不可见
   - "Current Phase:" 阶段选择器不可见
3. 输入会议标题，点击 **Create Pending Meeting**。
4. **验证**：`meeting_created` 状态：
   - "Pending Meeting" 卡片出现，"Start Meeting" 按钮可用
   - "End Meeting"、"Create Vote" 按钮不可见
5. 点击 **Start Meeting**。
6. **验证**：`meeting_active` 状态：
   - "End Meeting" 按钮可见且可用
   - "Create Vote" 表单可见（可输入标题和选项）
   - "Current Phase:" 阶段选择器可见，"General" 和 "Agenda Discussion" 按钮可用
7. 填写投票标题和选项，点击 **Create Vote**。
8. **验证**：投票创建后：
   - "Close Vote" 按钮可见
   - "Create Vote" 表单隐藏（不能创建第二个 open 投票）
9. 打开 `/seat/1` 页面。
10. **验证**：未签到状态：
    - "Active Vote" 不可见（不能投票）
    - "Service Request" 不可见（不能服务呼叫）
    - 语音 Start 按钮不可见
11. Demo 模式下点击 **Occupy Seat (Demo)**。选择参会人，点击 **Confirm Check-in**。
12. **验证**：签到成功后：
    - Active Vote 区域可见
    - 选择投票选项后 "Submit Vote" 按钮可用
    - 服务呼叫按钮可用
13. 选择选项，点击 **Submit Vote**。
14. **验证**：投票提交后显示 "Your vote" / "Your choice"
15. 回到 `/admin`，点击 **Close Vote**。
16. **验证**：投票关闭后：
    - "Close Vote" 按钮不可见
    - "Create Vote" 表单重新出现
17. 回到 `/seat/1`。
18. **验证**：投票关闭后：
    - 显示 "Final Result" 而非 "Active Vote"
    - "Submit Vote" / "Update Vote" 按钮不可见
    - 投票选项按钮禁用
19. 回到 `/admin`，点击 **End Meeting**，确认对话框选确定。
20. **验证**：会议结束后（主持人端）：
    - 页面顶部显示 "Meeting Ended"
    - "End Meeting" 按钮不可见（替换为 "New Meeting"）
    - "Create Vote" 表单不可见
    - 阶段选择器不可见
    - Add Attendee / Add Agenda 表单不可见
    - Set Speaker / Clear Speaker 不可见
    - 投票结果等只读面板仍然可见
21. 打开 `/seat/1`。
22. **验证**：会议结束后（座位端）：
    - 显示 "Waiting for Meeting"
    - "Confirm Check-in" 不可见
    - 投票结果不可见
    - "Service Request" 不可见
    - 语音 Start 按钮不可见
23. 打开 `/display`。
24. **验证**：大屏端：
    - "Refresh" 按钮可见
    - 没有任何写操作按钮（Create Vote、Close Vote、End Meeting、Start Meeting 等）
    - 投票结果可选择（如会议已结束，显示会议结束状态）

