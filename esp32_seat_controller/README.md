# ESP32 席位控制器

本模块是正式的席位硬件路径。每个 ESP32 通过 Wi-Fi 直接连接中央后端
`/ws/seat/{seatId}`，作为纯 Wi-Fi WS2812B 灯光控制器接收本席灯光命令；它不
采集入座传感器，也不保存或判断会议业务。Windows Seat Agent 与 Arduino 中央
串口模式仍保留为兼容台架。

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

正式模式还必须为每台控制器配置独立凭据，不能写入仓库：

```powershell
$env:SMARTDESK_ESP32_DEVICE_TOKENS_JSON = @'
{
  "esp32-seat-01": {
    "seatId": 1,
    "token": "replace-with-random-token-at-least-24-chars"
  }
}
'@
```

设备、席位和令牌必须与固件 `DeviceConfig.h` 一致。凭据 JSON 缺失或无效时
后端保持运行以便诊断，但正式 ESP32 连接全部失败关闭且不会显示在线。
最低固件版本默认 `0.1.0`，可用
`SMARTDESK_ESP32_MIN_FIRMWARE_VERSION` 提高。

## 模拟器

后端以 ESP32 模式启动后，可模拟 1–9 席：

```powershell
python -m esp32_seat_controller.simulator.esp32_simulator `
  --server-url ws://127.0.0.1:8000 `
  --seats 9
```

模拟器默认从同一个 `SMARTDESK_ESP32_DEVICE_TOKENS_JSON` 读取各席独立令牌；
缺少任一席位、席位绑定错误或令牌过短都会在连接前失败。仅测试旧
`distributed` 台架时可显式传 `--allow-unauthenticated-test`。

协议和异常场景测试：

```powershell
python -m pytest -q esp32_seat_controller/simulator/tests
python -m pytest -q new_coding_desk/tests/test_esp32_protocol.py
```

模拟器仍覆盖连接、心跳、旧版入座/离座与传感器异常协议、重启、重复/乱序事件、
丢失 ACK 和九席独立绑定，用于验证后端对 v1 旧固件的兼容性。0.3.0 实物固件
不再发送入座或传感器事件。模拟结果不是实物验证。

## 固件构建

1. 在 `firmware/include` 中将 `DeviceConfig.example.h` 复制为
   `DeviceConfig.h`。
2. 填写 Wi-Fi、中央主机、席位、设备编号和独立设备令牌。
3. 使用 PlatformIO 执行：

```powershell
.\PIO.bat run -d esp32_seat_controller/firmware
```

`DeviceConfig.h` 和 `.pio/` 已排除，不会把令牌提交到仓库。固件采用非阻塞灯效、
Wi-Fi/WebSocket 指数退避、应用心跳、命令 ID 去重、ACK、看门狗和断网
`ERROR` 安全灯态。入座状态由专用平板的人脸验证经后端事件驱动。

## ESP32-WROOM-32E 接线

默认 `esp32dev` 配置使用以下引脚；如实物布线不同，只修改各设备忽略的
`DeviceConfig.h`：

| 设备 | ESP32-WROOM-32E | 说明 |
|---|---:|---|
| WS2812B DIN | GPIO13 | 默认 60 颗，实际亮度硬上限 80 |

WS2812B 使用独立、容量足够的 5V 电源，不从 ESP32 的 3.3V 引脚给灯带供电；
灯带电源地、ESP32 地必须共地。ESP32 数据输出是 3.3V，正式布线建议使用
`74AHCT125` 或 `74HCT14` 转为 5V，并在灯带输入端配置串联数据电阻和大容量
电容。`MAX_LED_BRIGHTNESS=80` 只是软件保护，不能替代电源、线径、保险和温升
验收。

## HARDWARE_VALIDATION_REQUIRED

以下只能在实物完成：实际板型/引脚、WS2812B 供电和电平、看门狗复位、真实
Wi-Fi 重连、平板人脸入座联动及长时间温升。统一步骤最终记录在
`docs/integration/HUMAN_VALIDATION_REQUIRED.md`。
