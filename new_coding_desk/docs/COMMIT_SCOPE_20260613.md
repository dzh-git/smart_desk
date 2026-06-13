# SmartDesk 前端视觉与交互优化 — Git 提交范围分析

> **日期**: 2026-06-13  
> **分支**: replace-speech-module

---

## 完整变更清单

运行 `git status --short` 得到以下变更（均为 unstaged modified 或 untracked）：

```
 M .gitignore
 M frontend/src/__tests__/App.test.tsx
 M frontend/src/__tests__/DisplayView.test.tsx
 M frontend/src/__tests__/admin.test.tsx
 M frontend/src/__tests__/seat.test.tsx
 M frontend/src/components/AdminDashboard.tsx
 M frontend/src/components/AdminHeader.tsx
 M frontend/src/components/AgendaPanel.tsx
 M frontend/src/components/ConferenceTable.tsx
 M frontend/src/components/DisplayView.tsx
 M frontend/src/components/MeetingResultPanel.tsx
 M frontend/src/components/SeatTablet.tsx
 M frontend/src/components/ServicePanel.tsx
 M frontend/src/components/TranscriptPanel.tsx
 M frontend/src/components/VotePanel.tsx
 M frontend/src/components/shared.tsx
 M frontend/src/index.css
 M frontend/tailwind.config.js
?? docs/FRONTEND_VISUAL_SPEC.md
?? docs/COMMIT_SCOPE_20260613.md
?? frontend/e2e/visual-smoke.spec.ts
```

**汇总**: 18 个已修改文件 + 3 个新增文件，总计净增约 +1092 行。

---

## 建议提交的文件 ✅

### 前端源码（本轮核心修改）

| 文件 | 改动量 | 说明 |
|------|--------|------|
| `frontend/src/components/AdminDashboard.tsx` | +437/- | 管理后台 Dashboard 视觉优化 |
| `frontend/src/components/AdminHeader.tsx` | +220/- | 管理后台 Header 交互优化 |
| `frontend/src/components/AgendaPanel.tsx` | +11/- | 议题面板微调 |
| `frontend/src/components/ConferenceTable.tsx` | +364/- | 会议表格视觉重构 |
| `frontend/src/components/DisplayView.tsx` | +320/- | 大屏展示视图优化 |
| `frontend/src/components/MeetingResultPanel.tsx` | +55/- | 会议结果面板调整 |
| `frontend/src/components/SeatTablet.tsx` | +713/- | 席位平板触控交互优化（最大改动） |
| `frontend/src/components/ServicePanel.tsx` | +101/- | 服务面板视觉更新 |
| `frontend/src/components/TranscriptPanel.tsx` | +103/- | 转录字幕面板优化 |
| `frontend/src/components/VotePanel.tsx` | +119/- | 投票面板视觉调整 |
| `frontend/src/components/shared.tsx` | +477/- | 共享组件/工具提取与重构 |
| `frontend/src/index.css` | +51/- | 全局样式更新（暗色科技风 token） |
| `frontend/tailwind.config.js` | +25/-1 | Tailwind 配置扩展（颜色 token、阴影等） |

所有组件都有实际差异（`git diff --stat` 验证），属于本轮前端视觉与交互优化的一部分。

### 测试文件

| 文件 | 说明 |
|------|------|
| `frontend/src/__tests__/App.test.tsx` | 适配新组件结构 |
| `frontend/src/__tests__/DisplayView.test.tsx` | 适配 Display 新 UI |
| `frontend/src/__tests__/admin.test.tsx` | 大幅更新（+196/-116），配合 Admin 组件变更 |
| `frontend/src/__tests__/seat.test.tsx` | 适配 Seat 组件变更 |
| `frontend/e2e/visual-smoke.spec.ts` | **新增** — Playwright 三端截图冒烟测试 |

### 新增文档

| 文件 | 说明 |
|------|------|
| `docs/FRONTEND_VISUAL_SPEC.md` | **新增** — 前端视觉规范文档（版本 1.0，日期 2026-06-12）。定义了暗色科技风设计语言、Tailwind token、组件视觉要求 |
| `docs/COMMIT_SCOPE_20260613.md` | **新增** — 本轮 Git 提交范围分析（本文档），作为提交范围决策记录 |

### 配置文件

| 文件 | 说明 |
|------|------|
| `.gitignore` | 新增 `.smartdesk-runtime/` 条目（仅忽略运行时目录，不涉及源码，可以提交） |

---

## 不建议提交的文件 ❌

| 文件/目录 | 理由 |
|-----------|------|
| `working/plan/` 下所有子目录 | 已被 `.gitignore` 中 `working/` 忽略，不在变更列表中 |
| `.smartdesk-runtime/` | 已在 `.gitignore` 中，且目录为空，不存在于 git status |
| `node_modules/` | `.gitignore` 已有 |
| `frontend/dist/` / `dist-ssr/` | `.gitignore` 已有 |
| `frontend/test-results/` | `.gitignore` 已有 |
| Playwright trace/video/screenshot | `.gitignore` 覆盖 |

---

## 需要确认的文件 ❓

经逐文件核验：

- 所有 16 个前端源码修改（`frontend/src/`）均属于本分支的视觉与交互优化工作
- `docs/` 目录有 11 个已跟踪文档，本轮 **仅新增** `FRONTEND_VISUAL_SPEC.md` 和 `COMMIT_SCOPE_20260613.md`，其余文档无任何变更
- `.gitignore` 仅新增 `.smartdesk-runtime/` 条目
- `frontend/e2e/visual-smoke.spec.ts` 作为新增的 Playwright 端到端测试，属于本轮测试配套
- 没有任何运行产物、缓存文件或与本轮无关的文件出现在变更列表中

**结论：本轮没有需要额外确认的文件，所有变更均属于当前工作范围。**

---

## 建议的 git add 命令

逐文件添加：

```bash
git add .gitignore
git add frontend/src/components/AdminDashboard.tsx
git add frontend/src/components/AdminHeader.tsx
git add frontend/src/components/AgendaPanel.tsx
git add frontend/src/components/ConferenceTable.tsx
git add frontend/src/components/DisplayView.tsx
git add frontend/src/components/MeetingResultPanel.tsx
git add frontend/src/components/SeatTablet.tsx
git add frontend/src/components/ServicePanel.tsx
git add frontend/src/components/TranscriptPanel.tsx
git add frontend/src/components/VotePanel.tsx
git add frontend/src/components/shared.tsx
git add frontend/src/index.css
git add frontend/tailwind.config.js
git add frontend/src/__tests__/App.test.tsx
git add frontend/src/__tests__/DisplayView.test.tsx
git add frontend/src/__tests__/admin.test.tsx
git add frontend/src/__tests__/seat.test.tsx
git add frontend/e2e/visual-smoke.spec.ts
git add docs/FRONTEND_VISUAL_SPEC.md
git add docs/COMMIT_SCOPE_20260613.md
```

或者按目录批量添加（更简洁）：

```bash
git add .gitignore \
      frontend/src/ \
      frontend/e2e/ \
      docs/FRONTEND_VISUAL_SPEC.md \
      docs/COMMIT_SCOPE_20260613.md
