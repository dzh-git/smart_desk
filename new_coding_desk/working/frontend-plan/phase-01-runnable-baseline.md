# Phase 01: 可运行前端基线

## 阶段目标

将 v0 新生成的前端整理为根仓库中的 `frontend/`，先保证项目可安装、可构建、可启动。

## 前置条件与允许读取

- v0 结果必须是 React + Vite + TypeScript。
- 可读取本阶段文档、生成的前端文件和根目录 Git 状态。
- 不读取或实现后端接口规范。

## 允许修改范围

- `frontend/`
- 根目录仅与前端忽略规则直接相关的配置

## 修改内容

- 将新生成结果合并到小写 `frontend/`。
- 删除前端嵌套 `.git`、旧 `node_modules`、Next.js 文件和无关生成文件。
- 使用 npm，保留一份有效的 `package-lock.json`。
- 不增加 API、WebSocket、路由业务或后端功能。

## 验证与验收

```powershell
cd frontend
npm install
npm run build
npm run dev
```

- 安装和构建必须成功。
- 浏览器中管理端与座位端预览页面必须可打开，且没有明显控制台错误。

## 停止条件

构建失败、页面无法打开或仍包含 Next.js 依赖时，不进入 Phase 02。
