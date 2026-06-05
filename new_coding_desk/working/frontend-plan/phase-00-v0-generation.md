# Phase 00: v0 生成准备

## 阶段目标

提供严格要求 React + Vite + TypeScript 的 v0 提示词，并生成不包含后端集成的视觉前端原型。

## 前置条件与允许读取

- 可读取 `docs/V0_FRONTEND_PROMPT.md`。
- 不需要读取后端代码或后续阶段计划。

## 允许修改范围

- `docs/V0_FRONTEND_PROMPT.md`
- `working/frontend-plan/`

## 修改内容

- 要求 v0 输出完整可运行的 Vite 项目和必要入口文件。
- 禁止 Next.js、后端接口、WebSocket、语音识别和复杂业务逻辑。
- 仅让 v0 负责视觉质量、响应式布局、可复用展示组件、mock 数据和简单预览交互。
- 使用新提示词重新生成前端。

## 验证与验收

```powershell
Select-String -Path docs\V0_FRONTEND_PROMPT.md -Pattern 'React','Vite','TypeScript','vite.config.ts','src/main.tsx','src/App.tsx'
Select-String -Path docs\V0_FRONTEND_PROMPT.md -Pattern 'accept.*Next|接受.*Next'
```

- 第一条命令必须找到全部技术要求。
- 第二条命令不得找到接受 Next.js 的描述。
- 人工确认 v0 生成结果包含 Vite 入口文件且不包含 Next.js。

## 停止条件

生成结果不是 React + Vite + TypeScript 时，要求 v0 重新生成，不进入 Phase 01。
