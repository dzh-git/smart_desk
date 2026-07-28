# 稳定身份与签到契约

## 身份模型

`Person.id` 是跨会议稳定的 `personCode`，也是 Android 人脸模板键。
`Attendee.id` 仍是某场会议的临时记录；`Attendee.person_id` 可空以兼容历史数据，
但同一会议内非空 `person_id` 唯一。

中央数据库只保存人员、参会关系和身份事件元数据。照片、embedding、诊断裁剪
始终留在 Android App 私有存储。

启动时后端使用可重复执行的 SQLite 兼容迁移创建/补齐 `people`、
`tablet_devices`、`identity_checkin_events` 和 `attendees.person_id`。升级前仍
必须备份数据库文件；回滚旧版本前恢复该备份。

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
  "deviceId": "tablet-seat-01",
  "seatId": 1,
  "deviceToken": "unique-random-token-at-least-24-chars",
  "enabled": true
}
```

后端只保存 PBKDF2 加盐哈希。重复预配同一设备会轮换令牌；一个席位只能绑定一
台平板。设备令牌随后由 Android 安全存储保存。

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
  "deviceId": "tablet-seat-01",
  "deviceSeatId": 1,
  "status": "VERIFIED",
  "similarity": 0.82,
  "thresholdStatus": "PROVISIONAL",
  "verificationLevel": "PROTOTYPE",
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
8. 席位为 `occupied_unchecked`，人员未在其他席位签到，席位未绑定他人。
9. 调用现有 `SeatService.check_in`，不在路由中复制状态机。
10. Seat、Attendee、IdentityCheckInEvent 单事务提交；提交后才广播一次
    `check_in`。

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
| `SEAT_NOT_OCCUPIED` | 传感器尚未使席位进入待签到 |
| `ATTENDEE_ALREADY_CHECKED_IN`、`SEAT_ALREADY_BOUND` | 人员/席位冲突 |
| `RATE_LIMITED` | 设备/席位每分钟请求超限，按 `Retry-After` 重试 |

Pydantic 请求格式错误为 HTTP 422。业务拒绝不会部分写入 Seat、Attendee 或
幂等事件。

## 运行门禁

| 配置 | 默认 | 约束 |
|---|---:|---|
| `SMARTDESK_ALLOW_PROTOTYPE_IDENTITY_CHECKIN` | `false` | 仅开发联调 |
| `SMARTDESK_IDENTITY_MAX_EVENT_AGE_SECONDS` | `120` | 10–600 |
| `SMARTDESK_IDENTITY_MAX_FUTURE_SKEW_SECONDS` | `30` | 1–120 |
| `SMARTDESK_IDENTITY_RATE_LIMIT_PER_MINUTE` | `60` | 1–600 |

75 次标定未完成、陌生人误接受未验收或模型许可证未解除时，不得把开发开关用于
正式自动签到。

权威 HTTP 细节仍以
[API_SPEC](../../new_coding_desk/docs/API_SPEC.md) 为准。
