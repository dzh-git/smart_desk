# Test Results — Task 107

## 基线对比

| 套件 | Baseline | 当前 | 差异 |
|---|---|---|---|
| 全量 | 82 passed | **88 passed** | **+6** |
| admin.test.tsx | 21 passed | **27 passed** | **+6** |
| seat.test.tsx | 29 passed | 29 passed | 0 |
| api tests | 25 passed | 25 passed | 0 |

## 新增测试覆盖

| 测试方法 | 覆盖点 |
|---|---|
| `shows interim subtitle after translation_interim event` | interim 文本出现在 TranscriptPanel 中 |
| `higher revision overwrites lower revision interim` | 同 utterance_id 高 revision 覆盖低 revision |
| `lower revision does not overwrite higher revision interim` | 低 revision 不覆盖高 revision |
| `does not trigger full HTTP refresh on translation_interim` | interim 事件不触发 doFetch |
| `translation_final removes matching interim and shows final record` | final 移除 interim + 刷新 final 历史 |
| `translation_interim_cancelled removes matching interim` | cancelled 移除 interim 不新增历史 |

## 详细结果

```text
✓ src/api/__tests__/adapters.test.ts (7 tests)
✓ src/api/__tests__/client.test.ts (8 tests)
✓ src/api/__tests__/resources.test.ts (10 tests)
✓ src/__tests__/App.test.tsx (7 tests)
✓ src/__tests__/seat.test.tsx (29 tests)
✓ src/__tests__/admin.test.tsx (27 tests)

Test Files  6 passed (6)
     Tests  88 passed (88)
```

## 验证

- [x] typecheck 通过
- [x] lint 通过（0 errors）
- [x] 88 tests 全部通过
- [x] build 成功
- [x] 无回归
