# SmartDesk 九台平板极简部署

## 固定拓扑

- 1 台中央主机、1 个独立 AP、9 台平板、9 个席位 ESP32。
- Seat 1 是主持人席；Seat 2–9 是同构参会席。
- 九台平板安装同一个 APK，只允许 `seatId`、设备身份和网络地址不同。
- 中央主机使用固定地址；AP 为所有平板和 ESP32 做 DHCP 地址保留。

Windows 移动热点只用于单席调试，不作为十八个无线终端的正式网络方案。

## 每台平板

连接并解锁一台平板，确认 USB 调试已授权。先预演：

```powershell
.\scripts\manage_android_tablet.ps1 -Action Configure -SeatId 2 -ExpectedWifiSsid "SmartDesk"
```

确认目标席位后应用配置：

```powershell
.\scripts\manage_android_tablet.ps1 -Action Configure -SeatId 2 -Apply
```

脚本安装统一 APK，授予 `CAMERA`/`RECORD_AUDIO`，将 SmartDesk 设为默认
`HOME`，设置接电常亮、无阻塞锁屏和标准 Android 电池白名单。脚本不接收、
保存或输出维护 PIN、预配口令和设备 Token。

随后在平板本地预配页输入中央主机、Seat ID、预配口令和维护 PIN。小米/MIUI
还需人工确认“允许自启动”和“后台无限制”；这些厂商页面无法在所有系统版本上
可靠静默配置。

最后执行：

```powershell
.\scripts\manage_android_tablet.ps1 -Action Verify -SeatId 2 -ExpectedWifiSsid "SmartDesk"
```

报告写入 `logs/hardware/android-latest/seat-XX.json`。日志中的授权值和 Token
会被脱敏。

## 验收边界

Seat 2 的完整操作可代表 Seat 3–9 的共享业务代码，但每个实体席位仍须分别通过：

- 设备身份与 Seat ID 匹配；
- 正确 Wi-Fi、默认 HOME、相机和麦克风权限；
- 正式页面路径、心跳和 WebSocket；
- 对应 ESP32 的唯一设备身份、灯带接线与灯光 ACK。

全部设备上线后再运行 `scripts\run_nine_seat_simulation.ps1`，并进行九席真实
并发、断网恢复和灯光联动验收。
