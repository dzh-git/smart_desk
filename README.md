# SmartDesk 智能会议桌

SmartDesk 以中央 Windows 主机作为会议业务唯一权威源，以 9 台 Android 平板
显示同一套 `/seat/{seatId}` 会议页面，以 9 个 ESP32 负责本席传感器和灯带。
仓库已完成可由代码、测试、模拟器和静态分析验证的平板迁移；当前仍不是正式
发布状态，真机、实物、现场网络、人脸标定及模型商业许可证见
[人工验收清单](docs/integration/HUMAN_VALIDATION_REQUIRED.md)。

## 架构与边界

```text
中央 Windows 主机
├─ new_coding_desk/backend       FastAPI、数据库、会议状态、WebSocket
├─ new_coding_desk/frontend      唯一会议业务前端
├─ Display Agent                 Windows 应用切换唯一实现
└─ smartdesk_gesture_controller  只调用 Display Agent loopback API

Android 平板 × 9
└─ WebView + CameraX/ML Kit/本地人脸 + 网页麦克风 + 设备配置

ESP32 × 9
└─ PIR + VL53L0X + WS2812B + 直连席位 WebSocket
```

- Android 不写数据库，不复制签到、投票、议程或服务呼叫页面。
- FastAPI 决定人员是否属于当前会议，并复用 `SeatService` 完成签到。
- ESP32 不承载会议业务；人脸照片、embedding 和音频不上传到设备状态接口。
- Windows Seat Agent 与 Arduino 中央模式只作为兼容/台架路径保留。

完整说明见[集成架构](docs/integration/ARCHITECTURE.md)。

## 目录

| 目录 | 职责 |
|---|---|
| `new_coding_desk/` | FastAPI、React、中央大屏、Display Agent |
| `android_tablet/` | 正式 Android 容器、原生能力、诊断页、模型工具 |
| `esp32_seat_controller/` | ESP32 固件、模拟器、协议权威定义 |
| `smartdesk_gesture_controller/` | 中央主机手势识别 |
| `arduino_nano_controller/` | 兼容 Arduino 固件与协议 |
| `config/` | ESP32 正式示例与 Arduino 台架示例；实际配置不跟踪 |
| `deployment/portable/` | 内部演示版便携一键安装包 |
| `scripts/` | 一键验证、设备检查和单席/九席闭环入口 |
| `docs/integration/` | 当前平板/ESP32 集成契约与验收包 |

`docs/archive/` 仅供历史追溯，不是当前接口、配置或验收依据。

## 环境

- 中央主机：Windows 10/11、Python 3.11（唯一受支持版本）、Node.js 22。
- 仓库统一使用根目录 `.venv`；不要依赖系统 PATH 中的裸 `python`，也不要
  为各模块分别创建虚拟环境。
- Android 构建：JDK 17、Android SDK、Gradle Wrapper。
- ESP32 构建：PlatformIO CLI。
- 完整语音能力另需 `new_coding_desk/requirements.txt` 中的大型模型依赖和本地
  模型；CI 使用轻量的 `new_coding_desk/requirements-ci.txt`。
- 真机联调需中央主机固定局域网地址，并允许 TCP 8000、5173。

安装前端依赖：

```powershell
.\SETUP_PYTHON.bat
npm ci --prefix new_coding_desk/frontend
npm ci --prefix android_tablet/diagnostic-web
```

`SETUP_PYTHON.bat` 会查找 Python 3.11、创建 `.venv`、安装全部 Python
依赖并执行版本与依赖检查。固定解释器为
`.venv\Scripts\python.exe`；CI 可使用 `SETUP_PYTHON.bat -Profile CI`。
由于 PlatformIO 6.x 与语音栈依赖的 Click 版本互斥，固件 CLI 隔离在
`.tools\platformio-venv`，但同样强制使用 Python 3.11。

## 中央主机启动

现场使用便携包，不运行 Vite 开发服务器：

```powershell
powershell -ExecutionPolicy Bypass -File deployment\portable\build-portable.ps1
```

解压 `artifacts/` 中生成的内部包后，依次双击 `INSTALL.bat`、`START.bat`、
`DOCTOR.bat`。前端生产构建由轻量 Python 静态服务监听 5173，后端监听 8000。
实际硬件、数据和令牌位置分别由以下变量控制：

```text
SMARTDESK_CONFIG_PATH
SMARTDESK_DATA_DIR
SMARTDESK_ESP32_DEVICE_TOKENS_FILE
```

开发联调仍可使用 `new_coding_desk/start.bat`。健康检查为
`http://<中央主机IP>:8000/api/health`，席位页面为
`http://<中央主机IP>:5173/seat/1`。正式 ESP32 拓扑、设备令牌和数据库备份步骤
见[单席运行手册](docs/integration/ONE_SEAT_RUNBOOK.md)。

## Android

设备配置含 `seatId`、`deviceId`、独立 `deviceToken`、`serverBaseUrl` 和
`frontendBaseUrl`。正式页面固定加载 `/seat/{seatId}`；内置
`diagnostic-web` 只用于首次配置、离线和维护。

```powershell
Set-Location android_tablet
.\build-debug.ps1
```

当前人脸权重不提交到仓库且 Release 构建被许可证门禁阻断。详见
[Android 模块说明](android_tablet/README.md)、
[Bridge 契约](docs/integration/ANDROID_BRIDGE_CONTRACT.md)和
[模型许可门禁](docs/integration/MODEL_LICENSE_GATE.md)。

## ESP32

复制 `esp32_seat_controller/firmware/include/DeviceConfig.example.h` 为忽略的
`DeviceConfig.h`，为每席填写不同的席位、设备号和令牌：

```powershell
.\PIO.bat run -d esp32_seat_controller/firmware
```

当前协议唯一权威来源是
[esp32_seat_controller/protocol.md](esp32_seat_controller/protocol.md)。

## 自动验证

默认命令运行全部可用软件验证，并把执行项明确分为 `REQUIRED`、
`OPTIONAL_ENVIRONMENT`、`HARDWARE_REQUIRED`：

双击 `RUN_VALIDATION.bat`，或运行 `.\scripts\verify_all_software.ps1`。Full
默认包含九席 30 分钟无人值守模拟。

快速回归和单席 20 轮闭环：

```powershell
.\scripts\verify_all_software.ps1 -Profile Fast
.\scripts\run_seat1_integration_test.ps1
```

报告写入忽略的 `logs/verification/`，包含脱敏 JSON、HTML、日志和 zip
artifact。最少人工步骤见
[最短现场验证流程](docs/integration/FIELD_VALIDATION_QUICKSTART.md)。完整发布状态、
测试证据和阶段提交见
[发布就绪报告](docs/integration/RELEASE_READINESS.md)；九席复制顺序见
[九席部署手册](docs/integration/NINE_SEAT_DEPLOYMENT.md)。
