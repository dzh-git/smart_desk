# Phase 02: 文档与契约统一

## 阶段目标

消除实现规范之间的冲突，为后续前后端接入建立单一契约。

## 前置条件与允许读取

- Phase 01 已通过验证。
- 可读取 `docs/` 下全部规范和 `working/spec.md`。
- 不修改前端或后端代码。

## 允许修改范围

- `docs/`
- `working/spec.md`

## 修改内容

- 统一为 React + Vite + TypeScript。
- 移除 `/api/dashboard`、旧翻译接口、完整语音识别和客户端 WebSocket ping 要求。
- 统一座位、服务呼叫、投票、翻译和会议结束行为。
- 修正统一 SQLite、Repository 职责和重复投票规则。
- 将 `working/spec.md` 标记为历史背景，不作为新实现契约。

## 验证与验收

使用 `Select-String` 搜索 `Vue`、`/api/dashboard`、旧翻译路径、客户端 `ping`、独立语音数据库和“投票不可修改”等冲突关键词，并人工检查命中项。

- 所有保留命中都必须明确说明其已废弃或禁止使用。
- `API_SPEC.md` 与 `WEBSOCKET_PROTOCOL.md` 不得相互矛盾。

## 停止条件

仍存在无法决定的契约冲突时，先向用户确认，不进入 Phase 03。
