# SmartDesk 自主集成进度

最后更新：2026-07-27

## 当前阶段

阶段 0–5 完成度审计与基线固化。Android 原型、主前端 Native Bridge 和
身份签到的第一版已经进入集成分支；正在补齐设备身份、事件幂等、完整 Bridge
契约和可重复验证入口，之后继续 ESP32 与单席闭环。

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
  `/api/seats/{seat_id}/identity-checkin` 第一版。
- `PROTOTYPE` 默认不能自动签到，`CALIBRATION_PENDING` 会被拒绝。
- Graphify 根级单一快照已更新。

## 已执行测试

| 范围 | 命令/方式 | 结果 |
|---|---|---|
| Android JVM | `gradlew testDebugUnitTest --offline` | 通过，18 项 |
| Android 诊断页 | `npm run build` | 通过 |
| 主前端全量 | `npm test -- --run` | 通过，323 项 |
| 主前端最终定向 | app-config、NativeBridge、seat | 通过，83 项 |
| 主前端类型/构建 | `npm run typecheck`、`npm run build` | 通过 |
| 手势控制器 | `python -m pytest -q` | 526 项通过，4 项条件跳过 |
| 身份/席位/会议后端 | 定向 pytest | 通过，99 项 |
| 后端业务分组 | 分组 pytest | 通过，337 项 |
| 后端契约分组 | 分组 pytest | 通过，173 项 |
| 后端语音算法分组 | 分组 pytest | 282 项通过，3 项条件跳过 |
| Android Lint | `gradlew lintDebug` | 通过 |
| Android APK编译 | `gradlew assembleDebug` | 通过；不含未提供的模型权重 |
| Graphify | `scripts\graphify_update_single.bat` | 通过 |

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
- `new_coding_desk/docs/`
- `graphify-out/`

## 尚未完成的软件任务

- Android 配置安全存储、健康检查、加载超时和管理员重新配置入口。
- Native Bridge 完整状态/已注册人员接口、事件版本、事件 ID 和去重。
- 设备注册/席位绑定、设备令牌和 identity-checkin 幂等事件。
- ESP32 协议、固件骨架、后端兼容处理、模拟器和协议测试。
- seat 1 自动闭环与连续 20 轮恢复/幂等测试。
- Android WebView 麦克风权限和生命周期处理。
- Tablet/ESP32 分离的设备状态与管理端只读视图。
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
- 当前 identity-checkin 第一版仅比较请求中的席位字段，尚无可信设备注册。
- 当前原生事件没有统一 `schemaVersion`、`eventId`，不能证明端到端幂等。
- 现有 Seat Agent 协议适合 Windows+Arduino，但尚不满足 ESP32 ACK、
  顺序、版本和传感器错误要求。

## 下一步

1. 完成阶段 0 基线脚本并运行可用检查。
2. 将现有迁移、前端和身份改动拆成小型提交。
3. 补齐阶段 1–5 的安全与幂等缺口。
4. 在现有 SeatGateway 上实现版本化 ESP32 协议和模拟器。
