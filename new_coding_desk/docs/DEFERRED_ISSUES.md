# SmartDesk Deferred Issues

## Seat Capacity Convergence

The approved product baseline is 9 complete seats: seat 1 is the host seat and seats 2–9 are attendee seats. This documentation update does not modify application code, database initialization, test fixtures, or route validation. Before release, verify that all runtime validation and seeded data reject seat ids outside `1..9` and that hardware status still maps exactly to the nine configured seats.

These issues are known and non-blocking for the v1 demo.

## ASR Accuracy

Current ASR quality depends on the local FunASR models, microphone quality, and
room noise. The demo acceptance target is pipeline correctness: PCM input,
interim display, auto-final, persistence, and final broadcast. Better accuracy
requires model replacement, model tuning, or improved audio hardware.

## RMS Endpoint Detection

The current final boundary uses RMS endpoint detection. It works for the local
demo but is less robust than a dedicated neural VAD. FunASR FSMN-VAD integration
is deferred.

## Translation Model Disabled by Default

OPUS-MT zh-en is available as an optional local model but is disabled unless
`ENABLE_TRANSLATION_MODEL=true`. This avoids requiring every developer to
download or load the model for ordinary backend tests.

## Translation Cache Deployment

Production deployment needs a clear model cache strategy for `models/` and
`.hf_cache/`. The current repository intentionally does not track model weights.

## Playwright Microphone Automation

Automated E2E tests use PCM fixtures rather than browser microphone permission.
Manual demo still requires a browser microphone grant.

## Host Display / Screen Stream 未验证项

以下项目不阻塞当前会议业务和代码构建（代码已完成，自动测试已通过），
但部署前必须完成实机验证。

| 未验证项 | 说明 |
|---|---|
| 外接中央显示器 `display_index` 校准 | `display_probe.py` 需在目标主机上运行并确认输出索引。DXGI 索引在热插拔后可能变化。 |
| PowerPoint 实际窗口切换 | Display Agent COM/Win32 路径需在安装了 PowerPoint 的主机上验证。 |
| SolidWorks 窗口切换 | 当前测试主机未安装 SolidWorks。需在 SolidWorks 主机上验证 `SLDWORKS.exe` 窗口激活。 |
| WebRTC 局域网播放 | 需在 LAN 终端上打开 `http://<中央主机IP>:8889/screen` 确认画面实际显示。 |
| 10 客户端并发 | 10 个浏览器同时打开 `/screen`。画面基本流畅即可。 |
| <1s 延迟目标 | 实测从画面变化到 WebRTC 显示的端到端延迟。 |
| 60 分钟稳定性 | 长时间运行后 FFmpeg 和 MediaMTX 不崩溃，画面不卡死。 |
| FFmpeg 异常自动恢复 | 主动终止 FFmpeg 进程后 Supervisor 应在 `restart_delay_seconds` 后自动重启并恢复推流。 |
| Windows 防火墙 | TCP 8889 和 UDP 8189 需放行。Ports 8000/8554/8766/9997/9998 保持 loopback-only。 |
| 目标主机编码器兼容性 | 当前 Intel Graphics QSV probe 已通过。但其他 Intel 驱动组合、NVIDIA NVENC 和软件 libx264 fallback 仍需在各目标主机上逐台验证。 |

## Local Database Growth

Repeated manual demos and E2E runs can create many meetings in the local SQLite
database. The database is disposable in local demo mode and can be deleted
before startup.

## Windows Launcher Cleanup

`start.bat` starts long-running backend and frontend windows. Use `kill.bat` to
clean up ports and processes.

## Frontend Lint Warnings

Some React Fast Refresh warnings may remain if shared test utilities export
non-component helpers. They do not affect build or runtime behavior.

## Punctuation Quality

Chinese punctuation and two-line caption formatting are functional but may need
future product tuning for readability and typography.
