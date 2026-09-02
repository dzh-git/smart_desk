# 兼容路径说明

正式现场拓扑是 Android 平板 + 每席 ESP32。以下旧路径仍保留，但不得继续扩展为
第二套产品实现：

| 路径 | 用途 | 约束 |
|---|---|---|
| `new_coding_desk/seat_agent/` | 旧 Windows 席位终端回归 | 仅 `deploy_mode=distributed` |
| `arduino_nano_controller/` | Arduino 台架和串口固件 | 只使用脱敏示例配置 |
| `backend/hardware/arduino_manager.py` | 中央串口兼容 | ESP32 正式模式不得调用 |

正式 ESP32 模式必须拒绝旧 `pir/status/sync` 协议。自动验证固定运行
`test_legacy_protocol_only_remains_in_distributed_mode`，并保留灯光状态解析和
Display Agent 回归。已删除的 `repack_deploy.*` 不再是有效部署入口。

本机实际配置由 `SMARTDESK_CONFIG_PATH` 指向，Git 只保存：

- `config/smartdesk.integration.esp32.example.json`；
- `config/smartdesk.integration.arduino.example.json`。
