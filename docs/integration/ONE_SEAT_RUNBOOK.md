# Seat 1 集成运行手册

本手册分为无实物软件闭环和真实单席联调。前者可自动判定；后者必须按
[人工验收清单](HUMAN_VALIDATION_REQUIRED.md) 留存证据。

## 1. 软件闭环

在仓库根目录运行：

```powershell
.\scripts\run_seat1_integration_test.ps1
```

期望最终输出：

```text
Seat 1 software integration: PASS (20 rounds)
```

测试使用临时数据库、前端 Mock NativeBridge、Android 事件回放和 ESP32 模拟
传输，验证创建会议与稳定人员、入座、身份签到、数据库、会议广播、灯光命令、
ACK、重复/乱序事件、刷新、断线、后端/控制器恢复，并连续执行 20 轮。它不是
真机或硬件证明。

## 2. 真实单席准备

1. 记录当前提交：`git rev-parse HEAD`，确认工作区和测试数据库备份。
2. 给中央主机配置固定局域网 IP；开放可信局域网到 TCP 8000、5173。
3. 将 `config/smartdesk.integration.esp32.example.json` 的内容部署为
   `config/smartdesk.integration.json`；保存原配置以便回滚。
4. 生成三个不同的强随机值：管理预配令牌、平板令牌、ESP32 令牌。不得提交。
5. 确保席位 1 的平板、URL、后端登记、ESP32 配置均使用 seat 1，但设备 ID
   分别为 `tablet-seat-01` 和 `esp32-seat-01`。
6. Debug APK 需要本地研究权重；Release 当前必须被许可证门禁阻断。

示例会话环境：

```powershell
$env:SMARTDESK_DEVICE_PROVISIONING_TOKEN = "<admin-token-24+-chars>"
$env:SMARTDESK_ESP32_DEVICE_TOKENS_JSON = @'
{
  "esp32-seat-01": {
    "seatId": 1,
    "token": "<esp32-token-24+-chars>"
  }
}
'@
```

只有 75 次现场标定已接受为内部 `PROVISIONAL` 后，才可在内部闭环临时设置：

```powershell
$env:SMARTDESK_ALLOW_PROTOTYPE_IDENTITY_CHECKIN = "true"
```

这不使结果成为 `VALIDATED`，也不解除正式发布门禁。

## 3. 启动中央主机

终端 A：

```powershell
Set-Location new_coding_desk
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

终端 B：

```powershell
Set-Location new_coding_desk/frontend
npm run dev -- --host 0.0.0.0
```

从中央主机和同一 Wi-Fi 的另一设备分别访问：

```text
http://<host-ip>:8000/api/health
http://<host-ip>:5173/seat/1
```

后端启动会执行幂等数据库升级。升级前必须复制当前数据库；不要在首次现场启动
时覆盖唯一数据库备份。

## 4. 预配平板与会议数据

预配平板：

```powershell
$base = "http://<host-ip>:8000"
$headers = @{
  "X-SmartDesk-Provisioning-Token" =
    $env:SMARTDESK_DEVICE_PROVISIONING_TOKEN
}
$body = @{
  deviceId = "tablet-seat-01"
  seatId = 1
  deviceToken = "<tablet-token-24+-chars>"
  enabled = $true
} | ConvertTo-Json
Invoke-RestMethod -Method Post `
  -Uri "$base/api/tablet-devices/provision" `
  -Headers $headers -ContentType "application/json" -Body $body
```

在测试数据库创建稳定人员、会议和参会关系：

```powershell
$person = @{ id = "person_001"; name = "测试人员一" } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri "$base/api/people" `
  -ContentType "application/json" -Body $person

$meeting = Invoke-RestMethod -Method Post -Uri "$base/api/meetings" `
  -ContentType "application/json" `
  -Body (@{ title = "Seat 1 联调"; description = "现场验收" } | ConvertTo-Json)
$meetingId = $meeting.data.id

Invoke-RestMethod -Method Post `
  -Uri "$base/api/meetings/$meetingId/attendees" `
  -ContentType "application/json" `
  -Body (@{
    name = "测试人员一"
    title = ""
    personId = "person_001"
  } | ConvertTo-Json)

Invoke-RestMethod -Method Post `
  -Uri "$base/api/meetings/$meetingId/start"
```

已有同名测试数据时不要重复创建；使用 `/admin` 或 GET API 核对并选用新的测试
会议。生产人员资料必须由授权操作者录入。

## 5. 配置设备

Android 首次配置：

```json
{
  "seatId": 1,
  "deviceId": "tablet-seat-01",
  "deviceToken": "<tablet-token-24+-chars>",
  "serverBaseUrl": "http://<host-ip>:8000",
  "frontendBaseUrl": "http://<host-ip>:5173"
}
```

固件将 `DeviceConfig.example.h` 复制为忽略的 `DeviceConfig.h`，填写同一 Wi-Fi、
中央地址、seat 1、`esp32-seat-01` 和 ESP32 独立令牌：

```powershell
pio run -d esp32_seat_controller/firmware
pio run -d esp32_seat_controller/firmware -t upload --upload-port <COM>
pio device monitor -b 115200 -p <COM>
```

没有实物时，只验证网络协议可运行：

```powershell
python -m esp32_seat_controller.simulator.esp32_simulator `
  --server-url ws://<host-ip>:8000 --seats 1
```

## 6. 执行顺序

1. 查看 `/admin` 设备状态，平板与 ESP32 分通道在线。
2. 让 PIR/距离条件满足入座；席位变为 `occupied_unchecked`。
3. 平板出现身份验证提示，启动前置摄像头。
4. 已注册人员完成自然光和补光阶段；网页显示 person、Top1/Top2、分差和等级。
5. 在允许的验证等级下提交，后端返回 `checked_in`。
6. 管理端、席位端和中央大屏都显示同一签到状态。
7. ESP32 收到 `WELCOME`/当前业务灯态，执行后回 ACK。
8. 重复同一事件、刷新页面、短暂断开平板和 ESP32 网络，确认不重复签到且状态
   能恢复。
9. 连续执行 20 次完整流程；每轮结束会议/清理测试状态，不能复用污染数据冒充
   独立成功。

## 7. 证据与故障定位

保存：

- 后端 stdout/stderr 和 `GET /api/hardware/status` 响应；
- Android：`adb logcat -v threadtime SmartDeskTablet:I chromium:I '*:S'`；
- ESP32 115200 串口日志；
- 浏览器控制台/网络面板、每轮事件 ID/命令 ID；
- `logs/verification/verify-all-software.json`；
- 人工验收表、异常截图和复现时间。

定位顺序：健康检查 → 主机防火墙/路由 → 设备席位绑定 → 设备认证 → hello/版本
→ occupancy → identity 等级/时效 → SeatService 业务错误 → lighting ACK。不得用
降低人脸阈值、关闭认证或改数据库来掩盖失败。

## 8. 回滚

停止进程，恢复原 `smartdesk.integration.json` 和数据库备份；平板恢复上一版
APK/配置；ESP32 刷回已知可用固件。不要删除 `identity_checkin_events` 来解决
幂等冲突，先保留日志判断是否使用了错误事件 ID。
