# 发布就绪报告

最后更新：2026-07-28

## 当前结论

| 范围 | 状态 | 说明 |
|---|---|---|
| 机器可完成的软件工程范围 | `COMPLETE` | 阶段 0–12 的实现、测试、模拟、CI、配置和文档已闭合 |
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
| 9 | 一键验证可运行 | `verify_all_software.ps1` 与 CI workflow | 通过 |
| 10 | 文档/配置/人工验收包 | 本目录 8 份集成文档、链接/契约检查 | 通过 |
| 11 | 未验硬件明确标记 | `HUMAN_VALIDATION_REQUIRED.md` | 通过 |
| 12 | 原型/许可证限制明确 | 模型卡、机器门禁、Release Gradle 阻断 | 通过 |

## 自动验证基线

最终默认 Full 报告以 `logs/verification/verify-all-software.json` 为本机证据；该
目录不提交 Git。当前已取得的独立复验：

| 项目 | 结果 |
|---|---|
| Python 源码静态编译 | 211 个源文件通过 |
| 仓库配置/文档契约 | 通过 |
| 后端完整非长时集合 | 912 通过，4 条件跳过 |
| 前端 | 类型检查、330 单测、生产构建通过 |
| 手势控制器 | 526 通过，4 条件跳过 |
| Android | 28 JVM 测试、Lint、Debug APK 通过 |
| ESP32 | 协议/模拟器通过；固件 RAM 14.9%、Flash 74.7% |
| seat 1 | 后端/ESP32 18 项、前端 2 项；核心闭环 20 轮 |
| 模型门禁 | prototype 声明通过；release 按预期 `MODEL_LICENSE_GATE_BLOCKED` |

`test_speech_stream_service.py` 与 `test_speech_websocket_blackbox.py` 在本环境组合
运行超过 20 分钟未完成，明确归类 `OPTIONAL_ENVIRONMENT`，只有设置
`SMARTDESK_RUN_SLOW_SPEECH_TESTS=true` 才执行。30 分钟真实收音仍是人工项。

## 主要风险

1. 当前权重仅限非商业研究且不随仓库分发；项目根也无可推定的对外代码许可证。
2. 当前没有活体检测，照片/屏幕翻拍可能攻击识别；75 次小样本不能估计正式
   FMR/FNMR。
3. 现场示例使用 HTTP/WS；不可信网络必须使用受管 TLS、证书和网络隔离。
4. 会议管理 API 当前面向受控局域网；部署到更广网络前需要独立的管理身份与
   授权审查。
5. 固件虽能编译，真实引脚、阈值、供电、看门狗、Wi-Fi 与温升尚无新版本实物
   证据。
6. Vite dev server 只用于联调；正式场地需要受控静态托管/反向代理方案。

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

各阶段后另有独立 `chore: refresh ... graph snapshot` 提交维护根级 Graphify
快照。文档阶段和最终审计提交以本分支后续 `git log` 为准。
