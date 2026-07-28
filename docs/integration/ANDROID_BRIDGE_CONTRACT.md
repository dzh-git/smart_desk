# Android Native Bridge 契约

## 范围

正式会议前端只通过 `new_coding_desk/frontend/src/native` 的 `NativeBridge`
访问原生能力，不在组件中散布 `window.Android` 或 `window.SmartDeskNative`
调用。Android 注入对象名固定为：

```javascript
window.SmartDeskNative
```

浏览器调试使用 `WebNativeBridge`，它不伪造可用摄像头、设备凭据或成功识别。

## 前端接口

```typescript
interface NativeBridge {
  isAvailable(): boolean;
  getDeviceInfo(): Promise<DeviceInfo>;
  getDeviceCredential(): Promise<string>;
  getNativeStatus(): Promise<NativeIdentityStatus>;
  getRegisteredFaces(): Promise<RegisteredFaces>;
  startFaceVerification(): Promise<void>;
  stopFaceVerification(): Promise<void>;
}
```

前端 `getNativeStatus()` 映射 Android 原始方法 `getIdentityStatus()`。Android
方法同步返回 JSON 字符串，适配器将其解析成 Promise，并把立即返回的状态也按
统一事件派发。注册、清理模板、阈值和诊断开关属于本地诊断页能力，不是正式
会议页面 API。

## DeviceInfo

必须字段为 `deviceId`、`seatId`、`serverUrl`、`frontendUrl`、`configured`；
当前实现还返回 `serverBaseUrl`/`frontendBaseUrl` 别名、`appVersion`、
Android 设备信息及 camera/face-model/microphone/bridge 状态。

`getDeviceCredential()` 仅在当前 URL 与配置前端同源、路径严格为
`/seat/{配置 seatId}` 时返回 `device_credential`。诊断页、错误页、错席 URL
和外部网页均返回 `BRIDGE_ACTION_FORBIDDEN`。

## 事件信封

Android 用下列浏览器事件异步通知网页：

```javascript
window.dispatchEvent(
  new CustomEvent("smartdesk-native-event", { detail: envelope })
)
```

信封 schema：

```json
{
  "schemaVersion": 1,
  "eventId": "uuid",
  "type": "identity_status",
  "timestamp": 1785168000000,
  "data": {
    "status": "VERIFIED",
    "personId": "person_001",
    "similarity": 0.82,
    "top1PersonId": "person_001",
    "top1Score": 0.82,
    "top2PersonId": "person_002",
    "top2Score": 0.55,
    "margin": 0.27,
    "thresholdStatus": "PROVISIONAL",
    "verificationLevel": "PROTOTYPE",
    "modelVersion": "se_mobilefacenet_emb256_fp32",
    "message": "..."
  }
}
```

当前事件类型：

| type | 用途 |
|---|---|
| `identity_status` | 注册/验证状态与本地识别证据 |
| `camera_status` | 摄像头启动、运行、停止、错误 |
| `face_detection_status` | `NO_FACE`、单人或 `MULTIPLE_FACES` |
| `app_lifecycle` | `RESUMED`、`PAUSED` |
| `error` | 稳定错误码、消息，不含凭据 |

前端订阅器对每次注册最多记住 256 个 `eventId` 并去重，卸载时必须执行返回的
unsubscribe；页面刷新会建立新订阅。后端幂等表是跨刷新/重试的最终防线。

## 身份状态处理

- `VERIFIED`：只表示 Android 识别到稳定 `personId`；是否签到由后端决定。
- `CALIBRATION_PENDING`：显示并记录，不触发正式签到。
- `UNKNOWN`、`RETRY_REQUIRED`、`MULTIPLE_FACES`、`NO_FACE`：提示用户重试，
  不调用签到。
- `ERROR`：显示原生错误，停止或释放摄像头。
- 用户取消、Activity 暂停和 `stopFaceVerification()` 都必须可重复调用且释放
  摄像头。

当前正式自动提交只接受 `VALIDATED + thresholdStatus=VALIDATED`。显式开发模式
可测试 `PROTOTYPE + PROVISIONAL`，但不可把它显示或记录为 `VALIDATED`。

## WebView 安全

1. 正式页只能导航到已配置 `frontendBaseUrl` 的同源地址。
2. `seatId` 必须为 1–9，URL 席位与设备配置一致。
3. 外部 URL 不在 WebView 中加载；文件页不能进行通用跨源访问。
4. 麦克风只向可信正式席位来源授予 `AUDIO_CAPTURE`。
5. Release 使用 `BuildConfig.DEBUG=false` 关闭 WebView 调试。
6. 配置与令牌加密存储；日志和诊断页不回显已保存令牌。

## 兼容性

当前事件 `schemaVersion=1`。未知事件类型可忽略；畸形信封必须忽略而不是使页面
崩溃。平板 `appVersion` 使用 SemVer，后端默认最低版本为 `0.8.0`。任何 schema
破坏性变更必须先增加兼容解析与自动测试，再提高最低 App 版本。

实现和测试入口：

- `../../new_coding_desk/frontend/src/native/`
- `../../android_tablet/android-app/app/src/main/java/com/smartdesk/tablet/bridge/AndroidBridge.kt`
- `../../android_tablet/android-app/app/src/test/`
