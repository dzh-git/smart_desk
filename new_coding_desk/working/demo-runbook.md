# SmartDesk 演示手册 — 语音功能完整演示

> **版本**: Task 118 (Phase 08)
> **最后更新**: 2026-06-07

---

## 目录

1. [环境要求](#1-环境要求)
2. [启动系统](#2-启动系统)
3. [语音识别演示步骤](#3-语音识别演示步骤)
4. [演示验证清单](#4-演示验证清单)
5. [常见问题](#5-常见问题)
6. [故障排除](#6-故障排除)

---

## 1. 环境要求

### 硬件
- Windows 10/11 系统
- 麦克风（内置或外接）
- 屏幕分辨率 ≥ 1280×720

### 软件
- Python 3.12+
- Node.js 20+
- 现代浏览器（Chrome 120+ / Edge 120+）

### Python 依赖
```bash
pip install -r requirements.txt
```

关键包：`torch`, `funasr`, `numpy`, `scipy`, `soundfile`, `fastapi`, `uvicorn`, `sqlalchemy`

### 语音模型

系统使用 SenseVoice 和 Paraformer 模型进行中文语音识别。模型会在首次语音流启动时自动下载（需联网）。

如果模型未下载，后端在启动日志中会提示：
```
[WARN] Speech models:
  Paraformer Streaming: NOT found
  ...
→ 见下方模型下载说明
```

**模型下载**（手动，可选）：
```bash
cd models
# Paraformer 流式模型
git clone https://huggingface.co/funasr/paraformer-zh-streaming
# FSMN-VAD
git clone https://huggingface.co/funasr/fsmn-vad
```

> **注意**: 模型缺失不会阻止系统启动，但语音识别功能在首次音频流时会加载模型（首次约 30-60 秒加载时间）。

---

## 2. 启动系统

### 方式一：双击 `start.bat`（推荐）

```bat
# start.bat 自动执行：
# 1. 清理 8000/5173 端口残留进程
# 2. 检查 Python 依赖
# 3. 启动后端 (uvicorn, port 8000)
# 4. 启动前端 (Vite, port 5173)
# 5. 打开浏览器访问 http://localhost:5173
```

启动后终端会显示：

```
==========================================
  SmartDesk is starting up!

  Frontend: http://localhost:5173
  API:      http://localhost:8000
  Docs:     http://localhost:8000/docs

  Demo controls enabled:
    - Auto-seed meeting data
    - Auto-create demo meeting if no active meeting exists
    - Seat API controls
    - Demo seat preview
==========================================
```

### 方式二：手动启动

```bash
# 终端 1：后端
set ENABLE_DEMO_SEED=true
set ENABLE_DEMO_SEED_WHEN_NO_ACTIVE=true
set ENABLE_DEMO_SEAT_API=true
set VITE_ENABLE_DEMO_CONTROLS=true
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000

# 终端 2：前端
cd frontend
set VITE_ENABLE_DEMO_CONTROLS=true
npm run dev -- --host 127.0.0.1
```

### 停止系统

双击 `kill.bat`，或手动关闭两个终端窗口。

---

## 3. 语音识别演示步骤

### 步骤 1：启动系统

双击 `start.bat`，等待约 10-15 秒直到终端显示启动完成。

验证所有服务正常运行：
- http://127.0.0.1:8000 → 显示 Smart Desk 根页面 ✅
- http://127.0.0.1:8000/api/health → `{"status":"ok"}` ✅
- http://127.0.0.1:5173 → 显示 SmartDesk 管理端页面 ✅

### 步骤 2：打开管理端

浏览器打开 http://127.0.0.1:5173/

预期看到：
- 顶部标题栏显示 "2026年第二季度产品评审"
- 状态徽章：`In Progress` + `Connected`
- 座位概览：10 个座位（4 人已签到，2 人占用，4 人空闲）
- 右侧议程列表（5 项）、投票、服务请求
- 底部 Bilingual Transcript 区域

### 步骤 3：打开座位端

在新标签页中打开 http://127.0.0.1:5173/?seat=1

预期看到：
- 标题：Seat 1 — 2026年第二季度产品评审
- 状态：`Online`、`Speaking` 徽章
- 参会人：张伟（产品总监）— 已签到、Speaker
- **Voice Recognition** 区域可见
- "Click Start to begin speaking" 提示文字
- **Start** 按钮可以点击

### 步骤 4：确认 Seat 1 是 Speaker Seat

管理端可以看到：
- Seat 1 在座位图中带有 🎤 麦克风图标
- 指标卡显示 Speaker: 张伟

如果 Speaker Seat 不是 Seat 1，通过 API 设置：
```bash
curl -X POST http://127.0.0.1:8000/api/seats/speaker \
  -H "Content-Type: application/json" \
  -d '{"seat_id": 1}'
```

### 步骤 5：开始语音识别

在 Seat 1 页面点击 **Start** 按钮。

预期流程：
1. 按钮变为禁用状态，显示 "Requesting microphone access..."
2. 浏览器弹出麦克风权限请求 → 点击 **允许**
3. 状态变为 "Connecting to speech service..."
4. 状态变为 "Streaming audio..."，显示红色脉冲 **Recording** 徽章
5. **Stop** 和 **Cancel** 按钮出现

### 步骤 6：说话或播放音频

对着麦克风说中文，或播放预先录制的音频文件。

实时效果：
- 管理端的 **Bilingual Transcript** 区域会显示两行字幕（live caption）
- 第一行（灰色）：已提交的前一句
- 第二行（黑色）：当前正在识别的句子
- 字幕由后端自动添加标点并分句

### 步骤 7：管理端查看实时字幕

切换回管理端标签页（http://127.0.0.1:5173/）

预期看到：
- Bilingual Transcript 区域顶部出现 live caption 块
- caption 块包含 speaker 头像和实时更新的两行中文
- 每一行默认不超过 31 个字符（含标点），自动换行；可通过后端配置调整
- 无长字符串堆积现象

### 步骤 8：停止录音

在 Seat 1 页面点击 **Stop** 按钮。

预期：
- 录音状态立即结束
- live caption 从管理端消失
- 几秒后，最终识别结果出现在 Bilingual Transcript 的"历史记录"区
- 最终记录包含带标点的中文识别文本；翻译字段按当前后端能力显示，第一版不以翻译质量作为验收目标
- 管理端和座位端的 Transcript 区域同步显示

### 步骤 9：验证数据一致性

通过 API 查看持久化的翻译记录：
```bash
curl http://127.0.0.1:8000/api/translations?meeting_id=MEETING_ID
```

预期：
- `source_text` 与前端 DOM 显示的文本一致
- `utterance_id` 与 WS 消息中的一致
- 数据库、WebSocket、DOM 三端文本完全一致

---

## 4. 演示验证清单

| # | 验证项 | 方法 | 预期结果 |
|---|--------|------|----------|
| 1 | 启动 | 双击 `start.bat` | 后端 + 前端正常启动 |
| 2 | 管理端可访问 | 访问 `http://localhost:5173/` | 页面加载，无白屏 |
| 3 | 座位端可访问 | 访问 `http://localhost:5173/?seat=1` | 页面加载，无白屏 |
| 4 | Active Meeting | 查看顶端 | "2026年第二季度产品评审" |
| 5 | Speaker Seat | 查看管理端指标卡 | Speaker: 张伟 |
| 6 | 语音按钮状态 | Seat 1 页面 | Start 按钮可点击 |
| 7 | 非 Speaker 提示 | `/?seat=2` 页面 | "Only speaker seat can stream audio" |
| 8 | 连接状态 | Start 后 UI | recording 状态 + 脉冲动画 |
| 9 | 实时字幕 | 管理端 | live caption 两行刷新 |
| 10 | 最终记录 | Stop 后 | 历史区域出现 final 记录 |
| 11 | 控制台错误 | F12 Console | 无 error 输出 |
| 12 | 停止系统 | `kill.bat` | 8000/5173 端口释放 |
| 13 | E2E 测试 | `npm run e2e:speech` | 全部通过 |

---

## 5. 常见问题

### Q: 页面一直显示 "Waiting for Meeting"
确保 `ENABLE_DEMO_SEED=true` 和 `ENABLE_DEMO_SEED_WHEN_NO_ACTIVE=true` 已设置。
检查 `http://localhost:8000/api/meetings/active` 返回 active meeting。

### Q: 语音 Start 按钮不可点击
需要满足：
1. 座位已签到 (Checked In)
2. 该座位是 Speaker Seat
3. WebSocket 已连接 (Online)
4. 浏览器支持 `getUserMedia`

### Q: 录音后字幕无显示
1. 检查浏览器是否授权麦克风
2. 检查后端日志是否有 ASR 错误
3. 首次加载模型可能需要 30-60 秒

### Q: 识别文本不准
ASR 准确率不是本演示版的验收标准。模型输出不精确属于正常现象。
准确率取决于模型、音频质量和环境噪声；当前阶段不承诺准确率。
生产部署应使用定制微调模型或更高质量的 ASR 服务。

### Q: 前端不显示 Demo 控制 (Occupy/Vacate/Seat Preview)
确保启动前端时设置了 `VITE_ENABLE_DEMO_CONTROLS=true`。
使用 `start.bat` 启动时已自动设置。手动启动时需要 `set VITE_ENABLE_DEMO_CONTROLS=true`。

### Q: 模型下载慢或失败
系统使用 HuggingFace 的 Paraformer-zh-streaming 模型（约 70MB）。
自动下载在首次语音流时触发。如网络不畅，可以：
1. 代理设置：`set HTTPS_PROXY=http://proxy:port`
2. 手动下载放入 `models/` 目录
3. 使用 ModelScope 镜像

---

## 6. 故障排除

### 端口被占用
```bash
# 查看占用
netstat -ano | findstr ":8000"
netstat -ano | findstr ":5173"

# 手动终止
taskkill /PID <PID> /F
```

### 数据库冲突
如果页面显示异常数据，删除 `test.db` 后重启：
```bash
del test.db
# 然后重启 start.bat
```

### 后端模型加载失败
在启动日志中检查模型检查结果。如果显示模型缺失：
1. 确认网络可访问 HuggingFace
2. 首次启动后发送一次音频触发模型下载
3. 耐心等待（下载约 1-5 分钟，解压约 30 秒）

### 语音 WebSocket 连接失败
1. 确认后端日志无 MEETING_NOT_ACTIVE 错误
2. 确认 seat=1 是 speaker seat
3. 检查是否被防火墙拦截
4. 确认 `?seat=1` 参数正确附加在 URL 上

### Playwright 无法自动化麦克风
Playwright 默认不支持浏览器麦克风权限。E2E 测试使用 deterministic-caption
方案代替真实麦克风输入：通过 mock WebSocket 注入已知字幕数据验证前端展示，
同时使用真实 speech WS 发送 PCM fixture 文件和 end_hint 验证后端链路。

替代验证方式：
- 用 `npm run e2e:speech` 验证 caption 链路完整性
- 用 Playwright + 人工交互做手动演示
- 注意：E2E 测试在 CI 中也使用相同方式（无需物理麦克风）
