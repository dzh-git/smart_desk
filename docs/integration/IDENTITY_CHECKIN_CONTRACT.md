# 稳定身份与签到契约

## 身份模型

`Person.id` 是跨会议稳定的 `personCode`，也是 Android 人脸模板键。
`Attendee.id` 仍是某场会议的临时记录；`Attendee.person_id` 可空以兼容历史数据，
但同一会议内非空 `person_id` 唯一。

中央数据库除人员、参会关系和身份事件元数据外，允许按 `Person.id` 保存
AES-GCM 加密的 256 维模板。原始照片和诊断裁剪始终不得上传；模板只在 Seat 1
Android App 内由当前 ML Kit/对齐/MobileFaceNet 流水线生成。

Seat 1 经长按和本地维护 PIN 进入 `/seat/1/face-templates`，管理本场主持人、
中央模板与 Seat 2–9 分配。写接口必须同时验证设备令牌和后端绑定席位确为 Seat 1，普通
浏览器及其他席位不得管理。授权离页或闲置 10 分钟失效。

Seat 1 Android 冷启动先进入 `/host` 并使用原生维护 PIN 解锁主持人控制台；
`/seat/1` 仅重定向，不再提供普通席位页。主持人本机默认身份仅保存在平板：单个
模板自动默认，多个模板可在隐藏页选择。活动会议的 Seat 1 只有在主持人主动点击
签到时才启动 1:1 人脸验证（debug 模式则调用设备认证放行）；成功后仍停留控制台。

该页面明确区分两类模板：主持人本机模板仅保存在 Seat 1 Android Keystore，
用于 Seat 1 身份验证和主持人分配；中央参会者模板由服务器加密保存，才会出现在 Seat 2–9
分配下拉框。经过维护 PIN 授权后，页面可以调用系统多选照片器，并可逐项删除
本机模板；中央模板正在被待开始或进行中会议使用时，必须先解除分配再删除。

Seat 2–9 在识别前只下载各自席位已分配人员的模板；RSA-OAEP（主摘要 SHA-256、MGF1
摘要 SHA-1）包装 AES-GCM 会话密钥，
本地模板再由 Android Keystore 加密保存。会议、模板集版本、模型哈希、流水线、
维度或阈值策略不匹配时不得签到，也不得回退到旧会议模板。

所有席位均按后端分配的稳定 `Person.id` 执行 1:1 验证。一个目标人员模板即可
启动，相似度阈值和至少 4/5 帧通过仍为放行条件；Top2 与分差不参与放行。

启动时后端使用可重复执行的 SQLite 兼容迁移创建/补齐 `people`、
`tablet_devices`、`identity_checkin_events` 和 `attendees.person_id`。升级前仍
必须备份数据库文件以及 `.smartdesk-runtime/face-template-master.key`；已有模板但
密钥缺失时服务失败关闭，不生成新密钥覆盖。回滚旧版本前恢复该备份。

## 设备预配

后端环境变量 `SMARTDESK_DEVICE_PROVISIONING_TOKEN` 必须为至少 24 字符的管理
密钥。随后调用：

```http
POST /api/tablet-devices/provision
X-SmartDesk-Provisioning-Token: <admin-token>
Content-Type: application/json
```

```json
{
  "deviceId": "tablet-a83f0a90-1f47-4a7d-83ca-53d4b570a201",
  "seatId": 1,
  "deviceToken": "unique-random-token-at-least-24-chars",
  "enabled": true,
  "replaceExisting": false
}
```

后端只保存 PBKDF2 加盐哈希。重复预配同一物理设备会轮换令牌并允许移动到空闲
席位；一个席位只能绑定一台平板。目标席位已有其他设备时默认返回
`DEVICE_SEAT_ALREADY_BOUND`，只有管理员在平板确认替换后发送
`replaceExisting=true` 才解除旧绑定。设备令牌由 Android 生成并仅保存在安全存储。

App 每次加载正式页面前执行：

```http
POST /api/tablet-devices/{deviceId}/validate
X-SmartDesk-Device-Token: <device-token>
Content-Type: application/json

{"seatId": 1, "appVersion": "0.8.0"}
```

设备不存在、禁用、Token 错误、错席或 App 版本不兼容时不得加载 `/seat/{seatId}`。

## 签到请求

```http
POST /api/seats/1/identity-checkin
X-SmartDesk-Device-Token: <device-token>
Content-Type: application/json
```

```json
{
  "eventId": "6fe8e135-15f5-4a3f-946c-8800d7519937",
  "eventTimestamp": 1785168000000,
  "personCode": "person_001",
  "deviceId": "tablet-a83f0a90-1f47-4a7d-83ca-53d4b570a201",
  "deviceSeatId": 1,
  "status": "VERIFIED",
  "similarity": 0.82,
  "thresholdStatus": "VALIDATED",
  "verificationLevel": "VALIDATED",
  "modelVersion": "se-mobilefacenet-ms1mv3-arcface-emb256-v1"
}
```

`eventTimestamp` 为 Unix epoch 毫秒。新事件默认最多旧 120 秒、最多超前 30 秒；
已持久化且证据完全一致的 `eventId` 重试不受时效窗口影响。

## 校验顺序与状态转换

1. `seat_id` 与 `deviceSeatId` 均为 1–9 且相同。
2. 设备已预配、启用、令牌正确，注册席位与 URL 席位一致。
3. 新事件在允许时间窗内，身份 `status=VERIFIED`。
4. `VALIDATED` 必须配 `thresholdStatus=VALIDATED`。
5. `PROTOTYPE` 默认拒绝；仅显式开发开关可配 `PROVISIONAL`。
6. 存在活动会议，Person 存在且启用。
7. 活动会议中恰有一个 `Attendee.person_id` 指向该 Person。
8. 席位为 `vacant` 或 `occupied_unchecked`，人员未在其他席位签到，席位未绑定他人。
9. 空座先在同一事务内迁移为 `occupied_unchecked`，再调用现有
   `SeatService.check_in`，不在路由中复制状态机。
10. Seat、Attendee、IdentityCheckInEvent 单事务提交；空座成功后依次广播
    `seat_occupied`、`check_in`，不广播 `checkin_prompt`。

成功返回标准 `ApiResponse<SeatStateResponse>`，席位状态为 `checked_in`。
相同事件和相同证据重试返回相同状态且不重复广播；相同 `eventId` 搭配不同
设备、席位或人员返回 HTTP 409。

## 稳定错误码

| 错误码 | 含义 |
|---|---|
| `DEVICE_AUTH_FAILED`、`DEVICE_NOT_PROVISIONED` | 凭据缺失/错误或设备未登记 |
| `DEVICE_SEAT_MISMATCH` | URL、请求或注册席位不一致 |
| `IDENTITY_EVENT_STALE`、`IDENTITY_EVENT_FUTURE` | 新证据时间无效 |
| `IDENTITY_EVENT_CONFLICT` | 幂等键被不同证据复用 |
| `IDENTITY_NOT_VERIFIED` | 陌生人/失败状态不允许签到 |
| `FACE_CALIBRATION_PENDING` | 仍待现场标定 |
| `PROTOTYPE_IDENTITY_CHECKIN_DISABLED` | 正式默认拒绝原型等级 |
| `IDENTITY_THRESHOLD_INVALID` | 等级与阈值状态组合不匹配 |
| `NO_ACTIVE_MEETING` | 当前无活动会议 |
| `PERSON_NOT_FOUND`、`PERSON_INACTIVE` | 稳定人员无效 |
| `PERSON_NOT_IN_ACTIVE_MEETING` | 人员不属于当前会议 |
| `ATTENDEE_ALREADY_CHECKED_IN`、`SEAT_ALREADY_BOUND` | 人员/席位冲突 |
| `RATE_LIMITED` | 设备/席位每分钟请求超限，按 `Retry-After` 重试 |
| `DEBUG_IDENTITY_MODE_DISABLED` | 正式模式禁止 Debug 自动放行 |

Pydantic 请求格式错误为 HTTP 422。业务拒绝不会部分写入 Seat、Attendee 或
幂等事件。

## 平板确认离席

已签到页面调用 `POST /api/seats/{seatId}/tablet-vacate`，携带相同设备 Token：

```json
{"deviceId": "tablet-a83f0a90-1f47-4a7d-83ca-53d4b570a201", "deviceSeatId": 1}
```

后端必须校验设备、Token、URL 席位、设备绑定席位和活动会议。成功后解除参会人
与席位绑定，发布 `seat_vacant`；错 Token、错席或无活动会议均拒绝。

## 运行门禁

| 配置 | 默认 | 约束 |
|---|---:|---|
| `SMARTDESK_ALLOW_PROTOTYPE_IDENTITY_CHECKIN` | `false` | 仅开发联调 |
| `SMARTDESK_IDENTITY_MAX_EVENT_AGE_SECONDS` | `120` | 10–600 |
| `SMARTDESK_IDENTITY_MAX_FUTURE_SKEW_SECONDS` | `30` | 1–120 |
| `SMARTDESK_IDENTITY_RATE_LIMIT_PER_MINUTE` | `60` | 1–600 |

`config/smartdesk.integration.json` 的 `identity_mode` 仅允许 `formal` 或
`debug`，缺失或非法值按 `formal` 处理。`debug` 模式仍必须通过设备令牌与席位
绑定校验，只能自动放行当前活动会议分配给该席位的人员；它不上传人脸证据、
不创建 `identity_checkin_events`，界面必须持续显示 Debug 标识。

平板启动时先显示本地连接等待页。Wi-Fi、后端、绑定或前端未就绪时每 5 秒重试，
网络恢复立即重试，不得自动进入诊断页。诊断仅可通过长按维护入口并验证 PIN
进入；无活动会议等待会议，已签到席位重启后沿用后端签到状态。

75 次标定未完成、陌生人误接受未验收或模型许可证未解除时，不得把开发开关用于
正式自动签到。

权威 HTTP 细节仍以
[API_SPEC](../../new_coding_desk/docs/API_SPEC.md) 为准。
