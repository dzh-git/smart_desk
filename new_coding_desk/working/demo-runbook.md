# SmartDesk v1.0 — Demo Runbook / 演示脚本

## 环境要求

| 环境 | 版本要求 | 验证命令 |
|------|---------|---------|
| Python | ≥ 3.10 | `python --version` |
| Node.js | ≥ 18 | `node --version` |
| npm | ≥ 9 | `npm --version` |

## 一键启动

在项目根目录执行：

```powershell
.\start.bat
```

启动脚本会自动：
1. 清理残留进程（按端口 8000、5173）
2. 启动后端 FastAPI（http://127.0.0.1:8000）
3. 启动前端 Vite 开发服务器（http://127.0.0.1:5173）
4. 打开浏览器访问前端

### 环境变量（已内置于 start.bat）

| 变量 | 值 | 作用 |
|------|-----|------|
| `ENABLE_DEMO_SEED` | `true` | 启动时自动创建演示会议、座位、议程和与会者 |
| `ENABLE_DEMO_SEAT_API` | `true` | 启用开发座位模拟接口（占用/释放座位） |
| `VITE_ENABLE_DEMO_CONTROLS` | `true` | 前端显示 Demo 控制按钮（占座、座位预览切换） |

## 访问地址

| 页面 | 地址 |
|------|------|
| 管理端 | http://127.0.0.1:5173 |
| 座位端 (座位 5) | http://127.0.0.1:5173/?seat=5 |
| API 文档 | http://127.0.0.1:8000/docs |
| WebSocket 协议 | docs/WEBSOCKET_PROTOCOL.md |

## 停止方式

```powershell
.\kill.bat
```

或用 `Ctrl+C` 分别关闭两个终端窗口（SmartDesk-Backend / SmartDesk-Frontend）。

---

## 完整演示脚本（8 步，约 5 分钟）

### 步骤 1: 启动项目

```powershell
.\start.bat
```

验证：
- [ ] 两个终端窗口分别显示 "SmartDesk-Backend" 和 "SmartDesk-Frontend"
- [ ] 后端终端最后输出: `Uvicorn running on http://127.0.0.1:8000`
- [ ] 前端终端最后输出: `Local: http://localhost:5173/`
- [ ] 浏览器自动打开管理端页面

---

### 步骤 2: 管理端查看默认数据

**地址：** http://127.0.0.1:5173

启动后 `ENABLE_DEMO_SEED=true` 自动创建的演示数据如下：

| 数据项 | 实际内容 |
|--------|---------|
| **会议** | "2026年第二季度产品评审"（已开始，状态 active） |
| **座位** | 10 个座位网格 |
| **与会者** | 8 名：张伟（产品总监）、李娜（技术经理）、王强（市场总监）、陈静（前端工程师）、刘洋（后端工程师）、赵磊（测试工程师）、孙莉（设计师）、周明（运营主管） |
| **座位状态** | 1-4 已签到（对应张伟、李娜、王强、陈静）；5-6 occupied_unchecked；7-10 空闲 |
| **发言人** | 座位 1（张伟） |
| **议程** | 5 项：开场致辞、产品路线图回顾、技术方案评审、市场策略讨论、总结与下一步计划 |
| **投票** | 1 个 open vote："是否批准2026年Q3产品路线图"（选项：批准 / 修改后批准 / 不批准） |
| **服务呼叫** | 1 个 pending：座位 3（王强）请求 Coffee（尚未处理） |
| **翻译历史** | 2 条中英双语翻译记录 |

验证：
- [ ] 页面标题显示"2026年第二季度产品评审"和 "In Progress" 状态标签
- [ ] 右上角连接状态显示 "Connected"（WebSocket 已连接）
- [ ] 座位网格：1-4 显示已签到姓名、5-6 橙色待签到、7-10 灰色空闲
- [ ] 右侧议程面板显示 5 项议程
- [ ] VotePanel 显示当前 open vote 标题和选项统计
- [ ] ServicePanel 显示座位 3 的 pending Coffee 请求
- [ ] 页面底部翻译面板显示 2 条双语翻译记录
- [ ] 统计卡片：Attendees（4/10）、Speaker（张伟）、Requests（1）
  > 注：分母 10 表示 10 个座位，而非与会者总数（8 名）。这是管理端统计卡片 `${checkedIn}/10` 的展示方式。

---

### 步骤 3: 座位 5 入座/签到

**保持管理端在浏览器中打开**，新建标签页访问：
http://127.0.0.1:5173/?seat=5

验证：
- [ ] 页面标题显示 "Seat 5" 和会议名称
- [ ] 状态卡片显示 "Seat 5 — Check-in Required"（橙色，非空闲）

> 座位 5 初始状态为 `occupied_unchecked`，**不需要**先点击 Occupy。直接选择与会者签到即可。

**选择一个与会者**（如 "刘洋 后端工程师"），点击 "Confirm Check-in"

验证：
- [ ] 状态卡片更新为已签到（显示"刘洋"和 "Checked In" 标签）
- [ ] 签名头像显示 "刘洋" 的首字母

**切换回管理端标签页**

验证：
- [ ] 座位网格中座位 5 显示"刘洋"
- [ ] Attendees 统计从 "4/10" 变为 "5/10"
  > 注：分母 10 固定不变，因为统计卡展示 `${checkedIn}/10`。实际与会者共 8 名。

> **可选：** 如需重置座位 5 的状态，可在座位端使用 "Vacate Seat (Demo)" 按钮释放座位，再使用 "Occupy Seat (Demo)" 重新占座。

---

### 步骤 4: 座位端提交/修改投票

**切换回座位端** http://127.0.0.1:5173/?seat=5

验证：
- [ ] "Active Vote" 区域显示（标题："是否批准2026年Q3产品路线图"）
- [ ] 三个选项：批准、修改后批准、不批准
- [ ] 统计条显示当前各选项比例（初始均为 0，因为尚无投票记录）

**选择一个选项**（如"批准"），点击 **"Submit Vote"**

验证：
- [ ] 按钮变为 "Update Vote"
- [ ] 统计条更新（"批准" 增加 1 票）
- [ ] 选项旁显示 "Your vote" 标签

**修改投票：** 选择另一个选项（如"修改后批准"），点击 **"Update Vote"**

验证：
- [ ] 统计更新，旧选项减 1，新选项加 1
- [ ] "Your vote" 标签移至新选项
- [ ] 页面底部显示 "Your current vote: 修改后批准"

---

### 步骤 5: 管理端关闭投票 → 创建新投票

**切换回管理端**

#### 5a. 关闭当前投票

验证：
- [ ] 投票统计已自动刷新（显示座位 5 提交后的最新票数）
- [ ] 底部有关闭投票按钮

**点击 "Close Vote"**

验证：
- [ ] 投票状态变为 "Closed"
- [ ] Close Vote 按钮消失
- [ ] 统计条保持显示（只读）

#### 5b. 创建新投票

关闭投票后，"Create Vote" 表单会自动出现（此前因存在 open vote 而被隐藏）。

1. 输入标题，如："是否进入下一个演示环节？"
2. 输入选项："立即继续"、"稍等片刻"
3. 可勾选 "Anonymous vote"（匿名投票）
4. 点击 **"Create Vote"**

验证：
- [ ] Create Vote 表单消失
- [ ] VotePanel 显示新投票统计（初始均为 0%）

---

### 步骤 6: 座位端对新投票投票

**切换回座位端** http://127.0.0.1:5173/?seat=5

验证：
- [ ] 显示新的投票标题："是否进入下一个演示环节？"
- [ ] 选项："立即继续"、"稍等片刻"

**选择"立即继续"**，点击 **"Submit Vote"**

验证：
- [ ] 按钮变为 "Update Vote"
- [ ] 统计条更新

---

### 步骤 7: 座位端创建服务呼叫

**保持座位 5 页面**，确认 "Service Request" 区域可见（座位 5 没有当前 pending call，因此显示服务按钮）。

验证：
- [ ] 4 个服务按钮：Coffee、Tea、Water、Other

**点击 "Coffee"**

验证：
- [ ] 服务按钮区域被 "Coffee — Pending" 状态卡片替代
- [ ] 显示 "Your request has been sent"
- [ ] 显示 "Cancel" 按钮

---

### 步骤 8: 管理端处理服务呼叫 + WebSocket 验证

#### 8a. 处理服务呼叫

**切换回管理端**

验证：
- [ ] "Service Calls" 面板显示两个条目：
  - 初始的座位 3 Coffee（Pending）
  - 刚创建的座位 5 Coffee（Pending）
- [ ] 每个 Pending 条目旁有 "Resolve" 按钮
- [ ] Requests 统计显示 "2"

**点击座位 5 的 "Resolve"**

验证：
- [ ] 座位 5 的请求状态变为 "Resolved"（或从列表中消失）
- [ ] Requests 统计从 "2" 变为 "1"

#### 8b. 验证 WebSocket 自动刷新总结

在整个演示过程中，以下 WebSocket 驱动的自动刷新已隐式验证：

| 操作 | 事件 | 自动刷新 |
|------|------|---------|
| 步骤 3: 签到 | `check_in` | 管理端座位网格更新 |
| 步骤 3: 可选 demo 占座 | `seat_occupied` | 管理端座位状态更新（仅发生在 vacant → occupied_unchecked 时） |
| 步骤 4: 提交/修改投票 | `vote_updated` | 两端统计同步 |
| 步骤 5a: 关闭投票 | `vote_closed` | 两端投票状态同步 |
| 步骤 5b: 创建投票 | `vote_created` | 管理端表单消失 → 统计展示；座位端自动出现投票 |
| 步骤 7: 创建服务呼叫 | `service_call_created` | 管理端 Service Calls 面板更新 |
| 步骤 8a: 处理服务呼叫 | `service_call_resolved` | 管理端列表更新 |

如果某个面板未自动更新，可以点击右上角 `Refresh` 按钮手动触发全量刷新。

---

## 语音演示流程（Phase 7 — 实时转录）

> **前置条件**：Python 语音依赖已安装（`pip install -r requirements.txt`），模型文件已下载至 `models/`。首次启动时后端自动检查依赖和模型。

### 步骤 S1: 确认 Speaker Seat

**管理端** http://localhost:5173

验证：
- [ ] 页头显示 "Speaking" 标签（默认 Speaker 为座位 1 —— 张伟）
- [ ] 如需切换 Speaker Seat，点击座位卡片上的麦克风图标

### 步骤 S2: 打开 Speaker Seat 座位端

```
http://localhost:5173/?seat=1
```

验证：
- [ ] 页面标题显示 "Seat 1" 和会议名称
- [ ] "Voice Recognition" 区域：Speaker Seat → 显示 Start 按钮
- [ ] 非 Speaker Seat → 显示 "Only speaker seat can stream audio"（只读）

### 步骤 S3: 授权麦克风并开始录音

1. 点击 **"Start"** 按钮
2. 浏览器弹出麦克风权限请求，选择"允许"
3. 状态变化：`requesting_microphone` → `connecting_speech_ws` → `recording`

验证：
- [ ] "Recording" 标签（红色脉冲圆点）显示
- [ ] "Streaming audio..." 状态文字
- [ ] 出现 **Stop** 和 **Cancel** 按钮
- [ ] Start 按钮消失

> 如果提示 "Microphone not supported"，请使用 Chrome 或 Edge。
> 如果提示 "Microphone access denied"，检查系统麦克风设置：设置 → 隐私和安全 → 麦克风。

### 步骤 S4: 说话

对着麦克风说一段话（中文普通话或英文，约 5–10 秒）。

### 步骤 S5: 管理端查看实时 interim

**切换回管理端**（或分屏查看）

验证：
- [ ] "Bilingual Transcript" 面板中出现新的实时字幕行
- [ ] interim 行显示为：斜体、浅灰色、带旋转加载指示器
- [ ] interim 显示在 final 历史记录之上
- [ ] 随着说话持续，interim 文本更新（revision 递增）

### 步骤 S6: Stop → 查看 final 翻译

**切换回座位端**，点击 **"Stop"**

验证：
- [ ] "Recording" 标签消失，返回 idle 状态（Start 按钮重新出现）
- [ ] 已发送 `end_hint` → 后端 finalize

**切换到管理端**

验证：
- [ ] interim 消失
- [ ] 新的 final 双语记录出现在 Transcript Panel（带时间戳和语言标签）

### 步骤 S7: 验证持久化记录

在浏览器中打开：
```
http://localhost:8000/api/translations?meeting_id=1
```

或通过 Swagger UI 查看。

验证：
- [ ] 返回的 entries 列表包含刚完成的翻译记录
- [ ] 包含 `source_text` 和 `translated_text` 字段
- [ ] `created_at` 时间正确

### 步骤 S8: 切换 Speaker Seat

**管理端**点击另一个座位（如座位 2）的麦克风图标设置为 Speaker Seat

验证：
- [ ] 原 Speaker Seat（座位 1）的 "Speaking" 标签消失
- [ ] 新座位（座位 2）出现 "Speaking" 标签
- [ ] 管理端 Transcript Panel 中旧的 interim 被移除（收到 `translation_interim_cancelled`）

**在座位 1 页面**（原 Speaker Seat）：
- [ ] Voice Recognition 区域显示 "Only speaker seat can stream audio"
- [ ] 旧 WS 连接已关闭

**打开新 Speaker Seat 页面** `http://localhost:5173/?seat=2`：
- [ ] 签到后（如需），可点击 Start 开始新的录音会话

---

## 语音演示预期状态对照

| 状态 | 座位端（Speaker） | 管理端 Transcript Panel |
|---|---|---|
| Idle | "Click Start to begin speaking" + Start 按钮 | final 历史展示 |
| Requesting mic | "Requesting microphone access..." | 无变化 |
| Connecting WS | "Connecting to speech service..." | 无变化 |
| Recording | 红色脉冲圆点 + "Recording" + Stop/Cancel | interim 行（斜体 + spinner + 浅色） |
| Stopping | "Stopping..." | interim → final 过渡 |
| Error | 错误消息 + Retry 按钮 | 无变化 |
| Not speaker | "Only speaker seat can stream audio" | — |

---

## 演示完成

```powershell
.\kill.bat
```

## 已知非阻塞问题

详见 `working/deferred-issues.md`，摘要如下：

| # | 问题 | 影响 |
|---|------|------|
| 1 | shared.tsx 混合导出打断 HMR | 开发体验偶发全页刷新 |
| 2 | lucide-react 跳过预打包 | 冷启动 +100~200ms |
| 3 | 无 SVG favicon | 标签页无图标 |
| 4 | 首次测试 jsdom 启动 34s | CI +45s |
| 5 | WebSocket 事件触发全量 HTTP 刷新 | 低影响，高频场景可优化 |
| 6 | "Waiting for Meeting" 状态无自动检测 | 需手动点 Refresh |
| 7 | 服务呼叫操作无骨架屏 | 按钮 spinner 足够用 |
| 8 | 投票按姓名匹配与会者 ID | 重名时异常 |
| 9 | "Retry Now" 不触发 WS 重连 | 等效于刷新数据 |
| 10 | 无 stale-interim 超时清理 | 刷新页面即可清除 |
| 11 | 首次模型加载慢（10–60 秒） | 演示前预热或提前告知 |

所有问题均不影响核心演示流程。语音演示需确保模型已下载（见上述前置条件）。
