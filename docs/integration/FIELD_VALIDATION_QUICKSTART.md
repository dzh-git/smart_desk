# 最短现场验证流程

先双击内部演示包的 `INSTALL.bat`，然后双击 `START.bat` 和 `DOCTOR.bat`。
`DOCTOR` 没有 `FAIL` 后再做下面四项。软件会自动保存日志；不要保存人脸照片、
embedding、原始语音、设备令牌或真实数据库副本。

## 1. 手机/平板（约 3 分钟）

你只做四件事：

1. USB 连接并解锁，保持屏幕亮。
2. 接受 USB 调试和权限弹窗。
3. 在仓库运行：

   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts\verify_android_device.ps1
   ```

4. 看一眼：页面是本席 `/seat/编号`；点一次“身份验证”，相机能开，再点停止。

构建、覆盖安装、启动和日志由脚本完成。通过标准：页面不是白屏，席位号正确，
相机停止后系统相机指示消失。断开 Wi-Fi 再恢复一次，页面能回到会议席位页。
人脸结果仍显示 `CALIBRATION_PENDING`，不要求自动签到。

## 2. 一套 ESP32（约 10–15 分钟）

1. 按贴纸接好 ESP32、PIR、距离传感器和灯带，再接 USB。
2. 从 `DeviceConfig.example.h` 生成本机忽略的 `DeviceConfig.h`，只填写 seat 1
   和现场令牌；不要把它提交 Git。
3. 运行 `pio run -d esp32_seat_controller\firmware -t upload`。
4. 按顺序做空席、入座、离座、近距离、远距离动作；每一步只观察页面席位状态
   和灯色是否跟随。

最后运行 `scripts\run_seat1_integration_test.ps1`。它验证同一业务、协议和灯光
ACK 的 20 轮软件闭环；实物动作结果仍以你刚才看到的灯光和传感器为准。

## 3. 真实语音与显示（约 5 分钟）

1. 在席位页开始语音，说一句中文，再说一句英文，然后停止。
2. 确认字幕出现，停止后 Windows 麦克风占用图标消失。
3. 打开 PowerPoint，运行
   `new_coding_desk\host_services\display_agent\start_display_agent.bat`，在管理页
   点 PowerPoint，再点会议屏。

通过标准：字幕属于当前演讲席，切席后旧席不再上传；两个窗口都能切换回来。
SolidWorks 仅在装有 SolidWorks 的最终主机验证。

## 4. 九席和 30 分钟（最后做）

1. 按 `1 → 2/3 → 4/5/6 → 7/8/9` 接入，避免一次接错九套。
2. 每批只核对贴纸席位号、平板页面号和实际灯光号。
3. 先运行软件九席 30 分钟：

   ```powershell
   .\scripts\run_nine_seat_simulation.ps1 -DurationMinutes 30
   ```

4. 九套实物全部在线后，同时做入座、投票、服务呼叫；中途重启任意一套，再
   恢复网络。查看管理页总表是否仍为 9 个正确席位。

AP 断电、最终供电、温度和线束安全必须由现场人员完成。模拟器显示 PASS 不能
替代实物；缺少设备时记录 `HARDWARE_REQUIRED` 即可。

## 人脸最后单独做

75 次标定仍需 3 名注册人员、2 名陌生人和三种光照。未完成商业模型许可、活体
检测和安全评估前，禁止启用正式自动签到。
