# SmartDesk 前端视觉规范

> **版本**: 1.1  
> **状态**: 当前 SmartDesk 深色科技风视觉规范；用于约束三端视觉一致性和后续小范围 UI 修复。  
> **最后更新**: 2026-06-18

---

## 1. Design Goals (设计目标)

1. **赛博朋克科技感** — 深色背景 + 霓虹青 Cyan 高亮基调，营造沉浸式会议控制体验。
2. **信息密度适中** — 会议控制需要同时呈现状态、议题、发言、字幕，但绝不拥挤；善用间距和卡片层级。
3. **简洁高效** — 去掉装饰性冗余，每一个视觉元素都有功能归属。Admin 控制台侧重操作效率，Display 大屏侧重状态感知，Seat 平板侧重触控易用。
4. **一致性** — 所有页面共享同一套 token 体系（颜色、阴影、圆角、字体），不出现两套视觉语言。
5. **实时感** — 通过 cyan glow 阴影、脉冲动效、流畅过渡来体现 WebSocket 实时通信的气质。
6. **触控友好** — Seat 平板为 13.3 英寸触屏设计，所有触摸目标 ≥ 44px，防误触。

---

## 2. Dark Technology Visual Direction (暗色科技视觉方向)

- **底色**: `#050b14` (techBg) — 极深藏青，接近黑色带一丝蓝底。
- **表面**: `#07111f` (techSurface) — 面板、侧栏背景。
- **卡片**: `#0b132b` (techCard) — 内容区块。
- **卡片柔和**: `#111c33` (techCardSoft) — 悬浮或轻微高亮状态。
- **边框**: `#1e2a44` (techBorder) — 分割线和边框，低对比度不刺眼。
- **高亮色**: `#00eaff` (techCyan) — 主强调色，用于激活态、焦点、链接、发光效果。
- **辅助蓝**: `#38bdf8` (techBlue) — 次要强调和信息提示。
- **文字**: `#e5edf7` (techText) — 高亮主文字；`#7f8ea3` (techMuted) — 辅助/次要文字。
- **背景装饰**: 使用 `bg-tech-radial`（左上到右下径向渐变，techCyan 12% → transparent 32% + techBlue 8% → transparent 36%），仅用于页面级背景，不干扰内容可读性。
- **全局阴影**: 卡片使用 `shadow-card-glow` (18px 50px rgba(0,0,0,0.35))；活跃/选中元素使用 `shadow-cyan-glow` (0 0 18px techCyan 32%) 或 `shadow-cyan-glow-strong` (0 0 32px techCyan 45%)。

---

## 3. Color System (色彩系统)

所有颜色通过 Tailwind semantic tokens 引用，禁止在 JSX 中直接使用十六进制色值。

### 3.1 基础色板

| Token | 值 | 用途 |
|-------|------|------|
| `techBg` | `#050b14` | 页面 / 最底层背景 |
| `techSurface` | `#07111f` | 侧栏 / 面板背景 |
| `techCard` | `#0b132b` | 卡片 / 内容区块背景 |
| `techCardSoft` | `#111c33` | 卡片悬浮 / 轻微高亮 |
| `techBorder` | `#1e2a44` | 边框 / 分割线 |
| `techText` | `#e5edf7` | 主文字颜色 |
| `techMuted` | `#7f8ea3` | 辅助文字 / 占位符 |

### 3.2 语义色

| Token | 值 | 用途 |
|-------|------|------|
| `techCyan` | `#00eaff` | 主强调、焦点指示器、活动状态、链接 |
| `techBlue` | `#38bdf8` | 次要强调、信息提示 |
| `techGreen` | `#10b981` | 成功、已连接、在线状态 |
| `techAmber` | `#f59e0b` | 警告、连接中、待定状态 |
| `techRose` | `#f43f5e` | 错误、断开连接、危险操作 |

### 3.3 状态与语义色映射

| 状态 | 颜色 |
|------|-------|
| Connected / Active / Online | `techGreen` |
| Connecting / Pending / Warning | `techAmber` |
| Disconnected / Error / Offline | `techRose` |
| Focus / Selected / Highlight | `techCyan` |
| Info / Secondary | `techBlue` |

### 3.4 透明度规范

- 叠加层（overlay）：`bg-black/60` 或 `bg-techBg/80`
- 分割线：`border-techBorder/50`
- 禁用状态：`opacity-40`
- 悬浮高亮：使用 `techCardSoft` 而非透明度叠加

---

## 4. Typography Scale (字体层级)

使用 Tailwind 默认字体栈（系统无衬线字体）。不需引入外部字体。

### 4.1 字号层级

| 用途 | Class | 大小 | 字重 | 颜色 |
|------|-------|------|------|------|
| 大屏标题（Display） | `text-4xl` | 36px | `font-bold` | `techText` |
| 页面标题 | `text-2xl` | 24px | `font-semibold` | `techText` |
| 区块标题 | `text-lg` | 18px | `font-semibold` | `techText` |
| 正文 / 按钮 | `text-sm` | 14px | `font-medium` | `techText` |
| 辅助文字 | `text-xs` | 12px | `font-normal` | `techMuted` |
| 字幕/转录（大屏） | `text-2xl` | 24px | `font-normal` | `techText` |
| 字幕/转录（管理端） | `text-base` | 16px | `font-normal` | `techText` |

### 4.2 规则

- English secondary label：`text-xs text-techMuted`，在中文下方 `-mt-0.5`。
- 小写英文标签在合适场景可用 `tracking-wider uppercase`。
- 不要根据视口宽度直接缩放字体。
- letter-spacing 默认 `0`，仅 small uppercase 英文标签可加宽。

---

## 5. Spacing and Radius Rules (间距与圆角规则)

### 5.1 间距

- 使用 Tailwind 默认间距体系（`p-2` = 8px, `p-4` = 16px, 以 4px 为步进）。
- 卡片内间距：`p-5` (20px) 或 `p-6` (24px)。
- 卡片间间距：`gap-4` (16px) 或 `gap-6` (24px)。
- 区块间距：`space-y-6` (24px) 或 `space-y-8` (32px)。
- 密集管理端行：垂直 padding 8-12px。
- 大屏面板：padding 24-40px。
- 关联控件组间距：8px。
- 页面 shell 最大宽度遵循路由需求，不加额外约束。

### 5.2 圆角

| 用途 | Class | 值 |
|------|-------|-----|
| 卡片（默认） | `rounded-lg` | 8px |
| 按钮 | `rounded-lg` | 8px |
| 输入框 | `rounded-lg` | 8px |
| 徽章 | `rounded-full` | 9999px |
| 小图标容器 | `rounded-md` | 6px |
| 大屏卡片（Display） | `rounded-xl` | 12px |
| Tab 导航容器 | `rounded-lg` | 8px |
| 二次确认弹窗卡片 | `rounded-xl` | 12px |

> **例外说明**: 大屏展示卡片（Display 视图）可使用 `rounded-xl`（12px）获得更柔和的视觉边界；二次确认弹窗可适当放大圆角至 `rounded-xl`。默认业务卡片始终使用 `rounded-lg`（8px），不与既有前端设计约束冲突。

### 5.3 禁止

- 不在卡片内再嵌套视觉卡片；二级分组使用柔和面板或行背景。
- 不使用与 Tailwind 默认体系冲突的自定义间距。

---

## 6. Card Style Rules (卡片样式)

### 6.1 基础卡片

```jsx
<div className="bg-techCard border border-techBorder rounded-lg p-5 shadow-card-glow">
  {/* 内容 */}
</div>
```

### 6.2 卡片标题栏

- 卡片标题使用 `text-sm font-semibold text-techText`。
- 需要在卡片顶部加标题栏时，用 `border-b border-techBorder` 分割，标题栏高度约 44px。
- 标题栏右侧可放 `headerRight` 操作区。
- 标题文字：`text-xs font-semibold uppercase tracking-widest text-techMuted`。

### 6.3 选中/活跃卡片

- 选中态：`border-techCyan shadow-cyan-glow bg-techCyan/5`。
- 保持内容可读性，整体不饱和填充。

### 6.4 卡片悬浮

- 悬浮态：`hover:bg-techCardSoft hover:border-techCyan/20`。
- 仅交互性卡片（可点击、可操作）使用悬浮效果。

### 6.5 空状态卡片

- 居中图标 48×48px，`text-techMuted`。
- 标题 `text-sm font-medium text-techMuted`。
- 描述 `text-xs text-techMuted/70`。
- 安静显示，使用 muted 文字和细边框。

### 6.6 卡片稳定性

- 对于座位、投票选项、仪表盘指标等 WebSocket 更新频繁的卡片，必须使用固定尺寸以防止布局偏移。
- 不允许动态内容撑大卡片造成布局抖动。

---

## 7. Button Style Rules (按钮样式)

### 7.1 主要按钮 (Primary)

```jsx
<button className="bg-techCyan text-techBg text-sm font-semibold rounded-lg px-5 py-2.5 hover:brightness-110 active:brightness-90 transition-all">
  创建会议
</button>
```

- 背景 `bg-techCyan`，文字 `text-techBg`。
- 悬浮 `brightness-110`，按下 `brightness-90`。

### 7.2 次要按钮 (Secondary)

```jsx
<button className="bg-techCard border border-techBorder text-techText text-sm font-medium rounded-lg px-5 py-2.5 hover:bg-techCardSoft transition-colors">
  取消
</button>
```

### 7.3 危险按钮 (Danger)

```jsx
<button className="bg-techRose/10 border border-techRose/30 text-techRose text-sm font-medium rounded-lg px-5 py-2.5 hover:bg-techRose/20 transition-colors">
  结束会议
</button>
```

- 默认态：rose 边框/文字，半透明 rose 背景。
- 最终确认按钮：`bg-techRose text-white`。

### 7.4 幽灵按钮 (Ghost)

```jsx
<button className="text-techMuted text-sm font-medium hover:text-techText transition-colors px-2 py-1">
  更多
</button>
```

### 7.5 按钮禁用

- 禁用态：`opacity-40 cursor-not-allowed pointer-events-none`。
- 禁止禁用按钮响应 hover/active 效果。

### 7.6 按钮尺寸

| 变体 | 高度 | 横填充 | 字号 |
|------|------|--------|------|
| 默认 | 36-40px | `px-5` | `text-sm` |
| 小 | 28-32px | `px-3` | `text-xs` |
| 大 | 44-48px | `px-6` | `text-base` |

### 7.7 通用规则

- 按钮中常用操作使用 lucide 图标 + 文字组合。
- 危险或高影响操作必须图标 + 文字同时出现。
- Seat 平板按钮必须包含触控反馈（`active:scale-95` 或 `active:bg-techCyan/20`）。
- 图标不得替代状态文字，如果状态可能被误解。

---

## 8. Badge / Status Style Rules (徽章与状态指示)

### 8.1 状态指示点

- 圆点 6×6px (`w-1.5 h-1.5 rounded-full`)。
- Active: `bg-techGreen animate-pulse`
- Pending: `bg-techAmber`
- Finished/Offline: `bg-techMuted`

### 8.2 状态徽章

```jsx
<span className="inline-flex items-center gap-1.5 text-xs font-medium rounded-full px-2.5 py-1
  bg-techGreen/10 border border-techGreen/30 text-techGreen">
  <Wifi size={12} />
  Connected
</span>
```

颜色映射规则：

| 状态 | 背景 | 边框 | 文字 |
|------|------|------|------|
| active / connected / online | `bg-techGreen/10` | `border-techGreen/30` | `text-techGreen` |
| pending / connecting / waiting | `bg-techAmber/10` | `border-techAmber/30` | `text-techAmber` |
| finished / disconnected / ended | `bg-techRose/10` | `border-techRose/30` | `text-techRose` |
| info / speaker / current vote | `bg-techCyan/10` | `border-techCyan/30` | `text-techCyan` |
| 默认未知 | `bg-techBlue/10` | `border-techBlue/30` | `text-techBlue` |

### 8.3 连接断开覆盖层

```jsx
<div className="absolute inset-0 bg-techBg/80 backdrop-blur-sm flex flex-col items-center justify-center z-50 rounded-lg">
  <WifiOff className="text-techRose" size={24} />
  <p className="text-sm font-semibold text-techText mb-1">Connection Lost</p>
  <p className="text-xs text-techMuted mb-4">Attempting to reconnect...</p>
  <button className="...secondary button...">Retry Now</button>
</div>
```

---

## 9. Form / Input Style Rules (表单与输入框)

### 9.1 文本输入框

```jsx
<input className="w-full bg-techSurface border border-techBorder rounded-lg px-4 py-2.5
  text-sm text-techText placeholder:text-techMuted/60
  focus:outline-none focus:border-techCyan focus:ring-1 focus:ring-techCyan/30
  transition-colors" />
```

- 背景 `bg-techSurface`，边框 `border-techBorder`。
- 占位符文字 `text-techMuted/60`。
- Focus 状态：边框 `techCyan` + 外发光 `ring-techCyan/30`。
- 高度不低于 40px。

### 9.2 Select 下拉框

- 同输入框样式基础。
- 使用原生 select 或自定义，统一圆角和高度。

### 9.3 标签 / Label

- `text-xs font-medium text-techMuted mb-1.5 block`。
- 与输入框间距 `gap-1.5`。

### 9.4 表单错误

- 边框 `border-techRose`。
- 错误消息 `text-xs text-techRose mt-1`。

### 9.5 规则

- 验证错误使用 rose 文字和边框。
- 表单需紧密分组标签、帮助文字和错误信息。
- 视觉工作中不添加新的表单行为。

---

## 10. Tab / Section Navigation Style Rules (标签与导航样式)

### 10.1 Tab 导航

```jsx
<div className="flex gap-1 bg-techSurface p-1 rounded-lg">
  <button className="px-4 py-2 text-sm font-medium rounded-md transition-colors
    data-[active=true]:bg-techCard data-[active=true]:text-techCyan
    data-[active=true]:shadow-sm
    text-techMuted hover:text-techText">
    进行中
  </button>
</div>
```

- 容器：`bg-techSurface p-1 rounded-lg`，内边距 4px 防止内容溢出。
- 非活跃：`text-techMuted hover:text-techText`。
- 活跃：`bg-techCard text-techCyan shadow-sm`。

### 10.2 Section 标题栏

- 使用卡片内标题栏模式（`border-b border-techBorder` 分割）。
- 标题 `text-xs font-semibold uppercase tracking-widest text-techMuted`。

### 10.3 侧栏导航项

```jsx
<a className="flex items-center gap-3 px-4 py-2.5 text-sm rounded-lg
  text-techMuted hover:text-techText hover:bg-techCard
  aria-[current=page]:bg-techCard aria-[current=page]:text-techCyan
  aria-[current=page]:border-l-2 aria-[current=page]:border-techCyan">
  <LayoutDashboard size={20} />
  控制台
</a>
```

- 非活跃：`text-techMuted hover:text-techText hover:bg-techCard`。
- 活跃：`bg-techCard text-techCyan`，左侧 2px cyan 指示条。
- 导航图标统一 20px。

---

## 11. Bilingual UI Rules (中英双语规则)

### 11.1 基本原则

- **中文为主要语言**，英文为次要辅助语言。
- 所有面向用户的标签、标题、按钮文字，优先显示中文。
- 英文作为 secondary label，以较小字体和辅助色显示在中文下方或右侧。

### 11.2 双标签模式 (DualLabel)

`DualLabel` 组件已在 `shared.tsx` 中实现（见 21.1），其 props 与样式约定如下：

```jsx
interface DualLabelProps {
  cn: string;    // 中文主标签
  en?: string;   // 英文副标签（可选）
  className?: string;
  cnClassName?: string;
  enClassName?: string;
}
```

- 中文：`font-semibold text-techText`。
- 英文：`text-xs font-mono uppercase tracking-wider text-techMuted`，在中文下方。
- 英文不存在时仅显示中文。

### 11.3 Logo / 品牌标识

- 主标题中文优先，英文副标题置于下方。

### 11.4 中英文混排规范

- 中文与英文之间加一个空格（如"创建会议 Create Meeting"）。
- 数字与单位之间不加空格（"13.3英寸" 而非 "13.3 英寸"）。
- 使用全角标点（。，！？）用于中文句子，英文内容使用半角标点。
- 在密集操作面板中避免长段双语段落，使用紧凑标签和 tooltip。

---

## 12. Lucide-React Icon Usage Rules (图标使用规则)

### 12.1 图标库

- 仅使用 `lucide-react`，不使用其他图标库。
- 版本：`^0.344.0`（见 package.json）。

### 12.2 图标风格

- 所有图标使用 stroke 风格，视觉一致。
- 默认尺寸 16-20px，语义状态图标可适当调整。
- 图标颜色默认继承父元素文字颜色，除非语义需要。

### 12.3 常用图标映射表

| 用途 | 图标 | 默认尺寸 |
|------|------|----------|
| 连接成功 | `Wifi` | 12-16px |
| 连接中 | `Loader2` (+ `animate-spin`) | 12-16px |
| 断开连接 | `WifiOff` | 12-16px |
| 加载 | `Loader2` | 16-20px |
| 空状态 | `ClipboardList` / `Inbox` | 24-32px |
| 添加 | `Plus` | 16-20px |
| 关闭 | `X` | 16-20px |
| 编辑 | `Pencil` | 14-16px |
| 删除 | `Trash2` | 14-16px |
| 返回 | `ArrowLeft` | 16-20px |
| 刷新 | `RefreshCw` | 14-16px |
| 搜索 | `Search` | 14-16px |
| 设置 | `Settings` | 16-20px |
| 通知 | `Bell` | 16-20px |
| 全屏 | `Maximize2` | 16-20px |
| 退出全屏 | `Minimize2` | 16-20px |
| 麦克风 | `Mic` | 16-20px |
| 麦克风关闭 | `MicOff` | 16-20px |
| 举手 | `Hand` | 16-20px |
| 投票 | `Vote` | 16-20px |
| 计时器 | `Timer` | 16-20px |
| 菜单 | `Menu` | 16-20px |
| 更多 | `MoreHorizontal` / `MoreVertical` | 16-20px |
| 复制 | `Copy` | 14-16px |
| 确认 | `Check` / `CheckCircle` | 14-16px |
| 仪表盘 | `LayoutDashboard` | 20px |
| 会议 | `Users` | 20px |
| 发言 | `MessageSquare` | 20px |

### 12.4 语义颜色映射

- 成功 / 在线：`text-techGreen`
- 警告 / 待定：`text-techAmber`
- 错误 / 危险：`text-techRose`
- 高亮 / 选中：`text-techCyan`

### 12.5 图标容器

- 交互图标（可点击）最小触摸目标 44×44px，内部图标居中。
- 纯展示图标无需扩大触摸区域。
- 图标必须与文字配对用于危险、歧义或高影响操作。

---

## 13. Admin Console `/admin` Layout Principles (管理控制台布局)

### 13.1 整体布局

- 左侧固定侧栏（约 240px 宽）+ 右侧主内容区。
- 侧栏：`bg-techSurface border-r border-techBorder`，包含导航项和系统品牌标识。
- 主内容区：`bg-techBg`，可滚动。

### 13.2 侧栏导航

- 品牌标识区域：顶部约 56px 高度，含 logo 和中英文标题。
- 导航项样式见第 10.3 节。
- 导航项分组可选，组标题 `text-xs font-semibold uppercase tracking-widest text-techMuted/60 px-4 py-2`。

### 13.3 顶部栏

- 全局状态指示区：显示连接状态、会议状态、当前时间。
- 高度约 48-56px，`border-b border-techBorder`。
- 右侧可放置全局操作（全屏、设置等）。

### 13.4 内容区

- 页面标题：`text-2xl font-semibold text-techText mb-6`。
- 卡片网格：`grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6`。
- 响应式断点遵循 Tailwind 默认（sm:640px, md:768px, lg:1024px, xl:1280px）。

### 13.5 布局原则

- 优先操作密度和快速扫描。
- 使用清晰的网格组织会议状态、座位、投票、服务、议程、参会者和字幕面板。
- 将破坏性会议控制与常规操作视觉分离。
- 不引入落地页或营销风格 hero。

---

## 14. Seat Tablet `/seat/:seatId` Layout Principles (座位平板布局)

### 14.1 设备约束

- 13.3 英寸触控屏幕，分辨率 1920×1080。
- 竖屏/横屏均需适配，优先横屏。
- 触摸目标最小 44×44px，按钮间距至少 8px 防止误触。

### 14.2 布局

- 全屏深色背景 `bg-techBg`，无浏览器 chrome（全屏 API）。
- 顶部状态栏：会议名称 + 连接状态 + 当前时间，高度约 48px。
- 主内容区居中对齐，最大宽度 900px。
- 底部操作栏：主要操作按钮（发言/投票等），水平排列，间距 12px+。

### 14.3 内容层级

- 当前主要任务应视觉上占主导。
- 显示席位标识、签到状态、发言状态、投票状态、服务状态、发言控制和字幕访问。
- 使用大尺寸触控控件用于签到、投票、服务请求和发言。
- 避免 admin 端控制，除非 demo 模式明确允许。

### 14.4 防误触规则

- 所有不可逆操作（如"结束会议"）需要二次确认弹窗。
- 危险按钮使用 `techRose` 色并带确认弹窗。
- 按钮间距不小于 8px。
- 触摸反馈：`active:scale-95` 微缩动效。
- 非活动区域不应响应触摸。

---

## 15. Central Display `/display` Layout Principles (中央大屏布局)

### 15.1 设备约束

- 大屏电视 / 投影仪，16:9 比例。
- 最小 1920×1080，可能更高分辨率。
- 非触控设备，无需触摸目标考量，但字号需远距离可读。

### 15.2 布局

- 全屏深色背景 `bg-techBg`，无滚动条。
- 信息层级从中心向外辐射。
- 主区域：当前发言人 + 实时字幕，居中大字号（24-36px）。
- 辅助信息：会议标题、议程进度、计时等，置于顶部或底部状态栏。

### 15.3 设计原则

- 优化会议室可读性和远距离识别。
- 会议标题、投票问题和投票结果应为最清晰元素。
- 使用大数字、高对比度和稳定布局。
- 在现有逻辑保留的情况下保留已结束会议的投票结果。
- 主持人控制大屏功能已在 `/admin` Overview 的 `HostDisplayControl` 中实现（只读视频流查看端为 `/screen` 的 `ScreenView`）。

### 15.4 字幕区域

- 字幕背景：半透明黑色条 `bg-black/40 backdrop-blur-sm`，置于底部约 1/4 位置。
- 中文字幕：`text-2xl font-normal text-techText`。
- 英文翻译：`text-base text-techMuted`，在中文下一行。
- 最大显示 3-4 行，自动滚动。

---

## 16. Meeting Table Visualization Rules (会议桌可视化)

### 16.1 布局

- 矩形会议桌居中，椭圆形或圆角矩形表示。
- 座位围绕桌边排列。
- 使用 CSS/SVG 绘制，非图片。

### 16.2 座位指示

- 每个座位：圆形或圆角矩形图标，44-56px。
- 座号标于图标内或下方。
- 座位名称标于图标下方。
- 座位标签必须保持可读，不在更新时移位。

### 16.3 缩放与自适应

- 会议桌可视化应适应容器尺寸，使用相对单位。
- 在 Admin 端可略小（卡片内），Display 端可较大。
- 使用稳定网格或表格隐喻。

### 16.4 座位状态着色映射

| 状态 | 颜色 | 效果 |
|------|------|------|
| 空座 / 空闲 | `text-techMuted` / `border-techBorder` | 静态，低亮 |
| 有人 / 签到 | `text-techText` / `bg-techCard` | 静态，正常亮度 |
| 等待签到 | `techAmber` | 静态 |
| 发言中 | `techCyan` + `shadow-cyan-glow` | 脉冲或发光动画 |
| 请求发言 (Hand-raised) | `techAmber` | 脉冲动画 |
| 离线 / 错误 | `techRose/40` | 半透明 |
| 投票中 | `techBlue` | 静态 |

**发言中状态推荐实现**:
```jsx
className="ring-2 ring-techCyan shadow-cyan-glow animate-pulse"
```

---

## 17. Seat Status Color Rules (座位状态颜色规则)

### 17.1 状态色表

| 状态 | Tailwind 类 |
|------|-------------|
| 空座 (Empty) | `text-techMuted border-techBorder` |
| 有人 (Occupied) | `text-techText bg-techCard` |
| 发言中 (Speaking) | `text-techCyan ring-2 ring-techCyan shadow-cyan-glow` |
| 请求发言 (Hand-raised) | `text-techAmber animate-pulse` |
| 离线 (Offline) | `text-techRose/40 opacity-60` |
| 投票中 (Voting) | `text-techBlue` |
| 已签到 (Checked-in) | `text-techGreen` |

### 17.2 规则

- 座位状态颜色不得与现有状态逻辑编码不同。
- 不在此视觉任务中编码新的座位业务状态。
- 空座使用低亮显示，发言中使用高亮+发光，突出当前焦点。
- 多个状态同时存在时（如有人+发言中），发言中优先级最高。

---

## 18. Transcript / Bilingual Transcription Display Rules (字幕/双语转录显示)

### 18.1 字幕流

- 实时字幕从左到右逐句出现。
- 每句独立显示，不滚动覆盖。
- 中文字幕在上，英文翻译在下。
- 字幕表面应为深色、可读、平静。

### 18.2 句子块样式

```jsx
<div className="mb-3">
  <p className="text-base text-techText">中文原文内容。</p>
  <p className="text-sm text-techMuted -mt-0.5">English translation.</p>
</div>
```

### 18.3 临时/最终状态

- 临时语音识别结果（interim）：视觉上更轻，颜色略淡 `text-techMuted`。
- 最终确认结果（final）：更稳定、更可读 `text-techText`。

### 18.4 时间戳

- 可选在句子块右上角显示 `text-xs text-techMuted/60`。

### 18.5 最大高度

- 字幕列表最大高度限制，超出滚动。
- 管理端：`max-h-64 overflow-y-auto`。
- 大屏端：底部固定区域自动换行。
- 避免紧凑行高降低座位平板可读性。
- 不修改字幕数据加载、持久化和 WebSocket 处理。

---

## 19. Dangerous Action Rules (危险操作规则)

### 19.1 危险操作定义

- 结束会议。
- 移除参会者。
- 删除会议记录。
- 清空投票。
- 取消发言。
- 断开系统连接。

### 19.2 视觉规则

- 危险按钮使用 `techRose` 色系。
- 所有危险操作需二次确认弹窗。
- 确认弹窗标题含 ⚠️ 或红色警示。

### 19.3 二次确认弹窗

```jsx
<div className="fixed inset-0 bg-black/60 flex items-center justify-center z-[100]">
  <div className="bg-techCard border border-techBorder rounded-lg p-6 max-w-sm w-full shadow-card-glow">
    <h3 className="text-lg font-semibold text-techRose mb-2">确认结束会议？</h3>
    <p className="text-sm text-techMuted mb-6">此操作不可撤销。</p>
    <div className="flex gap-3 justify-end">
      <button className="...secondary...">取消 Cancel</button>
      <button className="bg-techRose text-white ...danger...">确认结束 End</button>
    </div>
  </div>
</div>
```

### 19.4 布局规则

- 危险操作不应排列在常规主要操作旁，需间距或分组隔离。
- 危险填充色（`bg-techRose`）仅用于最终确认按钮或明确的破坏性主要操作。
- 确认弹窗默认焦点在"取消"按钮。
- 确认行为保持不变，除非后续行为任务明确更改。

### 19.5 Seat 平板特殊规则

- 危险操作按钮与主要操作按钮间距 ≥ 12px。
- 长按或滑动确认（未来可选项，本轮不实现）。

---

## 20. 13.3 inch Touch Target and Anti-Mistouch Rules (触控与防误触)

### 20.1 触摸目标最小尺寸

- 所有交互元素（按钮、开关、可点击图标、列表项）：**最小 44×44px**。
- 链接文字：最小 44px 行高，padding 扩展触摸区域。
- 表单输入框：最小高度 44px。
- 常用控件应大于最小尺寸。

### 20.2 间距

- 相邻可点击元素间距 ≥ 8px。
- 危险按钮与普通按钮间距 ≥ 12px。

### 20.3 触摸反馈

- 按下态：`active:scale-95`（微缩）或 `active:bg-techCyan/20`。
- 过渡：`transition-transform duration-150`。
- 触控设备应禁用 hover 效果（使用 `@media (hover: hover)` 或 `pointer-fine` 变体）。
- 重要状态变化必须可见，不能仅依赖 hover。

### 20.4 防误触策略

- 不可逆操作必须二次确认。
- 确认弹窗"取消"按钮在左/上（符合 Fitts 定律，接近手指自然落点）。
- 开关/Toggle 需有明确状态视觉反馈（颜色切换 + icon 变化）。
- 滑动操作需有阻力阈值（未来可选项，本轮不实现）。
- 非活动区域不应响应触摸。

---

## 21. `shared.tsx` Future Organization Rules (共享组件未来组织)

### 21.1 当前状态

`frontend/src/components/shared.tsx` 当前包含：

| 导出 | 类型 | 说明 |
|------|------|------|
| `isDemoControlsEnabled()` | function | 环境变量检测 |
| `ConnectionBadge` | component | 连接状态徽章（Wifi/Loader2/WifiOff）— 仍为浅色主题，未被页面组件直接导入 |
| `MeetingStatusBadge` | component | 会议状态徽章（active/pending/finished）— 仍为浅色主题，未被页面组件直接导入 |
| `useClock` | hook | 每秒更新的时钟 |
| `formatTime` | function | 时间格式化 (HH:MM AM/PM) |
| `formatDuration` | function | 持续时间格式化 (Xh Ym) |
| `timeAgo` | function | 相对时间 (Xs ago / Xm ago) |
| `parseBackendDate` | function | 后端 naive UTC 时间解析 |
| `formatTranscriptTime` | function | 字幕时间格式化 |
| `EmptyState` | component | 空状态占位（图标+标题+描述） |
| `LoadingState` | component | 骨架屏加载（可配置行数） |
| `DisconnectedOverlay` | component | 断连覆盖层（含重试按钮） |
| `SectionCard` | component | 通用区块卡片（标题栏+内容区） |
| `DualLabel` | component | 中英双标签（cn 主 + en 副标签） |
| `StatusBadge` | component | 状态徽章（online/speaking/waiting/offline/success/warning/danger/neutral） |
| `ActionButton` | component | 统一按钮（variant/size/touch/loading） |
| `PanelCard` | component | 通用面板卡片（带 variant 边框） |
| `MetricTile` | component | 指标磁贴 |
| `SectionHeader` | component | 区块标题行 |
| `TechEmptyState` | component | tech 风格空状态（cn/en + 可选操作） |

> ✅ `EmptyState`、`LoadingState`、`DisconnectedOverlay`、`SectionCard` 已于 2026-06-13 视觉一致性收尾轮迁移到 tech 深色主题（`bg-techCard`、`border-techBorder`、`text-techMuted`/`text-techText`）。`ConnectionBadge` 与 `MeetingStatusBadge` 仍为浅色主题（emerald/amber/red/slate），未被任何页面组件直接导入，详见 24.5。

### 21.2 未来组织方案（本轮不移动）

当 `shared.tsx` 过大时可按分区拆分：

| 建议文件 | 包含内容 |
|----------|----------|
| `shared/badge.tsx` | `ConnectionBadge`, `MeetingStatusBadge`, 其他状态徽章 |
| `shared/feedback.tsx` | `EmptyState`, `LoadingState`, `DisconnectedOverlay`, 错误边界 |
| `shared/layout.tsx` | `SectionCard`、`DualLabel`、其他布局组件（如拆分） |
| `shared/utils.ts` | `formatTime`, `formatDuration`, `timeAgo`, `isDemoControlsEnabled` |
| `shared/display.tsx` | 大屏专用组件 |

### 21.3 本轮约束

- **不移动任何现有组件**。
- **不新增 `DualLabel` 组件**。
- **不修改 `shared.tsx` 中的业务逻辑**。
- 仅当实现视觉冻结后续任务时，才将 shared 组件改为 tech 主题。

---

## 22. Deferred Features That Must Not Be Implemented Now (本轮禁止实现)

以下功能已在规范中提及，但**本轮绝对不实现**：

1. **`DualLabel` 组件** — 已在 `shared.tsx` 中实现（`cn`+`en` 双标签），不再属于待新增项。
2. **shared.tsx 拆分** — 分文件组织规范已定，但本轮不移动组件。
3. **shared.tsx 组件深色主题迁移** — 现有组件改用 tech 色系，本轮不改。
4. **会议列表页** — 完整的会议列表管理页面。
5. **完整议题系统** — 议题 CRUD、排序、状态流转。
6. **主持人控制大屏** — 已在 `/admin` Overview 工作区的 `HostDisplayControl` 组件中实现（经 127.0.0.1:8766 loopback Agent 激活 PowerPoint/SolidWorks/SmartDesk）；只读视频流查看端为 `/screen`（`ScreenView`）。
7. **权限系统** — 用户角色与权限控制。
8. **大屏字幕、当前议题、发言人展示** — Display 视图的完整功能。
9. **Next.js 迁移** — 当前使用 React + Vite，不迁移。
10. **shadcn/ui 引入** — 不引入该组件库。
11. **大规模替换组件 className** — 不为视觉 token 大规模改组件。
12. **页面级 CSS** — 不在 `index.css` 中添加页面级样式。
13. **后端 API 变更** — 任何 API 接口变更。
14. **数据库 schema 变更** — 任何数据模型变更。
15. **WebSocket 行为变更** — 任何实时通信协议变更。
16. **路由结构变更** — 任何前端路由变更。
17. **直接复制 v0-smartdesk 代码** — 不应从已有设计中直接复制代码。

---

## 23. Testing and Acceptance Checklist (测试与验收清单)

### 23.1 构建验证

- [ ] `npm run lint` — ESLint 无错误。
- [ ] `npm run typecheck` — TypeScript 类型检查通过。
- [ ] `npm run build` — Vite 构建成功。
- [ ] `npm test -- --run` — Vitest 单元测试全部通过。

### 23.2 E2E 验证（可选）

- [ ] `npm run e2e:speech` — Playwright 端到端测试。
- [ ] 注意：E2E 测试依赖 `127.0.0.1:8000` 后端服务，后端未启动时失败为预期行为。

### 23.3 视觉一致性检查

- [ ] `docs/FRONTEND_VISUAL_SPEC.md` 存在并覆盖 23 个章节。
- [ ] Tailwind 配置中包含所有 semantic tokens。
- [ ] `tailwind.config.js` theme.extend 包含 colors、boxShadow、backgroundImage。
- [ ] 所有页面使用 tech 深色色板。
- [ ] 中英双语覆盖所有用户可见标签（中文主，英文次）。
- [ ] 触摸目标 ≥ 44px（Seat 平板页面）。
- [ ] 危险操作用 techRose 色系并有二次确认。
- [ ] `index.css` 仅含安全全局 base 样式，无页面级 CSS。
- [ ] 未修改业务逻辑、API、WebSocket、路由、按钮 disabled 规则。
- [ ] 未实现任何 deferred 功能。

### 23.4 代码审查要点

- [ ] 没有在 JSX 中直接使用十六进制色值（应使用 Tailwind token）。
- [ ] 没有引用 `docs/` 下不相关文档。
- [ ] 没有修改 `docs/` 下非本任务指定的文档。
- [ ] 新增文件使用 UTF-8 编码。
- [ ] 文件编码一致性：所有源码和文档 UTF-8。

### 23.5 本轮验收标准

- [ ] 只修改允许的 3 类文件（`docs/FRONTEND_VISUAL_SPEC.md`, `frontend/tailwind.config.js`, `frontend/src/index.css`）。
- [ ] `docs/FRONTEND_VISUAL_SPEC.md` 存在，并覆盖全部 27 个要求章节。
- [ ] Tailwind 包含 SmartDesk semantic tokens。
- [ ] `index.css` 没有页面级 CSS。
- [ ] 没有修改业务逻辑、API、WebSocket、路由、按钮 disabled 状态逻辑。
- [ ] 没有实现 deferred 功能。
- [ ] lint / typecheck / build / unit test 至少实际尝试运行并记录结果。
- [ ] Playwright visual smoke test 覆盖三端目标视口截图验收。
- [ ] 浅色残留类名已被扫描并修复（或记录保留原因）。
- [ ] Seat 端所有主要交互按钮满足触控 ≥ 44px。
- [ ] Display 端所有文字满足 86 寸远距离可读性要求。

---

---

## 24. Final Visual Consistency Convention (本轮视觉收尾最终约定)

> **版本**: 1.1  
> **更新日期**: 2026-06-13  
> **范围**: `/admin`、`/seat/:seatId`、`/display` 三端视觉一致性收尾

### 24.1 三端状态颜色最终规则

| 状态 | Color Token | 效果 | 使用场景 |
|------|-------------|------|---------|
| 发言中 / Speaking | `techCyan` + `shadow-cyan-glow` | 可 pulse | 当前发言人、大屏活动状态 |
| 在线 / 已签到 / 成功 | `techGreen` | 静态或 pulse | 连接成功、签到完成、服务已处理 |
| 等待 / 待签到 / Pending | `techAmber` | 静态 | 待签到、等待中、投票待处理 |
| 结束 / 错误 / 危险 | `techRose` | 静态 | 会议结束、连接断开、错误提示 |
| 空座 / 离线 / 无内容 | `techMuted` / `techBorder` | 静态 | 空座、暂无内容、无数据 |
| 次要信息 | `techBlue` | 静态 | 次要提示、信息展示 |

Badge 半透明背景映射规则:
- 状态色背景 `bg-{color}/10`，边框 `border-{color}/30`，文字 `text-{color}`
- 例如 `bg-techCyan/10 border-techCyan/30 text-techCyan`

### 24.2 按钮最终规则

按钮通过 `shared.tsx` 中的 `ActionButton` 组件统一提供，variant 映射:

| Variant | 外观 | 用途 |
|---------|------|------|
| `primary` | `bg-techCyan text-techBg` | 主要操作、创建、确认、投票、开始 |
| `success` | `bg-techGreen text-white` | 启动会议、成功确认、处理完成 |
| `warning` | `bg-techAmber text-white` | 预载模型、关闭投票等警示操作 |
| `danger` | `bg-techRose text-white` | 结束会议、取消、危险操作 |
| `secondary` | `bg-techCard border-techBorder text-techText` | 取消、刷新、辅助操作 |
| `ghost` | `bg-transparent text-techText hover:bg-techCard` | 轻量操作 |

禁止：
- 在 JSX 中手写按钮样式（必须使用 ActionButton 或基于 ActionButton 扩展）
- 在按钮中直接使用 `bg-sky-600`、`bg-sky-100`、`bg-emerald-600` 等浅色类名
- 修改 ActionButton 的 `onClick`、`disabled`、`loading` 等业务逻辑

### 24.3 触控热区最终规则

Seat 平板（`/seat/:seatId`）所有交互元素遵守：

| 规则 | 要求 | 实现 |
|------|------|------|
| 最小触摸高度 | ≥ 44px | `min-h-[44px]` 或 `ActionButton size="lg"` |
| 按钮间距 | ≥ 8px | Tailwind `gap-2` 或 `gap-3` |
| 危险按钮间距 | ≥ 12px | 与普通按钮组之间使用 `gap-3` |
| 按下反馈 | 微缩动效 | `active:scale-95 transition-transform` |
| 禁用状态 | 半透明 + 不可点击 | `disabled:opacity-40 disabled:cursor-not-allowed` |
| 图标触摸容器 | 最小 44×44px | 图标居中，外包 `min-h-[44px] min-w-[44px] flex items-center justify-center` |

Seat 端已实现：
- 签到按钮: `ActionButton variant="primary" size="lg" touch`
- 投票选项: `min-h-[48px]`，`active:scale-[0.98]`
- 服务按钮: `min-h-[48px]`，`active:scale-[0.98]`
- 语音控制: `ActionButton variant="primary" size="lg" touch`

### 24.4 大屏字号最终规则

Display 视图（`/display`）远距离可读性要求：

| 元素 | 最小字号 | Class |
|------|----------|-------|
| 会议标题 | 36px (h1) | `text-4xl font-bold` |
| 投票标题 | 48px | `text-5xl font-bold` |
| 投票选项 | 30px | `text-3xl font-semibold` |
| 票数 / 百分比 | 24px | `text-2xl tabular-nums` |
| 总票数 | 48px | `text-5xl font-bold text-techCyan` |
| 进度条高度 | 16px | `h-4` |
| 状态徽章 | 13px | `text-xs` |
| 空状态图标 | 40px | `size-8` (lucide) |
| 按钮 | 16px + 44px min-h | `text-base` + `min-h-[44px]` |

大屏限制：
- 唯一操作：Refresh（刷新）按钮
- 不实现密集表格
- 不实现小按钮（< 40px height）
- 所有状态居中显示
- 会议结束结果"结果保留 / Results Preserved"提示醒目且居中

### 24.5 禁止使用的浅色残留类名

以下类名已从深色主题的三端组件中移除，禁止在新代码中使用：

```
❌ bg-white           → bg-techCard / bg-techSurface / bg-techBg
❌ bg-slate-50        → bg-techBg
❌ bg-slate-100       → bg-techCard / bg-techCardSoft
❌ bg-sky-50          → bg-techCyan/10
❌ bg-sky-100         → bg-techCardSoft
❌ bg-sky-600         → ActionButton variant="primary"
❌ bg-emerald-600     → ActionButton variant="success"
❌ bg-amber-600       → ActionButton variant="warning"
❌ bg-rose-50         → bg-techRose/10
❌ bg-red-50          → bg-techRose/10
❌ text-slate-800     → text-techText
❌ text-slate-700     → text-techText
❌ text-slate-600     → text-techMuted
❌ text-slate-500     → text-techMuted
❌ text-slate-400     → text-techMuted
❌ text-sky-500       → text-techCyan
❌ text-sky-600       → text-techCyan
❌ text-sky-700       → text-techCyan
❌ text-rose-600      → text-techRose
❌ text-rose-700      → text-techRose
❌ text-emerald-600   → text-techGreen
❌ text-emerald-700   → text-techGreen
❌ text-amber-600     → text-techAmber
❌ text-amber-700     → text-techAmber
❌ border-slate-200   → border-techBorder
❌ border-slate-300   → border-techBorder
❌ border-sky-200     → border-techCyan/30
❌ border-rose-200    → border-techRose/30
❌ border-red-200     → border-techRose/30
❌ border-amber-100   → border-techAmber/30
❌ border-sky-800     → border-techCyan/30
❌ shadow-sm          → shadow-card-glow
```

> ✅ `shared.tsx` 中的 `SectionCard`、`EmptyState`、`LoadingState`、`DisconnectedOverlay` 已于 2026-06-13 迁移到 tech 深色主题。  
> ⚠️ `ConnectionBadge` 和 `MeetingStatusBadge` 虽仍为浅色，但当前未被任何页面组件直接导入（每个端有各自的内联版本），在未来清理 shared.tsx 时可一并移除。

### 24.6 表单输入框最终样式

所有表单输入框统一使用：

```tsx
className="w-full bg-techSurface border border-techBorder rounded-lg px-4 py-2.5 text-sm text-techText placeholder:text-techMuted/60 focus:outline-none focus:border-techCyan focus:ring-1 focus:ring-techCyan/30 transition-colors"
```

- 高度不低于 40px（`py-2.5` = 10px padding + ~20px text = ~40px）
- 禁用 `ring-2` 改用 `ring-1` 避免过重外发光
- 占位符颜色 `techMuted/60`
- 多行文本域（textarea）使用相同样式

### 24.7 双语文案最终规则

中英文优先级：
1. 中文为主 —— 标题、按钮、核心状态
2. 英文为辅 —— 辅助说明小字、`text-xs font-mono uppercase tracking-wider text-techMuted`
3. 英文使用英文半角标点，中文使用全角标点
4. 中英文混排时之间加一个空格（如"创建会议 Create Meeting"）

统一文案映射：

| 中文 | English | 位置 |
|------|---------|------|
| 主持人控制台 | Host Console | Admin Header 品牌区 |
| 会议大屏 | Command Display | Display Header |
| 座位 N | Seat N | Seat Header |
| 会议状态 | Meeting Status | Admin Header badge |
| 连接状态 | Connection | Header 连接徽章 |
| 发言中 | Speaking | 发言状态 |
| 已签到 | Checked In | 签到状态 |
| 待签到 | Waiting | 等待签到 |
| 空座 | Vacant | 空座位 |
| 进行中 | In Progress / Active | 会议活动状态 |
| 已结束 | Ended | 会议结束 |
| 暂无投票 | No Vote | 投票空状态 |
| 暂无字幕 | No Transcript | 字幕空状态 |
| 暂无请求 | No Requests | 服务请求空状态 |
| 会议结果 | Meeting Results | 结果面板标题 |
| 结果保留 | Results Preserved | 大屏结束提示 |

### 24.8 视觉修改后测试清单

每轮视觉修改后必须运行：

1. `npm run lint` — ESLint 检查
2. `npm run typecheck` — TypeScript 类型检查
3. `npm test -- --run` — Vitest 单元测试
4. `npm run build` — Vite 生产构建

如果 E2E 测试（Playwright）因后端未运行而失败，如实记录环境失败原因。禁止：
- 修改 Playwright 配置掩盖环境失败
- 删除关键业务断言使测试通过
- 修改按钮 `disabled` 规则使交互测试通过

### 24.9 最终验收视口与截图要求

本轮视觉验收覆盖以下硬件视口：

#### /admin 主持人端
| 视口 | 场景 | 要求 |
|------|------|------|
| 2560 × 1440 | 27寸桌面显示器 | 信息密度充足，顶部状态栏不换行，会议桌居中清晰 |
| 1920 × 1080 | 标准全高清显示器 | 投票、服务、字幕卡片不被挤压，危险操作按钮醒目 |

#### /seat/:seatId 座位端
| 视口 | 场景 | 要求 |
|------|------|------|
| 1920 × 1080 | 13.3寸触控屏 (横屏) | 主要按钮 ≥ 44px，触控区域间距 ≥ 8px，首屏可读当前状态 |
| 1366 × 768 | 常见笔记本分辨率 | 触控元素不缩小，允许纵向滚动，首屏能看懂状态 |
| 1280 × 800 | 小型平板/笔记本 | 按钮触控友好，服务/投票区域不被裁剪 |

#### /display 中央大屏
| 视口 | 场景 | 要求 |
|------|------|------|
| 3840 × 2160 | 86寸会议电视 (4K) | 大字号 (≥ 36px)，少控件，投票结果远距离可读 |
| 2560 × 1440 | 中档大屏/投影 | 状态居中，无密集表格，Refresh 为唯一操作 |
| 1920 × 1080 | 标准投影/大屏 | 结束会议后"结果保留"提示醒目居中 |

### 24.10 截图验收方法

截图通过 Playwright visual smoke test (`frontend/e2e/visual-smoke.spec.ts`) 自动生成：

1. 打开 `/admin` → 设置 1920×1080 → 截图 `visual-admin-1920x1080.png`
2. 打开 `/admin` → 设置 2560×1440 → 截图 `visual-admin-2560x1440.png`
3. 打开 `/seat/1` → 设置 1280×800 → 截图 `visual-seat-1-1280x800.png`
4. 打开 `/seat/1` → 设置 1920×1080 → 截图 `visual-seat-1-1920x1080.png`
5. 打开 `/seat/1` → 设置 1366×768 → 截图 `visual-seat-1-1366x768.png`
6. 打开 `/display` → 设置 1920×1080 → 截图 `visual-display-1920x1080.png`
7. 打开 `/display` → 设置 3840×2160 → 截图 `visual-display-3840x2160.png`

截图建议保存在 `frontend/test-results/visual/` 或 Playwright 默认
`frontend/test-results/` 下，不纳入版本控制。

### 24.11 13.3 寸触控验收要求 (Seat 端)

| 检查项 | 要求 |
|--------|------|
| 签到按钮 | `min-height ≥ 44px`，`touch` prop + `size="lg"` |
| 投票选项 | `min-h-[48px]`，`active:scale-[0.98]` |
| 提交投票 | `ActionButton variant="primary" size="lg" touch` |
| 服务呼叫按钮 | `min-h-[48px]`，`active:scale-[0.98]` |
| 取消服务 | `ActionButton variant="danger" size="md" touch` |
| 语音识别按钮 | `ActionButton variant="primary" size="lg" touch` |
| 错误关闭按钮 | `min-h-[44px] min-w-[44px]` |
| 返回按钮 | `min-h-[44px]` |
| 按钮间距 | `gap-2` 或 `gap-3` (≥ 8px) |
| 危险按钮间距 | 与普通按钮组之间使用 `gap-3` (≥ 12px) |
| 按下反馈 | `active:scale-95` 或 `active:scale-[0.98]` |
| 禁用状态 | `opacity-40 cursor-not-allowed` |

### 24.12 86 寸大屏可读性要求 (Display 端)

| 检查项 | 最小尺寸 |
|--------|----------|
| 会议标题字号 | `text-4xl` (36px) |
| 投票标题字号 | `text-5xl` (48px) |
| 投票选项字号 | `text-3xl` (30px) |
| 票数/百分比 | `text-2xl` (24px) |
| 总票数 | `text-5xl font-bold text-techCyan` (48px) |
| 进度条高度 | `h-4` (16px) |
| 按钮高度 | `min-h-[44px]`，`size="lg"` |
| 按钮文字 | `text-base` (16px) |
| 空状态图标 | 40px lucide icon |
| 交互控件 | 仅 Refresh 按钮，无密集表格，无小按钮 |

### 24.13 Playwright Visual Smoke Test 要求

`frontend/e2e/visual-smoke.spec.ts` ：

- 不依赖后端运行（页面 loading/empty/error 状态也可验证渲染）
- 7 个测试用例覆盖三端所有目标视口
- 使用 `domcontentloaded` 等待策略
- 检查 `body` 非空及关键文本可见（如 "Seat 1"、"Command Display"）
- 截图保存到 `frontend/test-results/visual/` 或 Playwright 默认
  `frontend/test-results/`
- 如果后端不可用，测试记录环境限制并如实报告，不假装通过

### 24.14 停止大面积视觉重构

本规范 v1.1 起，SmartDesk 前端视觉系统已冻结。此后：

- 禁止大规模替换组件 className
- 禁止新增页面级 CSS
- 禁止引入新的 UI 组件库
- 禁止迁移技术栈（React + Vite 保持不变）
- 禁止在视觉验收任务中修改业务逻辑、API、WebSocket、路由、按钮 disabled 规则
- 仅允许小范围视觉 bug 修复（浅色残留、溢出、文案等）
- 仅允许与真实硬件联调相关的视觉调整
- 所有视觉修改必须更新本文档对应章节

---

> **文档结束** — 本规范代表 SmartDesk 前端视觉系统冻结状态（v1.1）。后续所有 UI 开发应以此规范为唯一视觉参考，任何偏离需经团队评审并更新本文档。
