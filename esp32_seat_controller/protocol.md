# SmartDesk ESP32 Seat Protocol v1

状态：当前；传输：UTF-8 JSON over WebSocket；路径：
`ws://<server>/ws/seat/{seatId}`。单条消息最大 4096 bytes。

## 会话规则

1. ESP32 连接后第一条 v1 消息必须是 `hello`。
2. URL、消息体和设备配置的 `seat_id` 必须一致且在 1–9。
3. 服务端返回 `hello_ack`，随后下发当前预期灯态。
4. ESP32 每 5 秒发送心跳；18 秒无协议活动判定离线并关闭连接。
5. ESP32 上行消息使用每次启动单调递增的 `sequence`。新 `boot_id` 才允许
   sequence 从零重新开始。
6. 入座事件以 `event_id` 幂等；服务端缓存每席最近 256 个事件。
7. 灯光命令以 `command_id` 幂等。2 秒无 ACK 使用相同 ID 重试，最多 3 次。
8. 重连后重新 `hello` 并同步灯态；不得依赖断线前未确认的临时状态。
9. 固件不得打印 Wi-Fi 密码或设备令牌。

## ESP32 → 中央主机

### hello

```json
{
  "schema_version": 1,
  "type": "hello",
  "seat_id": 1,
  "device_id": "esp32-seat-01",
  "firmware_version": "0.1.0",
  "boot_id": "a1b2c3d4-0123",
  "capabilities": ["pir", "vl53l0x", "ws2812b"]
}
```

### heartbeat

```json
{
  "schema_version": 1,
  "type": "heartbeat",
  "seat_id": 1,
  "sequence": 10,
  "uptime_ms": 10000,
  "current_mode": "IDLE",
  "wifi_rssi": -45,
  "sensor_ok": true
}
```

### occupancy

```json
{
  "schema_version": 1,
  "type": "occupancy",
  "seat_id": 1,
  "sequence": 11,
  "event_id": "occupancy-a1b2-11",
  "occupied": true,
  "pir": true,
  "distance_mm": 72,
  "sensor_ok": true
}
```

服务端只把首次接受的事件交给 `SeatService`。重复事件返回
`event_ack.accepted=true, duplicate=true`；新 ID 但旧 sequence 返回
`SEQUENCE_OUT_OF_ORDER`，不会改变席位。

### command_ack

```json
{
  "schema_version": 1,
  "type": "command_ack",
  "seat_id": 1,
  "sequence": 12,
  "command_id": "3d8e7c8f-23b3-4d18-9de4-efbf18a52128",
  "success": true,
  "current_mode": "WELCOME"
}
```

重复命令必须重新 ACK，但不得重新启动会产生副作用的灯效状态机。

### sensor_error

```json
{
  "schema_version": 1,
  "type": "sensor_error",
  "seat_id": 1,
  "sequence": 13,
  "event_id": "sensor-a1b2-13",
  "component": "vl53l0x",
  "error_code": "SENSOR_UNAVAILABLE"
}
```

`sync` 仅包含公共 envelope 和 `sequence`，请求中央重发当前预期灯态。

## 中央主机 → ESP32

### hello_ack

```json
{
  "schema_version": 1,
  "type": "hello_ack",
  "session_id": "uuid",
  "heartbeat_interval_ms": 5000,
  "heartbeat_timeout_ms": 18000
}
```

### lighting

```json
{
  "schema_version": 1,
  "type": "lighting",
  "command_id": "uuid",
  "sequence": 5,
  "mode": "WELCOME",
  "brightness": 80
}
```

合法模式与 `backend/hardware/lighting_modes.py` 一致：
`BOOT`、`IDLE`、`WELCOME`、`MEETING_ACTIVE`、`AGENDA_ACTIVE`、
`VOTE_OPEN`、`VOTE_CLOSED`、`SERVICE_CALL`、`MEETING_ENDED`、
`AI_SPEAKING`、`ERROR`、`OFF`。

### event_ack / protocol_error

```json
{
  "schema_version": 1,
  "type": "event_ack",
  "event_id": "occupancy-a1b2-11",
  "accepted": true,
  "duplicate": false
}
```

```json
{
  "schema_version": 1,
  "type": "protocol_error",
  "error_code": "SEAT_ID_MISMATCH",
  "message": "message seat_id does not match WebSocket path"
}
```

致命错误包括消息过大、不支持的版本、席位不匹配、未先 `hello` 和混用旧协议；
服务端返回错误后以 WebSocket 1008 关闭。字段或乱序错误只拒绝本条消息。

## 旧协议兼容

没有 `schema_version` 且类型为 `pir/status/sync` 的消息仍按 Windows Seat Agent
处理，下行仍为 `{"type":"lighting","cmd":"SET_MODE","arg":"..."}`。同一连接
不得混用旧协议和 v1。
