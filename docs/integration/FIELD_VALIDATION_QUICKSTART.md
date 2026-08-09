# 人工验证清单与具体流程

本文件是现场人员需要执行的唯一简化清单。自动测试已经完成的内容不需要重复。
建议按本文顺序执行；没有设备时填写 `HARDWARE_REQUIRED`，不能用模拟结果代替
实物结果。

## 0. 记录基本信息

开始前填写：

```text
日期：
操作者：
中央主机：
Git 提交（运行 git rev-parse --short HEAD 获取）：
安装包版本：
手机/平板编号：
ESP32 席位编号：
现场网络名称：
```

结果只使用三种状态：

- `PASS`：实际操作和现象均符合通过标准。
- `FAIL`：出现错误，停止后续相关步骤并保留日志。
- `HARDWARE_REQUIRED`：缺少对应设备或现场条件，暂时未测。

不要保存或上传设备令牌、人脸照片、embedding、原始语音、真实数据库副本。

## 1. 中央主机安装（约 5 分钟）

### 准备

- 使用 `artifacts/SmartDesk-<提交前12位>.zip`，并确认标记为“内部演示版”。
- 暂时退出可能占用 `5173`、`8000`、`8766` 端口的旧程序。
- 不要把本地语音、人脸模型复制到 Git 仓库。

### 操作

1. 解压安装包。
2. 双击 `INSTALL.bat`，等待出现 `INSTALL PASS`。
3. 双击 `START.bat`，等待出现 `START PASS`。
4. 双击 `DOCTOR.bat`。
5. 浏览器打开 `http://127.0.0.1:5173`。
6. 重启一次 Windows，再次打开页面。

### 通过标准

- `DOCTOR` 中安装、配置、令牌文件、Python、APK、`5173/8000/8766` 均不是
  `FAIL`。
- 页面能打开，会议和席位数据没有丢失。
- 重启后服务能够重新启动。
- 缺少 SolidWorks、ESP32 或平板时显示 `HARDWARE_REQUIRED`，不算软件失败。

### 升级和卸载

1. 升级时直接运行新安装包的 `INSTALL.bat`。
2. 升级后运行 `START.bat` 和 `DOCTOR.bat`，确认原会议数据仍存在。
3. 测试卸载时运行 `UNINSTALL.bat`。
4. 重新安装后确认数据库仍存在；默认卸载不得删除数据库和备份。

记录结果：

```text
安装：PASS / FAIL
重启：PASS / FAIL
升级保留数据：PASS / FAIL
卸载保留数据：PASS / FAIL
```

## 2. 手机或平板（约 3 分钟）

### 准备

- USB 连接中央主机。
- 解锁并保持屏幕亮。
- 接受“允许 USB 调试”弹窗。
- 中央主机已经完成第 1 节。

### 操作

1. 在仓库根目录运行：

   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts\verify_android_device.ps1
   ```

2. 手机出现权限弹窗时允许相机和麦克风。
3. 首次安装时填写中央主机、席位、服务器预配口令和本地维护 PIN，核对确认页的
   物理 deviceId、`tablet-seat-XX` 别名和实体贴纸。
4. 保存后看页面地址和标题，确认是本机贴纸对应的 `/seat/席位号`。
5. 点击一次“身份验证”，确认前置相机打开。
6. 点击停止，确认相机指示图标消失。
7. 关闭 Wi-Fi，等页面显示离线；再打开 Wi-Fi。
8. 等待页面自动回到原席位，确认席位号没有变化。
9. 完整重启平板，确认无需点击图标即可自动拉起并返回同一席位。

### 通过标准

- 脚本显示 APK 安装、版本 `0.8.0`、MainActivity 启动通过。
- 页面不是白屏，席位号正确。
- 启动前设备绑定校验通过，错误 Token 或错席不会进入正式页面。
- 网页按钮能够打开和停止原生相机。
- 停止后摄像头被释放。
- 断网有提示，恢复网络后自动回到正式席位页。
- 系统重启后自动拉起；目标型号已启用厂商自启动白名单且没有阻塞式锁屏。
- 人脸状态仍为 `CALIBRATION_PENDING`；本阶段不要求自动签到。

记录结果：

```text
安装和启动：
席位号：
相机启停：
麦克风权限：
断网恢复：
```

## 3. 一套 ESP32 实物（约 10–15 分钟）

### 准备

- 只先连接 seat 1 的 ESP32、PIR、距离传感器和灯带。
- 检查供电电压、极性、共地和灯带方向。
- 从 `esp32_seat_controller/firmware/include/DeviceConfig.example.h` 生成同目录下
  本机忽略的 `DeviceConfig.h`。
- 只填写 seat 1、服务器地址和该设备的现场令牌；不要提交或截图令牌。

### 操作

1. 连接 ESP32 USB。
2. 编译并烧录：

   ```powershell
   pio run -d esp32_seat_controller\firmware -t upload
   ```

3. 打开 115200 串口，确认设备号和 seat 1 正确且已连接后端。
4. 按顺序执行，每一步停留约 3 秒：

   ```text
   空席 → 入座 → 离座 → 再入座 → 靠近 → 远离
   ```

5. 每一步同时观察串口、席位页面、管理页和实际灯光。
6. 拔掉 ESP32 USB 再接回，确认它自动恢复。
7. 最后运行：

   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts\run_seat1_integration_test.ps1
   ```

### 通过标准

- PIR 和距离变化与实际动作一致。
- seat 1 页面状态随动作变化，没有跳到其他席位。
- 后端下发灯光后收到同一设备的 ACK，实际灯光同步变化。
- 断电重启后设备重新上线，不需要修改数据库。
- 单席软件闭环显示 `PASS (20 rounds)`。

记录结果：

```text
烧录：
PIR：
距离传感器：
灯光和 ACK：
断电恢复：
单席 20 轮：
```

## 4. 真实语音和显示切换（约 5 分钟）

### 操作

1. 在一个席位页开始语音。
2. 说一句中文，例如“现在开始会议”。
3. 说一句英文，例如“Welcome to the meeting”。
4. 停止语音，观察 Windows 麦克风占用图标。
5. 切换当前发言席，再说一句话。
6. 打开 PowerPoint。
7. 启动
   `new_coding_desk/host_services/display_agent/start_display_agent.bat`。
8. 在管理页依次点击 PowerPoint 和会议屏。

### 通过标准

- 中英文字幕都能出现，并属于当前发言席。
- 切席后旧席不再继续上传字幕。
- 停止后麦克风占用图标消失。
- PowerPoint 和会议屏都能切换回来。
- SolidWorks 只在安装了 SolidWorks 的目标主机验证；没有时记录
  `HARDWARE_REQUIRED`。

记录结果：

```text
中文：
英文：
切席：
麦克风释放：
PowerPoint：
SolidWorks：
```

## 5. 九席实物和 30 分钟稳定性（最后执行）

### 接入顺序

不要一次连接九套。按下面顺序接入：

```text
seat 1
→ seat 2、3
→ seat 4、5、6
→ seat 7、8、9
```

每接入一批，只核对三项：

1. 设备贴纸席位号。
2. 平板页面 `/seat/编号`。
3. ESP32 实际灯光对应的席位。

### 操作

1. 先运行软件九席 30 分钟：

   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts\run_nine_seat_simulation.ps1 -DurationMinutes 30
   ```

2. 九套实物在线后，让多个席位同时执行入座、投票和服务呼叫。
3. 随机重启一台平板。
4. 随机重启一台 ESP32。
5. 重启中央后端，确认九席自动恢复。
6. 断开再恢复现场网络。
7. 查看管理页总表，逐席核对在线状态、投票、服务和灯光 ACK。

### 通过标准

- 模拟测试满 30 分钟并显示 PASS。
- 九个平板、九个 ESP32 和九个页面没有错席。
- 并发投票和服务呼叫没有丢失或串席。
- 单机、后端和网络恢复后无需手工改数据库。
- 最终管理页仍显示九个正确席位。

记录结果：

```text
九席编号核对：
并发业务：
平板重启：
ESP32 重启：
后端重启：
网络恢复：
30 分钟稳定性：
```

## 6. 现场供电和安全（必须人工）

1. 断开现场 AP 电源，再恢复，确认中央主机、九台平板和九个 ESP32重新上线。
2. 使用最终电源同时运行九席和灯带至少 30 分钟。
3. 触摸检查电源、接头和线束是否异常发热；有条件时记录温度。
4. 检查线束固定、绝缘、拉力和人员可接触位置。
5. 出现异味、明显升温、重启或闪烁时立即断电并记录 `FAIL`。

记录结果：

```text
AP 断电恢复：
最终供电：
最高温度：
线束安全：
```

## 7. 人脸标定（独立执行，不阻塞前面项目）

### 样本要求

- 3 名已注册人员。
- 2 名陌生人。
- 正常、亮、暗三种光照。
- 每人每种光照 5 次，共 `5 人 × 3 光照 × 5 次 = 75 次`。

### 操作

1. 取得参与人员知情同意。
2. 按人员和光照编号，不记录真实姓名。
3. 每次记录 Top1、Top2、margin、5 帧一致数和最终状态。
4. 对陌生人额外测试经授权的照片或屏幕翻拍。
5. 按 `android_tablet/docs/CALIBRATION.md` 分析阈值。

### 通过限制

- 标定完成前保持 `CALIBRATION_PENDING`。
- 陌生人或翻拍一旦被接受，禁止启用自动签到。
- 即使 75 次通过，也只能标记为 `PROVISIONAL/PROTOTYPE`。
- 未完成商业模型许可、活体检测和安全评估前，禁止正式自动签到。

## 8. 最终签字

```text
中央主机安装：PASS / FAIL
手机/平板：PASS / FAIL / HARDWARE_REQUIRED
单套 ESP32：PASS / FAIL / HARDWARE_REQUIRED
真实语音：PASS / FAIL / HARDWARE_REQUIRED
PowerPoint：PASS / FAIL / HARDWARE_REQUIRED
SolidWorks：PASS / FAIL / HARDWARE_REQUIRED
九席实物：PASS / FAIL / HARDWARE_REQUIRED
供电和安全：PASS / FAIL / HARDWARE_REQUIRED
75 次人脸标定：PASS / FAIL / CALIBRATION_PENDING

遗留问题：

操作者签字：
日期：
```
