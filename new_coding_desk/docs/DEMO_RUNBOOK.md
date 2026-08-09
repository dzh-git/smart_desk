# SmartDesk Demo Runbook

本文档描述当前 SmartDesk 本地演示、自动检查和人工验收流程。过往
Task 级计划已移除，本文只保留当前项目可执行的事实。

## 1. 环境要求

- Windows 10/11。
- Python 3.11（唯一受支持版本）。
- Node.js 20+。
- Chrome 或 Edge。
- 语音演示需要浏览器麦克风权限。
- 语音/翻译模型缓存位于 `models/` 和 `.hf_cache/`，不纳入 git。

安装依赖：

```powershell
Set-Location ..
.\SETUP_PYTHON.bat
npm install --prefix new_coding_desk/frontend
```

所有后端、测试和辅助服务统一使用仓库根目录
`.venv\Scripts\python.exe`；启动脚本会拒绝其他 Python 版本。

## 2. 启动与停止

启动：

```powershell
.\start.bat
```

默认地址：

- 前端：`http://127.0.0.1:5173`
- 后端 API：`http://127.0.0.1:8000`
- OpenAPI：`http://127.0.0.1:8000/docs`

停止：

```powershell
.\kill.bat
```

常用 demo 环境变量：

CMD 中：

```bat
set ENABLE_DEMO_SEED=true
set ENABLE_DEMO_SEED_WHEN_NO_ACTIVE=true
set ENABLE_DEMO_SEAT_API=true
set VITE_ENABLE_DEMO_CONTROLS=true
```

PowerShell 中：

```powershell
$env:ENABLE_DEMO_SEED = "true"
$env:ENABLE_DEMO_SEED_WHEN_NO_ACTIVE = "true"
$env:ENABLE_DEMO_SEAT_API = "true"
$env:VITE_ENABLE_DEMO_CONTROLS = "true"
```

可选屏幕共享（Screen Stream）：

PowerShell 中：

```powershell
$env:ENABLE_SCREEN_STREAM = "true"
.\start.bat
```

CMD 中：

```bat
set ENABLE_SCREEN_STREAM=true
start.bat
```

启用前需将 FFmpeg 和 MediaMTX 二进制文件分别放置到
`tools/ffmpeg/bin/ffmpeg.exe` 和 `tools/mediamtx/mediamtx.exe`。
这些二进制文件不提交到 Git 仓库，需人工下载放置。Display Agent 默认由
`ENABLE_DISPLAY_AGENT=true` 独立启动并监听 `127.0.0.1:8766`；Screen
Supervisor 仅在 `ENABLE_SCREEN_STREAM=true` 时管理 FFmpeg + MediaMTX，WebRTC 播放地址为
`http://<中央主机IP>:8889/screen`。

局域网访问：前端绑定 `0.0.0.0:5173`，同一 LAN 的终端可通过
`http://<中央主机IP>:5173/screen` 查看共享画面。后端仍仅监听
`127.0.0.1:8000`，通过 Vite 代理访问。

停止 Screen Stream（随 kill.bat 自动停止）：

```powershell
.\kill.bat
```

可选真实翻译：

CMD 中：

```bat
set ENABLE_TRANSLATION_MODEL=true
```

PowerShell 中：

```powershell
$env:ENABLE_TRANSLATION_MODEL = "true"
```

未启用翻译模型时，最终记录的 `translated_text` 使用
`[translation not available]`。

## 3. 路由

| 路由 | 用途 |
|---|---|
| `/admin` | 主持人控制台。 |
| `/seat/:seatId` | 1 到 9 号座位端（seat 1 为主持人位）。 |
| `/display` | 中央大屏。 |
| `/` | 自动跳转到 `/admin`。 |
| `/?seat=N` | 兼容旧入口，自动跳转到 `/seat/N`。 |

## 4. 主持人端验收

1. 打开 `http://127.0.0.1:5173/admin`。
2. 无 active meeting 时，创建 pending meeting。
3. 点击 `Start Meeting`，进入 active meeting。
4. 确认 Workspace 切换可见：
   - `会议总览 / OVERVIEW`
   - `议程与投票 / AGENDA & VOTE`
   - `服务与记录 / SERVICE & RECORDS`
5. 确认不存在旧的 `当前阶段 / CURRENT PHASE`、`General`、
   `Agenda Discussion` 阶段切换。
6. 在总览中检查会议桌、座位、发言席、参会人。
7. 在议程与投票中新增议程、设置当前议题、推进/完成/跳过议题。
8. 创建投票，确认 open 投票时不能创建第二个 open 投票。
9. 关闭投票，确认主持人端展示投票结果。
10. 在服务与记录中确认服务请求和会议记录可见。
11. 点击 `End Meeting`，确认结束后仍能直接看到：
    - 投票结果；
    - 会议记录；
    - 服务历史；
    - 最终议程进度。

## 5. 座位端验收

1. 打开 `http://127.0.0.1:5173/seat/1`。
2. demo 模式下点击 `Occupy Seat (Demo)`。
3. 选择参会人并点击 `Confirm Check-in`。
4. 确认座位号、参会人、会议标题、连接状态清晰。
5. 确认当前议题只读卡片可见，不出现 `Set Current`、`Advance`、
   `Complete`、`Skip` 等控制按钮。
6. open 投票存在时，选择选项并提交投票。
7. 确认服务呼叫按钮可用；已有 pending 请求时不可重复创建。
8. 将当前座位设为发言席后，确认语音 `Start` 可用。
9. 会议结束后，确认签到、投票、服务呼叫和语音上传不可用。

## 6. 大屏端验收

1. 打开 `http://127.0.0.1:5173/display`。
2. active meeting 存在时，确认显示会议标题、会议状态和当前议题。
3. 确认大屏只提供 `Refresh`，不提供任何写操作。
4. open 投票存在时，确认显示当前投票统计。
5. 投票关闭后，确认显示最终投票结果。
6. 会议结束后，确认显示会议已结束状态，并保留最近投票结果和最终
   议程进度。
7. 无 active meeting 且无 ended meeting 时，确认显示等待会议状态；
   大屏会周期性检查新的 active meeting。

## 7. 语音验收

前置条件：

- 后端和前端已启动。
- 座位已签到。
- 当前座位已被主持人设为发言席。
- 浏览器已授予麦克风权限。

流程：

1. 在座位端点击语音 `Start`。
2. 说一段中文。
3. 确认主持人端和各座位端出现实时识别。
4. 停顿后等待自动 final，确认实时框清理，历史记录出现最终文本。
5. 点击 `Stop`，确认进入停止/收尾状态后回到可再次开始状态。
6. 点击 `Cancel`，确认本地实时框立即清理且不写入历史记录。
7. 连续说多句并插入长停顿，确认系统不会永久残留 live caption。

## 8. 自动检查

后端：

```powershell
pytest -q
```

Screen Stream 代码级预检（需要 FFmpeg 和实际 GPU）：

```powershell
python host_services/screen_stream/supervisor.py --check
```

该命令验证配置文件、二进制文件路径，并对各编码器进行短时实机捕获探测。
因依赖 GPU/显示器，失败时应记录硬件输出，不能把未运行记作通过。
当前 Intel Graphics 主机上 QSV 预检通过。不含 RTSP、MediaMTX、WebRTC
和多终端实机验收。

前端：

```powershell
cd frontend
npm run typecheck
npm run lint
npm test -- --run
npm run build
```

如需运行 Playwright：

```powershell
cd frontend
npm run e2e:speech
```

如果本地模型、浏览器或后端服务缺失，需在测试报告中说明失败原因，
不能把未运行或环境失败记为通过。

## 9. 常见问题

| 现象 | 处理 |
|---|---|
| 页面无 active meeting | 在 `/admin` 创建并启动会议，或启用 demo seed。 |
| 座位端无法签到 | 确认有 active meeting、座位已占用、已选择参会人、WebSocket connected。 |
| 不能启动语音 | 确认当前座位是发言席、已签到、模型 ready、麦克风权限已授权。 |
| 翻译显示占位符 | 未启用 `ENABLE_TRANSLATION_MODEL=true` 或本地模型不可用。 |
| 数据过多或状态混乱 | 本地 SQLite 数据库是 demo 产物，可停止服务后删除并重新启动。 |

## 10. Screen Stream 实机验收（需中央主机执行）

以下验收项需在配置了 FFmpeg 和 MediaMTX 的中央主机上手动执行。

**当前状态：** 代码级自动测试 64 passed（config + phase1）。Intel QSV
编码器预检（`supervisor.py --check`）通过；NVENC 因当前主机无 NVIDIA GPU
未通过，符合预期。以下完整管线及多端验收**全部 NOT_RUN**（mock 测试和
`--check` 不能替代实机验证）。

| 验收项 | 命令/操作 | 预期 |
|---|---|---|
| FFmpeg ddagrab | 启动 Screen Stream 后检查 supervisor 日志 | 成功捕获目标显示器 |
| MediaMTX WebRTC | 在 LAN 终端打开 `http://<IP>:8889/screen` | 画面正常播放 |
| Display Agent | `curl http://127.0.0.1:8766/status` | 返回 `agent_state: online` |
| PowerPoint 切换 | 在 `/admin` 点击 PowerPoint 按钮 | 幻灯片显示在目标显示器 |
| SolidWorks 切换 | 在 `/admin` 点击 SolidWorks 按钮 | SolidWorks 窗口激活 |
| 防火墙端口 | 检查 TCP 5173、8889 和 UDP 8189 放行 | LAN 终端可访问 |
| 10 终端负载 | 10 个浏览器同时打开 `/screen` | 画面基本流畅 |
| 端到端延迟 | 实测从画面变化到 WebRTC 显示 | 目标 <1s，验收上限 <=1.5s（当前未实机测量） |

## 11. 手势切屏验收

1. 保持 Display Agent 与手势识别模块运行，预先打开 PowerPoint 和 SolidWorks。
2. 在会议大屏前做 `I Love You` 手势并右滑，确认会议屏切至 PowerPoint；再次右滑返回会议屏。
3. 左滑验证会议屏与 SolidWorks 的往返，并验证 PowerPoint 左滑至 SolidWorks、SolidWorks 右滑至 PowerPoint。
4. 关闭目标应用后重试，确认当前窗口和手势模式保持不变，状态服务报告明确失败原因。

历史计划和阶段性说明统一归档到根目录 `docs/archive/`，不作为当前行为依据。
