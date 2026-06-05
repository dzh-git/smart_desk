# SmartDesk Frontend Integration Plan

## 使用规则

本目录将实现拆分为独立阶段。执行某个阶段时，只读取该阶段文档，以及该文档明确列出的规范文件；不要提前读取或实现后续阶段。

任何修改完成后必须立即执行当前阶段的验证。验证失败时，只能在当前阶段修复，不得继续下一阶段。每个阶段结束时都应处于可构建、可测试、可提交的状态。

## 锁定决策

- 前端目录为根仓库下的 `frontend/`，使用 React + Vite + TypeScript 和 npm。
- v0 只负责视觉原型，后端接入由后续阶段完成。
- 默认路径为管理端，`?seat=1..10` 为座位平板端。
- 不实现或调用 `/api/dashboard`。
- 语音识别仅保留接口和占位展示。
- 重复投票允许更新已有投票。
- 开发演示座位接口必须受环境变量控制。

## 规范优先级

1. `docs/API_SPEC.md`
2. `docs/WEBSOCKET_PROTOCOL.md`
3. `docs/DATABASE_SCHEMA.md` 与 `docs/EVENT_BUS_SPEC.md`
4. `docs/system_architecture.md`
5. `docs/V0_FRONTEND_PROMPT.md`
6. `working/spec.md` 仅作为历史背景

## 阶段顺序

1. `phase-00-v0-generation.md`
2. `phase-01-runnable-baseline.md`
3. `phase-02-doc-contract-normalization.md`
4. `phase-03-frontend-contract-foundation.md`
5. `phase-04-backend-meeting-seat-correctness.md`
6. `phase-05-admin-dashboard-integration.md`
7. `phase-06-websocket-sync.md`
8. `phase-07-seat-tablet-checkin.md`
9. `phase-08-voting.md`
10. `phase-09-service-calls.md`
11. `phase-10-translations-placeholder.md`
12. `phase-11-startup-final-validation.md`
