# Task 107 — Speech Phase 7: TranscriptPanel interim/final/cancel UI

## 修改文件列表

| 文件 | 操作 | 说明 |
|---|---|---|
| `frontend/src/types.ts` | 修改 | 新增 `InterimTranslation` 类型 |
| `frontend/src/hooks/useAdminData.ts` | 修改 | 新增 `interimMap` 状态 + 智能 `handleWSEvent` (interim→no refresh, final→refresh, cancelled→no refresh) |
| `frontend/src/hooks/useSeatData.ts` | 修改 | 同上 (seat 版) |
| `frontend/src/components/TranscriptPanel.tsx` | 修改 | 新增 `interims` prop + `InterimRow` 组件 (italic/opacity/spinner 视觉区分) |
| `frontend/src/components/AdminDashboard.tsx` | 修改 | 传递 `interims={Object.values(interimMap)}` 给 TranscriptPanel |
| `frontend/src/components/SeatTablet.tsx` | 修改 | 内联翻译列表 → TranscriptPanel 组件；构建 `seatNameMap`；传递 `interimMap` |
| `frontend/src/__tests__/admin.test.tsx` | 修改 | 新增 6 个 transcript 事件测试 |
| `working/deferred-issues.md` | 修改 | 新增 Item 10 (stale-interim 清理) + Item 11 (SeatTablet 空状态变化) |
| `working/plan/task-107/changes.md` | **新增** | 本文件 |
| `working/plan/task-107/test-results.md` | **新增** | 测试结果 |

## interim/final/cancel UI 行为说明

### 事件处理

| 事件 | 行为 | HTTP 刷新? |
|---|---|---|
| `translation_interim` | 按 `utterance_id` 存入 `interimMap`，revision 检查（高或等才覆盖） | 否 |
| `translation_final` | 移除对应 interim + 全量 HTTP 刷新 (更新翻译历史) | 是 |
| `translation_interim_cancelled` | 移除对应 interim | 否 |
| 其他 WS 事件 | 全量 HTTP 刷新 (既有行为) | 是 |

### Revision 防护

`setInterimMap` 使用函数式更新，每个 `translation_interim` 到达时检查 `prev[uid].revision > newRevision`。仅接受 revision ≥ 当前值的更新，防止乱序/旧帧覆盖新帧。

### 视觉区分

| 特征 | Final Row | Interim Row |
|---|---|---|
| 样式 | 正常粗细、黑色文字 | italic、浅灰色文字 |
| 不透明度 | 100% | 80% |
| 语言标签 | `bg-slate-100` | `bg-sky-50 border-sky-200 text-sky-500` |
| 时间戳 | 显示 | 无 (实时) |
| 状态指示 | 无 | 旋转 spinner (`Loader2 animate-spin`) |
| 翻译文本 | `border-l-2 border-slate-200` | `border-l-2 border-sky-200 italic` |

Interim rows 显示在 final rows 之前（实时字幕优先），final rows 按 API 返回顺序显示。

### 数据流

```
WebSocket message
  ├─ translation_interim → setInterimMap({...prev, [utterance_id]: {}}) → TranscriptPanel re-render
  ├─ translation_final   → setInterimMap(remove) + doFetch(false) → TranscriptPanel re-render with final data
  ├─ translation_interim_cancelled → setInterimMap(remove) → TranscriptPanel re-render
  └─ other               → doFetch(false) → full re-render
```

## 测试结果摘要

```text
src/__tests__/admin.test.tsx (27 tests) ✓
  ├─ ... 21 existing tests
  └─ 6 new transcript tests:
     ├─ Transcript - translation_interim event
     │   ├─ ✓ shows interim subtitle after translation_interim event
     │   ├─ ✓ higher revision overwrites lower revision interim
     │   ├─ ✓ lower revision does not overwrite higher revision interim
     │   └─ ✓ does not trigger full HTTP refresh on translation_interim
     ├─ Transcript - translation_final event
     │   └─ ✓ removes matching interim and shows final record
     └─ Transcript - translation_interim_cancelled event
         └─ ✓ removes matching interim without adding history
```

## 验证摘要

- [x] typecheck 通过
- [x] lint 通过（0 errors, 5 pre-existing warnings）
- [x] **88 tests 全部通过**（baseline 82, +6）
- [x] build 成功
- [x] 既有管理端、座位端功能测试无回归
- [x] `translation_interim` 不触发全量 HTTP refresh（fetch count 不增加）
- [x] `translation_final` 触发 refresh 并展示 final 记录
- [x] `translation_interim_cancelled` 移除 interim 不新增历史
- [x] Deferred issues 更新 (Item 10, 11)
