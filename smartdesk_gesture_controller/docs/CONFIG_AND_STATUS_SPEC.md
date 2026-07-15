# 配置与状态接口规范

配置统一位于 `hands/gesture_config.py` 的 `GestureConfig`。

## 关键配置

| 字段 | 默认值 | 含义 |
|---|---:|---|
| `camera_index` | `0` | OpenCV 摄像头编号。 |
| `use_gesture_recognizer` | `true` | 使用 MediaPipe GestureRecognizer。 |
| `mode_arm_duration` | `0.20` | I Love You 滑动进入 armed 的稳定时间。 |
| `iloveyou_swipe_threshold_x` | `0.18` | 模式滑动最小水平位移。 |
| `mode_switch_cooldown` | `1.0` | 模式切换冷却时间。 |
| `display_agent_enabled` | `true` | 是否启用应用切换。 |
| `display_agent_url` | `http://127.0.0.1:8766` | Display Agent 地址。 |
| `display_agent_timeout_seconds` | `1.5` | 本地请求超时。 |
| `status_server_port` | `8765` | 手势状态 HTTP/WS 端口。 |

其余摄像头、鼠标平滑、SolidWorks 灵敏度和状态卡参数以 dataclass 字段及类型为准；删除字段前必须先清理调用方和测试。

## Display Agent

手势客户端只调用现有接口：

```http
GET  /status
POST /activate  {"app":"smartdesk|powerpoint|solidworks"}
```

不允许调用者传入程序路径、命令或 URL。PowerPoint/SolidWorks 不存在时返回失败，不自动启动。

## 手势状态 WebSocket

`ws://127.0.0.1:8765` 保持原字段，并增加以下可选诊断字段：

| 字段 | 含义 |
|---|---|
| `display_agent_online` | 最近一次探测/切换时 Agent 是否可达。 |
| `display_active_app` | 最近确认激活的应用。 |
| `display_target_app` | 当前模式期望的应用。 |
| `display_switch_state` | `unknown|ready|switching|active|failed|unavailable|disabled`。 |
| `display_switch_error` | 最近失败原因，成功时为空。 |
| `display_switch_at` | 最近探测或切换的 Unix 时间。 |

字段为向后兼容扩展；旧客户端可以忽略。
