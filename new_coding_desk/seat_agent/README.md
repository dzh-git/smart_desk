# Seat Edge Agent

每个**座位 Windows 终端**上运行的轻量 Python 进程，把本机 Arduino Nano（USB 串口）桥接到中央主机（WebSocket）。

## 它做什么

- 连接中央主机 `ws://<中央IP>:8000/ws/seat/{seat_id}`（长连接）
- **下行**：收到灯光命令（`SET_MODE` / `SET_BRIGHTNESS` / `OFF`）→ 转发给本机 Arduino
- **上行**：Arduino 的 `EVENT PIR`（入座/离座）→ 报给中央 → 触发座位状态机 + 灯效；定时上报在线/当前模式
- 复用 `backend/hardware/arduino_manager.py`，串口协议逻辑只有一份

## 部署到一台座位终端

1. **烧固件**：`arduino_nano_controller/smartdesk_lighting_controller/` 烧到 Nano，EEPROM 写入本座 `seat_id`。
2. **装依赖**（本终端）：
   ```bash
   cd new_coding_desk
   pip install pyserial websockets
   ```
3. **写配置**：复制示例并填值
   ```bash
   cp seat_agent/seat_agent_config.example.json seat_agent_config.json
   ```
   `seat_agent_config.json`：
   ```json
   { "seat_id": 1, "serial_port": "COM5", "central_ws_url": "ws://192.168.1.10:8000" }
   ```
   - `seat_id`：与本座固件 EEPROM、前端 URL 一致（1=主持人，2..9=参会）
   - `serial_port`：本机 Arduino 的 COM 口（设备管理器查看）
   - `central_ws_url`：中央主机地址
4. **运行**（在 `new_coding_desk` 目录，保证 `backend` 可导入）：
   ```bash
   python -m seat_agent
   ```
   也可用环境变量临时覆盖：`SEAT_ID=3 SERIAL_PORT=COM7 CENTRAL_WS_URL=ws://192.168.1.10:8000 python -m seat_agent`

## 中央主机侧

- `config/smartdesk.integration.json` 设 `"deploy_mode": "distributed"`
- 中央主机**不连任何串口**；`/ws/seat/{seat_id}` 端点接收各终端连接，`LightingManager` 经 `SeatGateway` 按 `seat_id` 下发灯光命令。

## 单机开发模式

单台机器测试时把 `deploy_mode` 设为 `"central"`：中央直接开本机串口（不需要跑 seat_agent），逻辑与生产一致。
