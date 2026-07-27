# SmartDesk 自主集成进度

最后更新：2026-07-28

## 当前阶段

阶段 0–9 已完成软件实现与定向回归。Tablet 已通过绑定设备令牌上报心跳和
非生物特征运行状态；后端将 Android 与 ESP32 作为独立通道聚合并执行超时
离线判断，管理端按席位只读展示两类设备；下一阶段进入发布安全、模型许可
门禁、CI 和一键验证。

## 已完成

- 主仓库已切换到 `feature/android-tablet-integration`。
- 原型仓库提交 `1f4ad9524a856f8e8d913e34a0307c3d040fac48` 已创建本地标签
  `v0.8.0-face-prototype`。
- Android 原型已迁入 `android_tablet/`，会议测试页已改为
  `diagnostic-web/`。
- Android 已支持持久化席位、设备、后端和前端地址配置，并加载
  `/seat/{seatId}`。
- 主前端已增加 `frontend/src/native/` 适配层并接收
  `smartdesk-native-event`。
- 后端已增加稳定 `Person`、`Attendee.person_id` 和
  `/api/seats/{seat_id}/identity-checkin`。
- 后端设备注册默认关闭，启用后以一设备一席位绑定；仅保存 PBKDF2 加盐哈希，
  identity-checkin 必须携带设备密钥。
- identity-checkin 持久化原生 `eventId`；相同证据重试不重复广播，不同证据
  复用事件 ID 返回 409。
- Android 设备配置和人脸模板使用 Android Keystore AES-GCM 加密，禁止备份；
  旧明文值首次读取时迁移。
- 原生事件已统一为 `schemaVersion/eventId/timestamp/type/data`，前端做有界
  事件 ID 去重，并把同一事件 ID 传递到后端。
- Native Bridge 已覆盖设备信息、受限设备凭据、身份状态、已注册人员以及
  开始/停止验证；设备密钥只允许受信 `/seat/{seatId}` 页面读取。
- `PROTOTYPE` 默认不能自动签到，`CALIBRATION_PENDING` 会被拒绝。
- 新增 `esp32_seat_controller/`：PlatformIO 固件、协议、模拟器和静态契约
  测试；固件已实际编译为 ESP32 Dev Module 镜像。
- 后端 `/ws/seat/{seatId}` 同时支持 ESP32 v1 和旧 Windows Seat Agent；
  `deploy_mode=esp32` 为正式直连模式，`central/distributed` 仍保留。
- ESP32 协议实现 hello、心跳/离线、入座、传感器错误、版本/席位校验、4096
  bytes 上限、sequence、事件去重、命令 ID、ACK、同 ID 重试、超时与重连同步。
- 硬件状态接口可以区分 `esp32/windows_agent`，并报告固件、心跳、传感器、
  距离、命令待确认和最近错误。
- 新增 seat 1 软件闭环测试夹具和一键脚本；连续 20 轮均走真实 REST 路由、
  `SeatService`、EventBus、WebSocket 广播、`LightingManager`、ESP32
  模拟器和命令 ACK。
- 单席闭环覆盖重复事件不重复签到、乱序 sequence 拒绝、每 4 轮 ESP32
  重连，以及第 11 轮后端硬件内存态重建后从数据库继续运行。
- 修复 ESP32 快速 ACK 早于后端登记待确认命令的竞态；灯光管理器增加显式
  注销，确保测试和进程内替换不会遗留 EventBus 订阅或定时器。
- Android WebView 只对已绑定的精确 `/seat/{seatId}` 页面和同源请求放行
  `RECORD_AUDIO`；外部来源、错误席位和混合音视频资源均拒绝。
- Activity 暂停、进入维护页、页面隐藏、页面卸载和演讲席撤销会立即取消录音、
  关闭语音 WebSocket 并释放资源；语音 WS 异常时先释放旧麦克风，再以有界
  重试建立新 WS 和新采集实例。
- Android 启动正式席位页前检查 `/api/health`；区分离线、服务错误、15 秒
  页面超时和重试状态，网络恢复后自动重试。
- 正式页面提供带确认的“设备维护”入口；本地诊断页显示 setup/checking/
  offline/server-error/timeout/maintenance 状态且仍是唯一配置修改来源。
- 设备配置存储支持可注入夹具，已验证保存、重载和重新配置时保留现有密钥；
  生产实现仍由 Android Keystore AES-GCM 存储。
- 增加认证 Tablet 心跳接口，持久化 App 版本、摄像头、人脸模型、模板数量、
  麦克风、会议 WebSocket、诊断状态和最近错误；不上传照片、embedding 或
  原始音频。
- `/api/hardware/status` 分别返回 `tablets` 与席位控制器 `seats`；Tablet
  默认 45 秒未心跳离线（可限制在 10–300 秒配置），ESP32 查询时也会收口
  已过期心跳。
- 管理端原有 `HardwareStatus` 已升级为按席位只读设备面板，分别显示 Tablet
  与 ESP32/兼容控制器的在线、版本、心跳、原生能力、灯效、传感器和最近错误，
  不提供人脸图片。
- 现有数据库通过可重复执行的启动迁移增加 Tablet 状态列，不删除或猜测旧数据。
- Graphify 根级单一快照已更新。

## 已执行测试

| 范围 | 命令/方式 | 结果 |
|---|---|---|
| Android JVM | `gradlew testDebugUnitTest` | 通过，28 项 |
| Android 诊断页 | `npm run build` | 通过 |
| 主前端全量 | `npm test -- --run` | 通过，323 项 |
| 主前端 NativeBridge/seat 定向 | `vitest --run` | 通过，81 项 |
| 主前端类型/构建 | `npm run typecheck`、`npm run build` | 通过 |
| 手势控制器 | `python -m pytest -q` | 526 项通过，4 项条件跳过 |
| 身份/设备/席位/会议后端 | 定向 pytest | 通过，116 项 |
| 后端业务分组 | 分组 pytest | 通过，337 项 |
| 后端契约分组 | 分组 pytest | 通过，173 项 |
| 后端语音算法分组 | 分组 pytest | 282 项通过，3 项条件跳过 |
| Android Lint | `gradlew lintDebug` | 通过 |
| Android APK编译 | `gradlew assembleDebug` | 通过；不含未提供的模型权重 |
| Graphify | `scripts\graphify_update_single.bat` | 通过 |
| ESP32 服务端协议/WS/灯光兼容 | 定向 pytest | 通过，23 项 |
| ESP32 模拟器/固件契约 | `pytest simulator/tests` | 通过，8 项 |
| ESP32 固件 | `platformio run` | 通过；RAM 14.9%，Flash 74.7% |
| seat 1 软件闭环 | `scripts/run_seat1_integration_test.ps1` | 通过；后端/ESP32 18 项、前端 2 项，核心闭环连续 20 轮 |
| Android WebView/语音前端 | `typecheck`、Native/Hook 定向、完整 seat 测试 | 通过；12 项定向、76 项席位 |
| 语音 PCM/权限/切换后端 | 轻量 pytest 节点集 | 通过，21 项；未加载真实 ASR 大模型 |
| Tablet 心跳/聚合/迁移 | 专项 pytest | 通过，8 项；与 ESP32/单席组合回归 11 项通过 |
| 管理端设备状态 | Admin + HardwareStatus Vitest | 通过，106 项；另有 Android 心跳/身份定向 5 项 |

`test_speech_stream_service.py` 与 `test_speech_websocket_blackbox.py`
组合运行超过六分钟执行时限，未取得完整汇总；没有把超时描述为通过。
阶段 0 基线首次运行还准确报告了 ESP32 模拟器缺失。手势依赖安装后发现最新
OpenCV 5 会把共享环境升级到不兼容的 NumPy 2.x，因此
`smartdesk_gesture_controller/requirements.txt` 已固定到 NumPy 1.x 与
OpenCV 4.11 兼容线，复验通过。

## 当前修改范围

- `android_tablet/`
- `new_coding_desk/backend/{api,models,repositories,schemas,services}`
- `new_coding_desk/frontend/src/{native,api,components}`
- `new_coding_desk/tests/test_identity_checkin.py`
- `new_coding_desk/tests/test_one_seat_integration.py`
- `esp32_seat_controller/`
- `scripts/run_seat1_integration_test.ps1`
- `new_coding_desk/docs/`
- `graphify-out/`

## 尚未完成的软件任务

- 安全加固、模型许可门禁、CI 和 `verify_all_software.ps1`。
- 完整集成文档、部署手册和人工验收包。

## HARDWARE_VALIDATION_REQUIRED

- Redmi K60 安装、权限、WebView、前置摄像头和真实麦克风。
- 3 名注册人员、2 名陌生人、3 种光照共 75 次标定。
- ESP32、PIR、VL53L0X、WS2812B 的烧录、接线、供电和看门狗。
- 真实局域网重连、30 分钟语音、单席连续 20 次和九席并发。
- 现场供电、温升与散热。

## 已知风险

- 当前人脸权重未随仓库提供，许可和商业使用范围尚未通过发布门禁。
- 设备 token 已受保护，但 TLS、事件时效限制、设备禁用/轮换运维界面仍需在
  发布安全阶段收口。
- ESP32 固件已编译但尚未在实物验证 PIR/VL53L0X/WS2812B 引脚、阈值、供电、
  Wi-Fi 和看门狗复位行为。

## 下一步

1. 完成设备接口防滥用、事件时效、日志脱敏和安全配置审计。
2. 增加模型许可发布门禁和 `MODEL_LICENSE_GATE.md`。
3. 完成 CI、`verify_all_software.ps1` 和分类验证结果。
4. 完成部署文档、发布清单与人工验收包。
