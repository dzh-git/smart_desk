# ESP32 席位控制器

本模块是正式的席位硬件路径。每个 ESP32 通过 Wi-Fi 直接连接中央后端
`/ws/seat/{seatId}`，负责 PIR、VL53L0X、WS2812B 和本席协议状态；它不保存或
判断会议业务。Windows Seat Agent 与 Arduino 中央串口模式仍保留为兼容台架。

## 目录

```text
esp32_seat_controller/
├─ firmware/       # PlatformIO/Arduino 固件
├─ simulator/      # 无实物协议模拟器
└─ protocol.md     # 当前协议权威定义
```

## 后端配置

复制 `config/smartdesk.integration.esp32.example.json` 为部署配置，或把现有配置
的 `deploy_mode` 改为 `esp32`。中央模式 `central` 和旧 Windows Agent 模式
`distributed` 均不会被删除。

## 模拟器

后端以 ESP32 模式启动后，可模拟 1–9 席：

```powershell
python -m esp32_seat_controller.simulator.esp32_simulator `
  --server-url ws://127.0.0.1:8000 `
  --seats 9
```

协议和异常场景测试：

```powershell
python -m pytest -q esp32_seat_controller/simulator/tests
python -m pytest -q new_coding_desk/tests/test_esp32_protocol.py
```

模拟器覆盖连接、心跳、入座/离座、重启、重复/乱序事件、丢失 ACK、传感器异常
和九席独立绑定。模拟结果不是实物验证。

## 固件构建

1. 在 `firmware/include` 中将 `DeviceConfig.example.h` 复制为
   `DeviceConfig.h`。
2. 填写 Wi-Fi、中央主机、席位、设备编号和独立设备令牌。
3. 使用 PlatformIO 执行：

```powershell
pio run -d esp32_seat_controller/firmware
```

`DeviceConfig.h` 和 `.pio/` 已排除，不会把令牌提交到仓库。固件采用非阻塞传感
采样与灯效、Wi-Fi/WebSocket 指数退避、应用心跳、命令 ID 去重、ACK、看门狗
和断网 `ERROR` 安全灯态。

## HARDWARE_VALIDATION_REQUIRED

以下只能在实物完成：实际板型/引脚、PIR 误触发、VL53L0X 距离阈值、WS2812B
供电和电平、看门狗复位、真实 Wi-Fi 重连及长时间温升。统一步骤最终记录在
`docs/integration/HUMAN_VALIDATION_REQUIRED.md`。
