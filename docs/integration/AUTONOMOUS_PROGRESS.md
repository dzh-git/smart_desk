# SmartDesk 自主集成进度

最后更新：2026-07-28

## 当前阶段

阶段 0–11 已完成软件实现与定向回归。正式 ESP32 会话和平板接口已做独立
设备认证、席位绑定、版本门禁、基础限流和结构化脱敏日志；身份证据增加时效
与原子事务保证；当前非商业人脸权重已由脚本和 Android Release 构建双重阻断。
CI 和一键验证已落地；下一阶段完成架构、部署、发布和人工验收文档包。

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
- 正式 `deploy_mode=esp32` 只接受携带独立 Bearer 令牌的 v1 设备；服务端
  以环境 JSON 绑定 `device_id/seat_id/token`，认证前不登记在线，缺失或错误
  配置失败关闭。旧 Windows 协议只保留在 `distributed` 测试台架。
- ESP32 模拟器读取同一多设备凭据映射，并在连接前拒绝缺席位、错席位或短令牌；
  固件与平板 App 都执行严格 SemVer 最低版本检查。
- 身份事件必须携带毫秒时间戳；首次事件默认只接受过去120秒至未来30秒窗口，
  相同已落库事件仍可幂等重试。
- 身份签到把 Seat、Attendee 和身份事件放在同一数据库事务中；注入事件写入
  失败的测试证明全部业务状态回滚且不广播成功事件。
- 身份、Tablet 心跳和设备注册入口使用有界内存滑动窗口限流，429 统一返回
  `RATE_LIMITED` 与 `Retry-After`。
- 设备认证、心跳与身份签到记录单行 JSON 安全事件；递归脱敏
  authorization/cookie/password/secret/token 类字段，自动测试证明错误令牌
  不进入日志。
- Android 模板由 Keystore AES-GCM 存储、备份与设备迁移全部排除，
  Release 关闭 WebView 调试；受信来源、Bridge最小暴露、资源释放和生命周期
  门禁均已有自动测试。
- 新增 `MODEL_LICENSE_GATE.md`、机器可读许可状态和发布检查脚本；原型状态检查
  通过，Release 脚本和 Gradle 任务均按预期以
  `MODEL_LICENSE_GATE_BLOCKED` 失败，不影响 Debug 编译。
- 新增 `scripts/verify_all_software.ps1`，默认 `Full`、CI 和显式 `Fast`
  三种配置均输出 `REQUIRED/OPTIONAL_ENVIRONMENT/HARDWARE_REQUIRED` 分类、
  控制台汇总、Transcript 和 JSON 报告；实际执行失败一律使总命令失败。
- 新增 Windows GitHub Actions，固定 Python 3.12、Node 22、JDK 17 和 Android
  SDK，安装轻量后端/手势/PlatformIO依赖并执行 CI 配置；报告始终上传。
- Python 静态检查只编译 Git 跟踪及未忽略的新源码，不扫描 `.venv`、
  `node_modules` 或工具缓存。
- PlatformIO core 固定到仓库忽略的 ASCII 路径；没有私有
  `DeviceConfig.h` 时验证脚本临时使用占位示例，构建后立即移除，避免中文
  用户目录工具链故障及凭据提交。
- 一键验证首次运行真实发现并修复了 Tablet 心跳连接状态测试竞态，以及
  CT-Transformer 已加载后产生 `，。` 的测试顺序污染；完整前端330项和完整
  非长时后端912项复验通过。
- 两个语音 stream/WebSocket 长时文件在本机组合运行20分钟仍未结束，未伪装
  为通过；它们被明确拆为 `OPTIONAL_ENVIRONMENT`，设置
  `SMARTDESK_RUN_SLOW_SPEECH_TESTS=true` 才执行。
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
| 阶段10安全/身份/设备/ESP32/单席 | 组合 pytest | 通过，70 项 |
| Python静态语法 | `python -m compileall` | 通过 |
| Android安全回归 | JVM + Lint + Debug APK | 通过；JVM 28 项，Release 门禁不参与 Debug |
| 模型许可原型声明 | `check_model_license_gate.py --mode prototype` | 通过，明确 Release 仍阻断 |
| 模型许可正式发布 | 脚本与 Gradle `checkModelLicenseGate` | 按预期失败：`MODEL_LICENSE_GATE_BLOCKED` |
| 一键验证 Fast | `verify_all_software.ps1 -Profile Fast` | 整体通过；所有执行项 PASS，环境/实物项显式 SKIP |
| Python源码静态检查 | `check_python_sources.py` | 通过，211项 |
| 后端完整非长时集合 | 排除2个已知长时语音文件的 pytest | 912项通过，4项条件跳过 |
| 前端全量复验 | `npm test -- --run` | 330项通过 |
| ESP32固件 ASCII 缓存复验 | 一键脚本 PlatformIO 检查 | 通过；RAM 14.9%，Flash 74.7% |

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

- 完整集成文档、部署手册和人工验收包。

## HARDWARE_VALIDATION_REQUIRED

- Redmi K60 安装、权限、WebView、前置摄像头和真实麦克风。
- 3 名注册人员、2 名陌生人、3 种光照共 75 次标定。
- ESP32、PIR、VL53L0X、WS2812B 的烧录、接线、供电和看门狗。
- 真实局域网重连、30 分钟语音、单席连续 20 次和九席并发。
- 现场供电、温升与散热。

## 已知风险

- 当前人脸权重未随仓库提供且仅限非商业研究；发布门禁会持续阻断，直至替换
  获得明确商业/再分发许可的权重并完成人工审批与重新标定。
- 局域网部署示例仍使用明文 HTTP/WS；设备令牌虽已受保护且日志脱敏，正式跨
  不可信网络部署前仍必须增加可信 TLS 终止和证书运维。
- 设备禁用和令牌轮换已有后端能力，但尚无专用管理 UI；当前通过受保护的
  provisioning 接口运维。
- ESP32 固件已编译但尚未在实物验证 PIR/VL53L0X/WS2812B 引脚、阈值、供电、
  Wi-Fi 和看门狗复位行为。

## 下一步

1. 完成部署文档、发布清单与人工验收包。
2. 扩展文档/链接检查并执行默认 Full 最终验证。
