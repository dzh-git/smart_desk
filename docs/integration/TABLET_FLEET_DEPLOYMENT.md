# SmartDesk 九台平板极简部署

## 固定拓扑

- 1 台中央主机、1 个独立 AP、9 台平板、9 个席位 ESP32。
- Seat 1 是主持人席；Seat 2–9 是同构参会席。
- 九台平板安装同一个 APK，只允许 `seatId`、设备身份和网络地址不同。
- 中央主机使用固定地址；AP 为所有平板和 ESP32 做 DHCP 地址保留。

Windows 移动热点只用于单席调试，不作为十八个无线终端的正式网络方案。

## 每台平板

优先使用发布提交生成的一键包：

```powershell
powershell -ExecutionPolicy Bypass -File deployment\tablet\build-tablet-deploy.ps1 `
  -DefaultCentralHost 192.168.137.1 -DefaultWifiSsid "SmartDesk"
```

把 `artifacts/SmartDesk-Tablet-Deploy-<commit>.zip` 解压到部署电脑。新平板开启
USB 调试并确认授权后，双击 `DEPLOY_TABLET.bat`，输入 Seat 号，核对设备型号并
输入 `YES`。脚本自动安装统一 APK、授予相机/麦克风权限、设置默认 HOME、接电
常亮、电池白名单，随后打开已经预填 Seat 和中央主机的配置页。

操作者只需在平板上输入服务器预配口令和维护 PIN，保存后回到部署窗口按
Enter；最终报告写入包内 `reports/seat-XX.json`。包和报告都不包含维护 PIN、
预配口令、Wi-Fi 密码、设备 Token 或人脸模板。

需要在仓库内单独排障时，仍可运行底层脚本：

```powershell
.\scripts\manage_android_tablet.ps1 -Action Configure -SeatId 2 -Apply
```

小米/MIUI 的“允许自启动”和“后台无限制”仍需人工确认；这些厂商页面无法在
所有系统版本上可靠静默配置。

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
