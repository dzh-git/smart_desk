# Android 平板模块

本目录是智能会议桌正式产品仓库中的独立 Android 模块。它负责：

- WebView 容器与席位设备配置；
- CameraX、ML Kit、人脸对齐和 MobileFaceNet 本地推理；
- `window.SmartDeskNative` JavaScript Bridge；
- 首次配置、离线恢复和通用设备能力诊断。

会议业务界面仍只有一套，位于 `../new_coding_desk/frontend`。正式运行时
Android App 加载：

```text
{frontendBaseUrl}/seat/{seatId}
```

`diagnostic-web` 不是第二套会议界面。它只在首次配置或管理员显式进入诊断时作为
本地页面使用；网络或中央页面不可用时保持连接等待并自动重试。

## 目录

```text
android_tablet/
├─ android-app/       # APK 与 Android 原生能力
├─ diagnostic-web/    # 本地配置、连接与原生能力诊断页面
├─ model-tools/       # 模型转换与静态验证工具
├─ scripts/           # 真机 WebView/摄像头/身份验证 smoke 脚本
├─ docs/              # 原型标定与验证基线
└─ build-debug.ps1
```

## 设备配置

首次启动会进入本地预配页。App 首次安装生成并加密保存稳定的
`tablet-{UUID}` 物理设备 ID；旧版本已有配置时沿用原设备 ID。管理员只填写
seat 1–9、中央主机、服务器预配口令和 6–12 位本地维护 PIN。中央主机默认推导
后端 `:8000` 与前端 `:5173`，高级模式可覆盖完整 URL。

App 原生层生成独立设备令牌并调用 `/api/tablet-devices/provision`。只有中央主机
确认物理设备 ID、席位和 `tablet-seat-XX` 别名完全一致后，才把配置与设备令牌
写入 Keystore 加密的 App 私有存储；预配口令和 PIN 明文均不保存、不回显。
后续启动会直接加载已保存配置对应的正式席位页，同时在后台检查 health 并调用
设备绑定校验接口。后台校验失败或席位页加载失败时才回退到本地状态页；离线期间
每 5 秒重试，网络恢复时也立即重试。

正式页面的席位头部在“在线”和时间右侧显示 SmartDesk 标识；它随页面正常滚动，
长按 5 秒并通过本地 PIN 后才能进入维护配置页。后端离线或绑定错误时，本地状态页
仍保留原生应急入口，维护页自身不显示该入口。Android 系统广播 `BOOT_COMPLETED`
后会自动拉起单实例 Activity；
现场仍需为目标平板启用厂商自启动白名单并关闭阻塞式锁屏。
主前端会通过 `SmartDeskNative.getDeviceInfo()` 读取 `serverBaseUrl`，并据此连接后端
HTTP API 和会议/语音 WebSocket。

## Bridge 契约

正式前端通过以下统一入口调用原生能力：

```javascript
window.SmartDeskNative.getDeviceInfo()
window.SmartDeskNative.getDeviceCredential()
window.SmartDeskNative.provisionDeviceConfig(configJson)
window.SmartDeskNative.beginMaintenanceHold()
window.SmartDeskNative.cancelMaintenanceHold()
window.SmartDeskNative.getIdentityStatus()
window.SmartDeskNative.getRegisteredFaces()
window.SmartDeskNative.startFaceVerification("assigned-person-id")
window.SmartDeskNative.stopFaceVerification()
```

`getDeviceCredential()` 只允许已配置前端同源且路径严格为
Seat 1 的严格同源 `/host` 或 Seat 2–9 的 `/seat/{seatId}` 正式页面调用；
诊断页、错席页面和外部页面均被拒绝。Seat 1 每次冷启动先通过原生维护 PIN
解锁控制台，PIN 只保存在原生层，进程重启后会话失效。

异步状态统一派发为：

```javascript
window.dispatchEvent(
  new CustomEvent("smartdesk-native-event", {
    detail: {
      schemaVersion: 1,
      eventId: "6fe8e135-15f5-4a3f-946c-8800d7519937",
      type: "identity_status",
      timestamp: 1785168000000,
      data: {
        status: "VERIFIED",
        personId: "person_001",
        similarity: 0.82,
        thresholdStatus: "PROVISIONAL",
        verificationLevel: "PROTOTYPE",
        modelVersion: "se_mobilefacenet_emb256_fp32"
      }
    }
  })
)
```

Android 只报告本地识别状态，不访问会议数据库，也不决定能否签到。75 次现场标定
完成前应保持 `CALIBRATION_PENDING`；即使应用 `PROVISIONAL` 阈值，也只作为
内部原型结果。

人脸照片注册、本机模板管理、中央模板发布、Seat 1 主持人与 Seat 2–9 分配统一在
已通过维护 PIN 的 Seat 1 `/seat/1/face-templates` 页面完成。当前原型阈值输入
默认显示 `0.55`；首次使用或模型哈希/处理流水线变化后必须在该页面重新确认。
阈值只绑定当前模型和处理流水线，不依赖本机或中央模板数量，本机模板变更也不会
重置阈值。诊断页不再提供人脸模板和阈值写操作。

Seat 1 不再加载普通席位页面；`/seat/1` 重定向到 `/host`。主持人只有点击控制台
内的 Seat 1 签到卡后才启动人脸验证，签到成功继续停留在主持人控制台。唯一
本机模板自动成为默认主持人身份，多模板时在模板管理页显式选择。

正式席位页按当前席位已分配的 `Person.id` 执行 1:1 验证；一个人员模板即可
启动，仍须满足相似度阈值与至少 4/5 帧通过。Seat 2–9 每场只同步本席人员模板。

正式后端默认拒绝 `PROTOTYPE` 身份签到。仅在开发联调且已接受现场标定后，才可
临时设置：

```powershell
$env:SMARTDESK_ALLOW_PROTOTYPE_IDENTITY_CHECKIN = "true"
```

同时前端必须显式启用 demo 控件，页面才显示“提交测试签到”。`VALIDATED` 结果
才会走自动提交；当前原型不会自行产生 `VALIDATED`。

## 构建

模型权重受单独许可约束，不提交到仓库。先按 `model-tools/README.md` 转换并放置：

```text
android-app/app/src/main/assets/models/se_mobilefacenet_emb256_fp32.tflite
```

然后执行：

```powershell
.\build-debug.ps1
```

原型冻结基线为原仓库的 `v0.8.0-face-prototype`。当前标定要求见
`docs/CALIBRATION.md`；设备与现场验收统一使用
`../docs/integration/FIELD_VALIDATION_QUICKSTART.md` 和
`../docs/integration/HUMAN_VALIDATION_REQUIRED.md`。
