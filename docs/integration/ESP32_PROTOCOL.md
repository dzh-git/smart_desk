# ESP32 集成协议入口

本文件只说明跨模块接入、认证和验收入口，不复制报文规范。所有消息字段、状态
机、时序、错误码、重连、去重和 ACK 的唯一权威来源是
[esp32_seat_controller/protocol.md](../../esp32_seat_controller/protocol.md)。

## 实现映射

| 组件 | 路径 | 责任 |
|---|---|---|
| 固件 | `../../esp32_seat_controller/firmware/` | 传感器、非阻塞灯效、重连、心跳、ACK |
| 模拟器 | `../../esp32_seat_controller/simulator/` | 无实物协议故障与 1–9 席回放 |
| 后端 codec | `../../new_coding_desk/backend/hardware/esp32_protocol.py` | v1 报文校验 |
| WebSocket | `../../new_coding_desk/backend/api/seat_ws.py` | 认证、席位绑定、版本门禁、网关注册 |
| 网关/灯控 | `../../new_coding_desk/backend/hardware/seat_gateway.py` | 在线状态、命令与 ACK |

## 正式连接前提

1. `config/smartdesk.integration.json` 使用 `deploy_mode=esp32`。
2. 固件 `SEAT_ID` 为 1–9，`DEVICE_ID` 与后端登记一致。
3. `SMARTDESK_ESP32_DEVICE_TOKENS_JSON` 为每个设备配置独立的
   `{seatId, token}`；令牌至少 24 字符。
4. 客户端连接 `ws://<host>:8000/ws/seat/{seatId}` 并在握手携
   `Authorization: Bearer <token>`。
5. 第一条业务消息必须是 schema v1 `hello`；设备、URL 席位、hello 席位必须
   一致，`firmware_version` 是不低于默认 `0.1.0` 的 SemVer。

凭据注册表缺失或无效时正式连接失败关闭。`esp32` 模式不会接受
`distributed` 兼容协议降级；日志不得包含令牌。

示例环境：

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

## 软件验证

```powershell
python -m pytest -q new_coding_desk/tests/test_esp32_protocol.py
python -m pytest -q new_coding_desk/tests/test_esp32_websocket.py
python -m pytest -q esp32_seat_controller/simulator/tests
.\scripts\run_seat1_integration_test.ps1
```

这些测试覆盖认证、版本、非法席位、重复/乱序事件、断线重连、后端恢复、丢失
ACK、传感器异常、命令去重和九席并发模拟。它们不证明真实 PIR、VL53L0X、
WS2812B、供电、Wi-Fi 或温升。

## 兼容路径

- `central`：中央主机直连 Arduino，仅用于单机/台架。
- `distributed`：Windows Seat Agent 兼容路径。
- `esp32`：正式新路径，每席设备直连后端。

不得在 Android 或手势模块复制 ESP32 协议实现。协议变更必须同时更新权威
协议、后端 codec、固件、模拟器和自动测试。
