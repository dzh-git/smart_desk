# Phase 02: 文档与契约统一 — 修改记录

## 修改文件

### 1. `working/spec.md`
- **操作:** 在文件开头添加历史背景声明横幅
- **内容:** 明确标注为历史背景文档，不作为新实现契约。指引读者以 `docs/` 目录下的契约文件为准。
- **说明:** 原文中的 Vue 3 引用、旧 API 路径等不再作为实现依据，所有后续实现以 `docs/API_SPEC.md`、`docs/WEBSOCKET_PROTOCOL.md`、`docs/DATABASE_SCHEMA.md`、`docs/EVENT_BUS_SPEC.md` 和 `docs/system_architecture.md` 为准。

## 新增文件

### 2. `frontend/src/api/types.ts`
- 后端 DTO 类型定义，全部使用 snake_case
- 包括: `ApiResponse<T>`, `Meeting`, `Agenda`, `Attendee`, `SeatState`, `SpeakerSeat`, `Vote`, `VoteStatistics`, `VoteOptionStat`, `ServiceCall`, `TranslationRecord`, `TranslationHistoryResponse`
- 枚举类型: `MeetingStatus`, `SeatStatus`, `VoteStatus`, `ServiceCallStatus`, `ServiceType`
- 与 `docs/API_SPEC.md` 完全一致

### 3. `frontend/src/api/client.ts`
- 原生 fetch API 客户端
- 使用相对 `/api/...` 路径
- `ApiError` — HTTP 非成功响应和业务错误
- `NetworkError` — 网络层错误
- `apiGet<T>()`, `apiPost<T>()`, `apiPatch<T>()`, `apiDelete<T>()` — 便捷方法
- 统一解包 `ApiResponse<T>` 并返回 `data`
- `/// <reference types="vitest" />` 添加后移除 — 改用 import 方式

### 4. `frontend/src/api/adapters.ts`
- `SeatDisplay` — 座位展示 ViewModel（与后端 DTO 分离）
- `buildSeatDisplays()` — 将 `SeatState[] + Attendee[] + SpeakerSeat` 合成为 10 个座位展示数据
- 座位状态: `vacant | occupied_unchecked | checked_in`
- 发言席为独立高亮（`isSpeaker`），不是座位状态

### 5. `frontend/vite.config.ts`
- 添加 `server.proxy` 配置:
  - `/api` → `http://localhost:8000`（`changeOrigin: true`）
  - `/ws` → `ws://localhost:8000`（`ws: true`）

### 6. `frontend/src/api/__tests__/client.test.ts`
- 8 个测试用例:
  - 成功响应返回 data
  - 业务错误抛出 ApiError（含 error_code）
  - HTTP 404 抛出 ApiError
  - HTTP 500 非 JSON 响应抛出 ApiError
  - 网络错误抛出 NetworkError
  - null data 响应
  - POST 发送 JSON body
  - POST 无 body 请求

### 7. `frontend/src/api/__tests__/adapters.test.ts`
- 7 个测试用例:
  - 始终返回 10 个座位
  - 缺失状态视为 vacant
  - 正确映射 attendee
  - 发言席为独立高亮
  - occupied_unchecked 状态正确处理
  - 多座位映射（ID 1-10）
  - null speakerSeat 表示无发言席

## 未修改的文件

- 未修改 `backend/` 任何代码
- 未修改 `App.tsx` 及现有 UI 组件
- 未修改 `mockData.ts`（保留了视觉原型 mock 数据）
- 未修改 `types.ts`（现有 UI ViewModel 类型保持不变）
- 未修改 `tsconfig.app.json`（保留 `src/__tests__` 排除规则）
