# Phase 06: 管理操作与完整演示 — 变更记录

## 概述

完成可展示初版的管理端写操作、翻译占位展示、启动脚本和完整演示流程验证。

## 修改文件清单

### 新增文件

1. **working/plan/phase-06/changes.md** — 本变更记录
2. **working/plan/phase-06/test-results.md** — 测试结果记录

### 新增 API 函数

3. **frontend/src/api/resources.ts**
   - `createVote(meetingId, title, options, isAnonymous)` — 创建投票
   - `closeVote(voteId)` — 关闭投票
   - `resolveServiceCall(callId)` — 处理服务呼叫

### 管理端写操作 UI

4. **frontend/src/components/AdminDashboard.tsx**
   - 新增 admin action state (creatingVote, closingVote, resolvingId, adminActionError)
   - 新增 `handleCreateVote` — 创建投票处理函数，包含表单验证和冲突错误展示
   - 新增 `handleCloseVote` — 关闭投票处理函数
   - 新增 `handleResolveCall` — 处理服务呼叫函数
   - 新增 Create Vote 表单 (SectionCard)，仅在无 active vote 时显示
   - 新增 admin action 错误提示区域
   - 将 `onCloseVote` 和 `onResolve` 回调传递给 VotePanel 和 ServicePanel

5. **frontend/src/components/VotePanel.tsx**
   - 新增 `onCloseVote` 和 `closingVote` props
   - 新增 "Close Vote" 按钮，仅在 vote.status === "open" 时显示
   - 新增分离线和统计信息展示

6. **frontend/src/components/ServicePanel.tsx**
   - 新增 `onResolve` 和 `resolvingId` props
   - ServiceRow 新增 "Resolve" 按钮，仅在 pending 状态时显示
   - 新增 Loader2 加载动画图标

### 启动脚本

7. **start.bat** — 完全重写
   - 设置 ENABLE_DEMO_SEED=true, ENABLE_DEMO_SEAT_API=true, VITE_ENABLE_DEMO_CONTROLS=true
   - 后端: `python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000`
   - 前端: `cd frontend && npm run dev -- --host 127.0.0.1`
   - 统一进程标题 SmartDesk-Backend / SmartDesk-Frontend

8. **kill.bat** — 重写
   - 按窗口标题杀进程 (SmartDesk-Backend / SmartDesk-Frontend)
   - 按端口号杀进程 (5173, 8000)
   - 新增 uvicorn 进程清理

### 文档修复

9. **working/plan/phase-05/changes.md**
   - 删除「后端无修改」错误陈述
   - 标记管理端写操作推迟至 Phase 06

10. **working/deferred-issues.md**
    - 删除已实现的「SeatTablet is a placeholder」条目 (#6)
    - 修正后续条目编号 (原 7→6, 8→7, 9→8, …)
    - 修正末尾重复的 #10 编号

### 前端测试

11. **frontend/src/__tests__/admin.test.tsx** — 新增 21 个测试用例
    - 创建投票表单展示测试
    - 创建投票 API 调用测试 (含表单填充)
    - 重复投票冲突错误展示测试
    - 关闭投票 API 调用测试
    - 处理服务呼叫 API 调用测试
    - WebSocket vote_closed 事件触发刷新测试
    - WebSocket service_call_resolved 事件触发刷新测试

## 架构决策

- 管理端创建投票表单使用受控组件，提交前做标题和选项验证
- 后端返回 409 Conflict 时，前端展示 detail 中的错误码
- 解析投票后管理端和座位端通过 WebSocket 推送自动刷新
- 翻译历史已在 Phase 05 实现，本阶段仅做验证
- 语音识别保持「接口预留」占位不变

## 未涉及

- 麦克风、VAD、ASR 未实现
- `/api/dashboard` 未实现
- 管理端关闭会议未实现
