---
name: task-121-interim-display-fix
description: "Task 121: Fix frontend not displaying streaming ASR interim results in real-time"
metadata:
  type: project
---

# Task 121 — 修复前端不显示流式语音识别 interim 的问题

## 问题现象
- 点击座位端 Voice Recognition Start 后，前端没有实时显示流式语音识别结果
- 只有点击 Stop 后，最终识别结果才显示
- final 能显示，说明最终落库/刷新链路大体可用

## 断点定位结果

| 检查项 | 结果 |
|--------|------|
| Speech WS 是否 started | ✅ 是 — `start` → `started` 响应 |
| PCM frames 是否发送 | ✅ 是 — 麦克风音频经 mic → speech WS |
| 后端是否发布 interim | ✅ 是 — `process_pcm_frame` → `TranslationInterimEvent` via EventBus |
| Meeting WS 是否收到 interim | ✅ 是 — E2E 确认 `translation_interim` 到达 `/ws/{mid}` |
| React state 是否更新 | ✅ 是 — `setInterimMap` 处理事件 |
| DOM 是否显示 interim | ⚠️ **仅当 caption 行非空时** — `LiveCaptionBlock` 在两行均为空时渲染不可见块 |

## 根因

`TranscriptPanel.tsx` 中过滤逻辑 `captionInterims = filteredInterims.filter((i) => i.caption != null)` 将**所有** interim 路由到 `LiveCaptionBlock`，因为后端始终包含 `caption` 对象。当字幕格式化器产生空白的 `previousLine`/`currentLine`（早期 ASR 帧），块渲染出空白文本——容器显示了但无可见文字，造成"未显示 interim"的假象。

## 修复

**`frontend/src/components/TranscriptPanel.tsx`** — 修改过滤逻辑：

```ts
// 修复前：caption != null → LiveCaptionBlock
// 修复后：caption 存在且至少一行非空 → LiveCaptionBlock
const captionInterims = filteredInterims.filter(
    (i) => i.caption != null && (i.caption.currentLine || i.caption.previousLine),
);
const textInterims = filteredInterims.filter(
    (i) => i.caption == null || (!i.caption.currentLine && !i.caption.previousLine),
);
```

当 caption 两行均为空时，回退到 `InterimRow` 显示 `source_text`，确保 `source_text` 在存在时始终可见。

## 新增测试

`frontend/src/__tests__/seat.test.tsx` 新增 3 个测试：

| 测试 | 状态 |
|------|------|
| Caption 缺失 → 回退到 transcript-interim 显示 source_text | ✅ |
| Caption 空行 → 回退到 transcript-interim 显示 source_text | ✅ |
| translation_final → 移除 live caption 并显示 final | ✅ |

## 验证结果

| 命令 | 结果 |
|------|------|
| `pytest tests/test_speech_websocket_blackbox.py -q` | **16 passed, 1 skipped** ✅ |
| `pytest tests/test_speech_stream_service.py -q` | **29 passed** ✅ |
| `pytest -q` (全量) | **329 passed, 2 skipped** ✅ |
| `npm run typecheck` | 无错误 ✅ |
| `npm test -- --run` | **108 passed** (105 现有 + 3 新增) ✅ |
| `npm run build` | 构建成功 ✅ |
| E2E: `deterministic-caption.spec.ts` | **PASS** ✅ — 字幕显示、修订更新、final 清除 |
| E2E: `speech-consistency.spec.ts` | **PASS** ✅ — 真实 ASR、live-caption 在 DOM 中、final 正确 |

E2E 确认使用真实 PCM16 + 真实 ASR 时，interim 事件出现在 meeting WS 上（rev 18-20，首帧后约 9.6s），`data-testid="live-caption"` 在录音期间出现在 DOM 中，字幕内容与 WS 负载一致。

## 产出文档

- `working/speech-interim-debug-report.json` — 调试报告
- `working/plan/task-121/changes.md` — 变更说明
- `working/plan/task-121/test-results.md` — 测试结果
