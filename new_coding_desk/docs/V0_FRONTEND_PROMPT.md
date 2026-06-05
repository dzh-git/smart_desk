# SmartDesk v0 Frontend Prompt

Version: 2.0

Last Updated: 2026-06-04

## 目标

本提示词只用于让 v0 生成视觉质量高、结构清晰、可直接运行的前端原型。

v0 负责少量但重要的设计工作：

- 优化页面美观度、视觉层级和信息密度。
- 设计精致的会议桌、座位状态和信息卡片。
- 适配 16:10 平板与桌面管理端。
- 提供统一的空状态、加载状态和断开连接状态示例。

本阶段不要求 v0 接入真实后端、实现 WebSocket、状态管理、语音识别或完整业务规则。真实后端接入将在生成结果基础上继续开发，并遵循 [API_SPEC.md](./API_SPEC.md) 和 [WEBSOCKET_PROTOCOL.md](./WEBSOCKET_PROTOCOL.md)。

## 使用方式

将下方提示词整体粘贴到 v0。生成结果必须是 React + Vite + TypeScript 项目；如果结果包含 Next.js，请要求 v0 重新生成，不要接受后再迁移。

## 提示词

````text
Design and build a polished frontend prototype for a smart conference table system named “SmartDesk”.

The output must be a complete, runnable React + Vite + TypeScript project.
It must include at least:

- package.json
- index.html
- vite.config.ts
- src/main.tsx
- src/App.tsx

Do not use Next.js, Next.js imports, Server Components, Server Actions, API Routes, or Vercel Analytics.
Do not build a backend, API integration, WebSocket logic, database, authentication, state management framework,
microphone access, VAD, speech recognition, or complex business rules.

Use realistic local mock data and simple local preview interactions only.
Tailwind CSS, shadcn/ui, and lucide-react are welcome when they work cleanly in Vite.

## Product context

SmartDesk is used in a meeting room with:

- 10 smart seats around a conference table
- 10 seat tablets
- 1 administrator tablet
- one active meeting
- seat occupancy and attendee check-in
- one current speaker seat
- voting
- tea, coffee, water, and other service requests
- bilingual meeting transcript display

## Design priorities

- Make the interface visually impressive for a live project demonstration.
- Create a premium modern meeting-room dashboard, not a generic admin template.
- Use a dark navy and charcoal background with restrained cyan and blue highlights.
- Use clear visual differences for vacant, occupied, checked-in, and current-speaker seats.
- Create strong information hierarchy, clean spacing, touch-friendly controls, and restrained animation.
- Make the layout responsive for a 16:10 tablet and a desktop administrator screen.
- Design consistent loading, empty, and disconnected examples.

## Application modes

Create one application with a visible local preview switch:

1. Admin Dashboard
2. Seat Tablet

The final application will later use `?seat=1` through `?seat=10` for seat tablet mode, but this prototype only
needs a convenient local preview switch.

## Admin Dashboard

Create:

- SmartDesk header with meeting title, meeting status, connection indicator, and current time
- A visually prominent conference table with all 10 seats arranged around it
- Seat cards with seat number, attendee name, seat state, and speaker highlight
- Meeting overview and agenda progress
- Active vote display with attractive result bars
- Pending service request panel
- Bilingual transcript timeline
- Compact summary metrics

## Seat Tablet

Create:

- Seat header with seat number, attendee name, meeting title, and connection indicator
- Current speaker display
- Agenda list
- Bilingual transcript timeline
- Large vote option buttons
- Service request buttons for coffee, tea, water, and other
- A clearly labeled “Speech interface reserved” area
- A check-in dialog example

## Prototype behavior

- Keep presentation components reusable and easy to extend.
- Use realistic board-meeting mock data.
- Allow simple local interactions such as switching modes, selecting seats, opening dialogs, choosing vote options,
  and resolving service requests.
- Include visible examples for loading, empty, and disconnected states.

Generate the complete frontend prototype with a cohesive visual design and no backend integration code.
````
