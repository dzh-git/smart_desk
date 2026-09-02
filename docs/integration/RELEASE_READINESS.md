# 发布就绪报告

最后更新：2026-09-02

## 当前结论

| 范围 | 状态 | 说明 |
|---|---|---|
| 机器可完成的软件工程范围 | `COMPLETE` | Full 验证、九席 30 分钟模拟和便携安装生命周期已闭合 |
| 内部演示安装包 | `READY_FOR_FIELD_VALIDATION` | 静态前端、后端、APK、固件工具、Display Agent、手势和诊断已打包 |
| Android/ESP32/现场验收 | `HARDWARE_VALIDATION_REQUIRED` | 不以 JVM、APK、固件编译或模拟器替代实物 |
| 人脸自动签到安全等级 | `CALIBRATION_PENDING` | 75 次标定后也只能成为内部 `PROVISIONAL/PROTOTYPE` |
| 正式/商业发布 | `BLOCKED` | 当前权重非商业研究限制且无活体检测；Release 门禁按设计失败 |

因此可以声明“机器可完成部分已经完成”，不能声明“产品已经正式发布/现场验收
通过”。

## 完成判定

| # | 判定条件 | 证据 | 机器状态 |
|---:|---|---|---|
| 1 | Android 已迁入且可构建 | `android_tablet/`、JVM/Lint/Debug APK | 通过 |
| 2 | 正式席位页与 Bridge 接通 | `/seat/{seatId}`、Native 适配层与 Android 事件测试 | 通过 |
| 3 | 稳定 Person/Attendee 关联 | 模型、幂等启动迁移、服务/API 测试 | 通过 |
| 4 | identity-checkin 业务校验 | 认证、时效、等级、事务、错误码和广播测试 | 通过 |
| 5 | ESP32 协议/固件/模拟器 | v1 规范、PlatformIO 编译、模拟测试 | 通过 |
| 6 | 单席完整软件闭环 | `run_seat1_integration_test.ps1` | 20 轮通过 |
| 7 | 重复/断线/重连/幂等 | 单席、协议、Bridge 和恢复测试 | 通过 |
| 8 | 原有核心测试未破坏 | 后端非长时 912、前端 330、手势 526 | 通过 |
| 9 | 一键验证可运行 | `RUN_VALIDATION.bat`、脱敏 JSON/HTML/ZIP 与 CI workflow | 通过 |
| 10 | 文档/配置/人工验收包 | 本目录 8 份集成文档、链接/契约检查 | 通过 |
| 11 | 未验硬件明确标记 | `HUMAN_VALIDATION_REQUIRED.md` | 通过 |
| 12 | 原型/许可证限制明确 | 模型卡、机器门禁、Release Gradle 阻断 | 通过 |

## 自动验证基线

最终 Full 报告生成于 2026-07-30，以
`logs/verification/verify-all-software.json` 为本机证据；该目录不提交 Git。
汇总为 26 PASS、8 显式 SKIP、0 FAIL，所有 `REQUIRED` 项通过。ZIP artifact
只包含脱敏的 JSON、HTML 和日志，不包含令牌、人脸、embedding、原始语音或
数据库。当前已取得的独立复验：

| 项目 | 结果 |
|---|---|
| Python 源码静态编译 | 221 个源文件通过 |
| 仓库配置/文档契约 | 通过 |
| 后端完整非长时集合 | 通过 |
| 前端 | 类型检查、330 单测、生产构建通过 |
| 手势控制器 | 526 通过，4 条件跳过 |
| Android | 28 JVM 测试、Lint、Debug APK 通过 |
| Redmi K60 自动复验 | 覆盖安装、版本、Activity、WebView 启动通过 |
| ESP32 | 协议/模拟器和 PlatformIO 固件编译通过 |
| seat 1 | 后端/ESP32 18 项、前端 2 项；核心闭环 20 轮 |
| 九席模拟 | 9 ESP32、9 Tablet、9 客户端及重启/断线恢复，30 分钟通过 |
| 数据库 | 备份、双次迁移、数据/约束保持、失败回滚通过 |
| 便携包 | 全新安装、升级、失败回滚、卸载保留数据通过 |
| 投屏 | MediaMTX/FFmpeg、10 Chromium 客户端、FFmpeg 恢复通过 |
| Display Agent | 8766 服务与自动化契约通过；最新 PowerPoint 实机切换受当前 Office COM 忙状态阻塞，关闭临时演示文稿后需重跑；SolidWorks 待目标机 |
| 模型门禁 | prototype 声明通过；release 按预期 `MODEL_LICENSE_GATE_BLOCKED` |

### 2026-09-02 增量复验

- 正式 `start.bat` 已修复重定向 stdin 下 `timeout.exe` 立即失败的问题；重新启动
  后端约 5 秒、前端约 1 秒就绪，Display Agent 正常监听 8766，启动输出无伪失败。
- 前端 373 项单测、类型检查和生产构建通过；Android 单测/Lint/Debug APK、
  平板诊断页 11 项测试与构建通过。
- Python 测试按后台线程边界拆为两个干净进程执行：其余集合 1054 通过、7 条件
  跳过，语音 WebSocket 黑盒 24 通过、1 条件跳过，共 1078 通过、8 跳过、0 失败。
- 九席软件模拟通过；语音 WebSocket 黑盒为 24 通过、1 条件跳过，真实中文
  PCM 实时字幕用例通过。旧测试录音已仅在测试端归一化，并显式选择中文流式
  引擎，避免把自动语言探测性能混入中文字幕契约。
- 新平板部署包 5 项回归已覆盖 Windows PowerShell 5/7 Dry Run、确认设备模拟
  配置和验收、输出目录越界防护，以及缺失/篡改 APK SHA-256 时在任何 ADB
  操作前拒绝；manifest 声明不含秘密。
- 当前 Seat 2 未连接 USB，但通过移动热点持续上报新鲜心跳：App 0.9.0，
  camera/face/microphone/diagnostic 为 `READY`，会议 WebSocket 为 `CONNECTED`，
  API 与 `/seat/2` 均可从 `192.168.137.1` 访问。

PCM 长语音、生命周期和切席路由测试已通过。
`test_speech_stream_service.py` 与 `test_speech_websocket_blackbox.py` 在本环境组合
运行超过 20 分钟，继续归类 `OPTIONAL_ENVIRONMENT`，只有设置
`SMARTDESK_RUN_SLOW_SPEECH_TESTS=true` 才执行。真实麦克风中英文各一句仍是人工项。

## 主要风险

1. 当前权重仅限非商业研究且不随仓库分发；项目根也无可推定的对外代码许可证。
2. 当前没有活体检测，照片/屏幕翻拍可能攻击识别；75 次小样本不能估计正式
   FMR/FNMR。
3. 现场示例使用 HTTP/WS；不可信网络必须使用受管 TLS、证书和网络隔离。
4. 会议管理 API 当前面向受控局域网；部署到更广网络前需要独立的管理身份与
   授权审查。
5. 固件虽能编译，真实引脚、阈值、供电、看门狗、Wi-Fi 与温升尚无新版本实物
   证据。
6. 现场仍需核对防火墙、固定 IP、AP 供电和九台真实设备；软件包已改用
   5173 轻量静态服务，不再依赖 Vite 开发服务器。

## 正式发布退出条件

- [ ] [HUMAN_VALIDATION_REQUIRED](HUMAN_VALIDATION_REQUIRED.md) 所有适用项签字。
- [ ] 商业权重使用和再分发授权、项目代码许可、证据路径与 SHA-256 完整。
- [ ] 新模型重新转换、数值验证、真机模板重建和独立安全评估。
- [ ] Release 模型门禁和 Android Release 构建通过，不通过修改布尔值绕过。
- [ ] 管理访问、TLS、密钥轮换、数据库备份/恢复和现场回滚完成安全审查。
- [ ] seat 1 实物 20 轮后，九席 30 分钟并发、语音和供电验收通过。

## 阶段提交

| 提交 | 作用 |
|---|---|
| `a7cba07` | 建立迁移基线、冻结原型、迁入 Android 模块 |
| `ec054b0` | 正式前端 NativeBridge 适配层 |
| `150cdfa` | 稳定 Person 与身份签到基础流程 |
| `4ed9036` | 软件基线验证入口 |
| `413edb7` | 平板认证与身份事件幂等 |
| `e428827` | 原生身份事件和 Android 安全存储 |
| `a7f7e8b` | ESP32 v1 后端、固件、模拟器与协议 |
| `e86c2fe` | seat 1 二十轮软件闭环 |
| `55749c9` | WebView、麦克风、生命周期和恢复加固 |
| `6fa475f` | 平板心跳与双通道设备运维状态 |
| `0db1713` | 设备认证、限流、事务、版本和模型发布门禁 |
| `ee37e4b` | CI、一键验证和全量回归修复 |
| `80f8006` | 架构、契约、单席/九席、发布与人工验收文档包 |
| `594d622` | Windows PowerShell 5 预期 Release 阻断捕获兼容 |

各阶段后另有独立 `chore: refresh ... graph snapshot` 提交维护根级 Graphify
快照。最终证据回填与快照提交以本分支后续 `git log` 为准。
