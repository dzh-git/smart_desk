# SmartDesk Gesture Controller — API Reference (concise)

> 面向开发者的精简接口文档。含函数签名、参数、用途。不含实现细节。
> 所有签名基于 `hands/` 目录中的实际代码。

---

## sendinput_utils.py

Windows SendInput 封装，替代 pyautogui，仅 Windows 可用（非 Windows 平台 import 时抛 ImportError）。

### 公共函数

| 函数 | 签名 | 说明 |
|------|------|------|
| `moveTo` | `(x: float, y: float) -> None` | 光标移至绝对屏幕坐标，自动 clamp 到屏幕范围，归一化到 0–65535 |
| `moveRel` | `(dx: float, dy: float) -> None` | 光标相对移动 |
| `mouseDown` | `(button: str = "left", x: float\|None = None, y: float\|None = None) -> None` | 按下鼠标按键；传 x/y 则先移动再按下 |
| `mouseUp` | `(button: str = "left", x: float\|None = None, y: float\|None = None) -> None` | 释放鼠标按键 |
| `click` | `(button: str = "left", x: float\|None = None, y: float\|None = None) -> None` | 单击（按下+释放） |
| `scroll` | `(amount: int) -> None` | 垂直滚轮滚动，amount × 120 = WHEEL_DELTA |
| `keyDown` | `(key: str) -> None` | 按住键盘按键；key 支持名称字符串（如 `"a"`, `"f1"`, `"shift"`） |
| `keyUp` | `(key: str) -> None` | 释放键盘按键 |
| `press` | `(key: str) -> None` | 按下并释放一个按键 |
| `hotkey` | `(*keys: str) -> None` | 组合键：依次按下，逆序释放 |
| `size` | `() -> Tuple[int, int]` | 返回主屏幕分辨率 (width, height) |

### 支持的 key 名称（部分）

`a`-`z`, `0`-`9`, `f1`-`f12`, `esc`, `enter`, `space`, `tab`, `backspace`, `delete`, `home`, `end`, `pageup`, `pagedown`, `left`, `up`, `right`, `down`, `shift`, `ctrl`, `alt`, `win`, `leftbracket` (`[`), `rightbracket` (`]`)

---

## gesture_camera.py

摄像头抽象层，支持 OpenCV USB 摄像头和工业 MV SDK 相机两种后端。

### 工厂函数

| 函数 | 签名 | 说明 |
|------|------|------|
| `create_camera` | `(config: GestureConfig) -> CameraInstance` | 根据 `config.camera_driver` 创建对应摄像头实例 |

### 实例接口（两类相机均实现）

| 方法 | 签名 | 说明 |
|------|------|------|
| `read` | `() -> Tuple[bool, Optional[np.ndarray]]` | 读取一帧 BGR 图像；返回 (success, frame) |
| `release` | `() -> None` | 释放摄像头资源 |

### 配置字段（GestureConfig）

`camera_driver` (`"opencv"` / `"industrial"`), `camera_index`, `camera_width`, `camera_height`, `camera_fps`, `camera_auto_exposure`, `camera_exposure`, `camera_brightness`, `camera_gain`

工业相机额外字段：`industrial_sdk_module`, `industrial_camera_index`, `industrial_width`, `industrial_height`, `industrial_fps`, `industrial_exposure_time`, `industrial_exposure_auto`, `industrial_gain`, `industrial_gain_auto`, `industrial_balance_white_auto`, `industrial_fallback_to_opencv`

---

## gesture_config.py

全部配置的数据类与命令行解析。

### 数据类

| 类 | 说明 |
|----|------|
| `GestureConfig` | 全部配置字段的数据类，含默认值 |

### 工厂函数

| 函数 | 签名 | 说明 |
|------|------|------|
| `default_config` | `() -> GestureConfig` | 返回默认配置 |
| `config_from_args` | `(argv: list[str] \| None = None) -> GestureConfig` | 从命令行参数构建配置 |
| `resolve_screen_size` | `(config: GestureConfig) -> GestureConfig` | 解析屏幕大小并写入 `screen_size`，返回新 config |
| `build_arg_parser` | `() -> argparse.ArgumentParser` | 构建命令行参数解析器 |

### 关键配置字段

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `initial_mode` | str | `"standby"` | 启动模式（CLI `--mode` 可覆盖） |
| `camera_driver` | str | `"opencv"` | 摄像头驱动（`"opencv"` 普通摄像头 / `"industrial"` 工业相机） |
| `camera_index` | int | `0` | 摄像头索引 |
| `use_gesture_recognizer` | bool | `True` | 是否启用 MediaPipe GestureRecognizer |
| `min_gesture_confidence` | float | `0.65` | 手势识别最低置信度 |
| `pause_on_start` | bool | `False` | 启动时是否暂停 |
| `enable_system_mouse` | bool | `True` | 是否执行真实鼠标/键盘操作 |
| `dry_run` | bool | `False` | dry-run 模式（不执行系统操作） |
| `hand_loss_timeout` | float | `1.0` | 手丢失超时（秒） |
| `pinch_threshold` | float | `0.045` | PINCH 进入阈值 |
| `pinch_release_threshold` | float | `0.2` | PINCH 释放阈值 |

### 模式常量

`MODE_STANDBY`, `MODE_PRESENTATION`, `MODE_PRESENTATION_PEN`, `MODE_MOUSE`, `MODE_MOUSE_SCROLL`, `MODE_SOLIDWORKS`, `MODE_PAUSED`

> 完整字段见 `CONFIG_SPEC.md`。

---

## gesture_recognition.py

MediaPipe 手部关键点识别与手势判定。Phase 8 接入了 GestureRecognizer 官方 canned gesture 分类。

### 数据类

| 类 | 字段 | 说明 |
|----|------|------|
| `HandInput` | `gesture, palm_xy, centroid_xy, wave_x, pinch_distance` | 单帧手部输入（定义在 `gesture_state.py`，此模块构造） |
| `_FrameResult` | `landmarks, raw_hand_landmarks, gesture, gesture_confidence, gesture_source, raw_gesture` | 单帧识别中间结果（内部使用） |

### 主类

| 类/方法 | 签名 | 说明 |
|----------|------|------|
| `HandRecognizer.__init__` | `(max_num_hands=1, min_detection_confidence=0.7, min_tracking_confidence=0.5, *, use_gesture_recognizer=True, min_gesture_confidence=0.65, fallback_to_rule_gestures=True, gesture_recognizer_model_path="gesture_recognizer.task", gesture_recognizer_fn=None) -> None` | 初始化 HandLandmarker + 可选 GestureRecognizer |
| `HandRecognizer.process_frame` | `(img_rgb: np.ndarray) -> _FrameResult` | 输入 RGB 图像，返回识别结果（landmarks + gesture 元数据） |
| `HandRecognizer.to_hand_input` | `(frame_result: _FrameResult) -> HandInput` | 将 _FrameResult 转换为 HandInput（legacy 兼容路径） |
| `HandRecognizer.to_gesture_frame` | `(frame_result: _FrameResult) -> GestureFrame` | 将 _FrameResult 转换为 GestureFrame（tracker 路径） |
| `HandRecognizer.draw` | `(img_bgr, frame_result: _FrameResult) -> None` | 在 BGR 图像上绘制 landmarks（调试窗口用） |
| `HandRecognizer.close` | `() -> None` | 释放 MediaPipe 资源 |

### 工具函数

| 函数 | 签名 | 说明 |
|------|------|------|
| `normalize_gesture_name` | `(gesture: Gesture \| str \| None) -> str` | 手势名归一化（兼容 MediaPipe 官方名） |
| `classify_gesture` | `(landmarks: LandmarkList) -> Gesture` | 旧 landmarks 规则分类（兜底） |
| `pinch_distance` | `(landmarks: LandmarkList) -> Optional[float]` | 拇指尖(4)与食指尖(8)距离 |
| `centroid_21` | `(landmarks: LandmarkList) -> Optional[Tuple[float, float]]` | 21 点质心（presentation_pen 锚点） |
| `finger_bent` | `(landmarks: LandmarkList, tip_idx: int, root_idx: int) -> bool` | 判断某手指是否弯曲（指尖 y > 根关节 y） |
| `finger_bent_status` | `(landmarks: LandmarkList) -> List[bool]` | 返回 [食指, 中指, 无名指, 小指] 弯曲标志 |
| `is_hand_open` | `(landmarks: LandmarkList) -> bool` | 五指张开（Open_Palm）判定 |
| `is_fist` | `(landmarks: LandmarkList) -> bool` | 四指弯曲（Fist）判定 |
| `palm_center` | `(landmarks: LandmarkList) -> Optional[Tuple[int, int]]` | 手腕(0)与中指根部(9)中点像素坐标 |
| `landmarks_to_hand_input` | `(landmarks: LandmarkList) -> HandInput` | 由 landmarks 构造 HandInput（规则路径，测试/兼容用） |
| `gesture_recognizer_model_exists` | `(model_filename: str = "gesture_recognizer.task") -> bool` | 检查 `gesture_recognizer.task` 是否存在于项目根目录 |

---

## gesture_intent_tracker.py

手势稳定化与去抖，将原始手势流转化为控制事件。纯逻辑模块，无 I/O。

### 数据类

| 类 | 关键字段 | 说明 |
|----|----------|------|
| `GestureFrame` | `hand_present, raw_gesture, gesture_confidence, gesture_source, palm_xy, centroid_xy, index_tip_xy, pinch_distance, hand_size, pinch_distance_norm, timestamp` | 每帧输入（归一化坐标 0–1） |
| `ControlEvent` | `type, phase, attempt_id, session_id, dx, dy, position, reason` | 跟踪器输出事件 |
| `TrackerResult` | `events, stable_gesture, intent_state, active_attempt, active_session, debug_info` | `update()` 的返回值 |
| `GestureAttempt` | `attempt_id, intent_type, phase, start_position, trajectory, committed` | 短期原子动作（模式切换/翻页/缩放） |
| `ControlSession` | `session_id, control_type, phase, pressed_buttons, pressed_keys` | 连续动作（旋转/平移/画笔绘制） |

### 事件类型常量

`EVT_MODE_SWIPE_LEFT`, `EVT_MODE_SWIPE_RIGHT`, `EVT_PAGE_SWIPE_LEFT`, `EVT_PAGE_SWIPE_RIGHT`, `EVT_ROTATE_BEGIN`, `EVT_ROTATE_UPDATE`, `EVT_ROTATE_END`, `EVT_PAN_BEGIN`, `EVT_PAN_UPDATE`, `EVT_PAN_END`, `EVT_ZOOM_UPDATE`, `EVT_PEN_MODE_TOGGLE`, `EVT_PEN_DRAW_BEGIN`, `EVT_PEN_DRAW_UPDATE`, `EVT_PEN_DRAW_END`, `EVT_FIST_HOLD_COMMITTED`, `EVT_CANCEL`, `EVT_HAND_LOST_TIMEOUT`

### 主类

| 方法 | 签名 | 说明 |
|------|------|------|
| `GestureIntentTracker.__init__` | `(config: GestureConfig) -> None` | 初始化去抖参数 |
| `GestureIntentTracker.update` | `(frame: GestureFrame, current_mode: str, now: float) -> TrackerResult` | 输入一帧，输出控制事件列表 |
| `GestureIntentTracker.reset` | `() -> None` | 重置所有跟踪状态（不输出事件） |
| `GestureIntentTracker.cancel` | `(reason: str = "") -> List[ControlEvent]` | 取消当前 attempt/session，返回结束事件 |

---

## gesture_state.py

手势状态机，将 `ControlEvent` + `HandInput` 转化为 `ActionIntent`。纯逻辑模块，无 I/O。

### 枚举

| 枚举 | 说明 |
|------|------|
| `Gesture` | 手势枚举，成员：`NONE, FIST, OPEN_PALM, SINGLE_FINGER, TWO_FINGER, PINCH, UNKNOWN, CLOSED_FIST, POINTING_UP, THUMB_UP, THUMB_DOWN, VICTORY, ILOVEYOU`（legacy 名映射到 spec-canonical 名） |

### 数据类

| 类 | 关键字段 | 说明 |
|----|----------|------|
| `ActionIntent` | `type, key, keys, button, x, y, dx, dy, amount, text, meta` | 声明式操作意图 |
| `HandInput` | `gesture, palm_xy, centroid_xy, wave_x, pinch_distance` | 单帧手部输入（legacy 兼容路径） |
| `StepResult` | `mode, intents, status_text, debug_info, reset_tracker` | `step()` 返回值 |

### ActionIntent 工厂方法

```python
ActionIntent.press(key)           # 单个按键
ActionIntent.hotkey(*keys)        # 组合快捷键
ActionIntent.key_down(key)        # 按住键
ActionIntent.key_up(key)          # 释放键
ActionIntent.mouse_down(button)   # 按住鼠标键
ActionIntent.mouse_up(button)     # 释放鼠标键
ActionIntent.click(button)        # 单击
ActionIntent.move_to(x, y)        # 绝对移动
ActionIntent.move(x, y)           # move_to 别名
ActionIntent.move_rel(dx, dy)     # 相对移动
ActionIntent.scroll(amount)       # 滚轮滚动
ActionIntent.release_all()        # 释放所有
ActionIntent.status(text)         # 状态提示
ActionIntent.noop()               # 空操作
```

### 主类

| 方法 | 签名 | 说明 |
|------|------|------|
| `GestureState.__init__` | `(config: GestureConfig) -> None` | 初始化状态机 |
| `GestureState.step` | `(hand: HandInput, now: float, events: Optional[List[ControlEvent]] = None) -> StepResult` | 输入手势/事件，输出操作意图列表 |
| `GestureState.toggle_pause` | `() -> bool` | 切换暂停/恢复，返回新暂停状态 |
| `GestureState.set_active_mode` | `(mode: str) -> None` | 切换活动模式 |
| `GestureState.activate_from_standby` | `() -> bool` | 从 standby/paused 激活 |
| `GestureState.force_release` | `() -> List[ActionIntent]` | 强制释放所有按键（异常/关闭时调用） |
| `GestureState.should_release_on_hand_loss` | `(now: float) -> bool` | 判断是否需要因手丢失而释放 |

### 属性

| 属性 | 类型 | 说明 |
|------|------|------|
| `GestureState.mode` | `str` | 当前模式（直接属性，非 property） |
| `GestureState.paused` | `bool` | 是否暂停 |

### 模式常量（在 `gesture_config.py` 中定义）

`MODE_STANDBY = "standby"`, `MODE_PRESENTATION = "presentation"`, `MODE_PRESENTATION_PEN = "presentation_pen"`, `MODE_MOUSE = "mouse"`（Phase 9 已禁用，进入即回 standby）, `MODE_MOUSE_SCROLL = "mouse_scroll"`（同上）, `MODE_SOLIDWORKS = "solidworks"`, `MODE_PAUSED = "paused"`

---

## gesture_actions.py

操作执行层，将 `ActionIntent` 转化为真实鼠标/键盘操作（通过 `sendinput_utils`）。

### 主类

| 方法 | 签名 | 说明 |
|------|------|------|
| `ActionLayer.__init__` | `(enable_system_mouse: bool, driver: Optional[Any] = None) -> None` | 初始化；`enable_system_mouse=False` 时使用 FakeDriver |
| `ActionLayer.execute` | `(intents: None \| ActionIntent \| Iterable[ActionIntent]) -> None` | 统一入口，执行一个或多个意图 |
| `ActionLayer.release_all` | `() -> None` | 无条件释放 left/middle/right 鼠标键和 shift/ctrl/alt 键 |
| `ActionLayer.move_to` | `(x: float, y: float) -> None` | 绝对移动（兼容方法） |
| `ActionLayer.left_click` | `() -> None` | 左键单击（兼容方法） |
| `ActionLayer.mouse_down` | `(x=None, y=None) -> None` | 左键按下（兼容方法） |
| `ActionLayer.mouse_up` | `(x=None, y=None) -> None` | 左键释放（兼容方法） |
| `ActionLayer.press` | `(key: str) -> None` | 按键（兼容方法） |
| `ActionLayer.hotkey` | `(*keys: str) -> None` | 组合键（兼容方法） |
| `ActionLayer.using_fake_driver` | `() -> bool` | 是否使用 FakeDriver |
| `ActionLayer.fake_driver` | `() -> FakeDriver` | 获取 FakeDriver（仅 dry-run 时有效） |

### 属性

| 属性 | 类型 | 说明 |
|------|------|------|
| `ActionLayer.is_left_down` | `bool` | 左键是否按下 |
| `ActionLayer.held_buttons` | `set` | 当前按住的鼠标键集合 |
| `ActionLayer.held_keys` | `set` | 当前按住的键盘键集合 |

### FakeDriver（测试用）

| 类 | 说明 |
|----|------|
| `FakeDriver` | 不执行真实操作的空实现；记录调用历史 `calls`（列表）与 `events`（元组列表）供断言。另有 `names()`、`reset()`、`has_event(*prefix)` 辅助方法 |

---

## gesture_controller.py

主控循环，串联识别 → 状态机 → 动作层，管理摄像头/热键/调试窗口/状态服务器。

### 主类

| 方法 | 签名 | 说明 |
|------|------|------|
| `GestureController.__init__` | `(config: Optional[GestureConfig] = None, *, recognizer=None, actions=None, status_server=None, overlay=None, cap=None) -> None` | 初始化控制器；可注入各组件（测试用） |
| `GestureController.start` | `() -> int` | 启动主循环（阻塞）；返回退出码（0=正常, 2=摄像头失败, 3=模型缺失） |
| `GestureController.stop` | `() -> None` | 请求停止主循环（线程安全） |
| `GestureController.status_server_update` | `(**fields) -> None` | 更新状态服务器（安全调用） |
| `GestureController.status_update` | `(**fields) -> None` | 统一推送状态（WS 服务 + 原生 overlay） |
| `GestureController.overlay_update` | `(**fields) -> None` | 仅更新原生 overlay（安全调用） |

### 全局热键（默认）

| 热键 | 动作 | 后端 |
|------|------|------|
| `Ctrl+Alt+G` | 切换暂停/恢复 | `keyboard` 库优先，pynput 兜底 |
| `Ctrl+Alt+Q` | 紧急退出 | `keyboard` 库优先，pynput 兜底 |
| `p` / `Space` | 切换暂停/恢复 | cv2 调试窗口兜底 |
| `q` / `Esc` | 退出 | cv2 调试窗口兜底 |

### 模块函数

| 函数 | 签名 | 说明 |
|------|------|------|
| `check_model_files` | `(project_root: Optional[str] = None, use_gesture_recognizer: bool = True) -> list` | 检查模型文件是否存在，返回缺失路径列表（定义在 `gesture_controller.py`，非 `gesture_recognition.py`） |
| `main` | `(argv: Optional[list] = None) -> int` | CLI 入口（配置日志 + 启动控制器） |

---

## gesture_replay.py

录制与回放手势识别结果。录制写入 JSONL，回放默认 dry-run。

### 录制

| 类/方法 | 签名 | 说明 |
|----------|------|------|
| `GestureFrameRecorder.__init__` | `(config: Optional[GestureConfig] = None) -> None` | 初始化录制器 |
| `GestureFrameRecorder.start` | `() -> None` | 创建录制文件（写入 `logs/`） |
| `GestureFrameRecorder.record_frame` | `(gesture_frame, tracker_result, mode, generated_events, *, state_paused=None, mode_changed=False) -> None` | 录制一帧 |
| `GestureFrameRecorder.close` | `() -> None` | 关闭录制文件 |
| `GestureFrameRecorder.enabled` | property `-> bool` | 是否正在录制 |
| `GestureFrameRecorder.path` | property `-> Optional[str]` | 当前录制文件路径 |
| `GestureFrameRecorder.frame_count` | property `-> int` | 已录制帧数 |

### 回放

| 函数 | 签名 | 说明 |
|------|------|------|
| `replay_record` | `(record_path: str, config: Optional[GestureConfig] = None, *, dry_run: bool = True) -> ReplayResult` | 回放录制文件，dry_run=True 时不执行真实操作 |
| `load_record` | `(path: str) -> List[Dict]` | 加载 JSONL 录制文件，返回记录列表 |

### 回放结果

| 类 | 关键字段 | 说明 |
|----|----------|------|
| `ReplayResult` | `frames_processed, events_generated, intents_generated, mode_changes, errors` | 回放统计结果 |

---

## gesture_status_server.py

WebSocket 状态广播服务（调试/监控用）。运行在 `127.0.0.1:8765`，后台线程。

### 主类

| 方法 | 签名 | 说明 |
|------|------|------|
| `GestureStatusServer.__init__` | `(host: str = "127.0.0.1", port: int = 8765, broadcast_interval: float = 0.2, html_path: Optional[str] = None) -> None` | 初始化 WebSocket 服务；`html_path` 为调试页面 HTML 路径 |
| `GestureStatusServer.start` | `() -> bool` | 启动服务（后台线程，非阻塞）；返回是否成功 |
| `GestureStatusServer.stop` | `() -> None` | 停止服务 |
| `GestureStatusServer.update` | `(**fields: Any) -> None` | 合并部分状态更新（线程安全） |
| `GestureStatusServer.snapshot` | `() -> Dict[str, Any]` | 返回当前状态快照 |

### 广播 JSON 字段

```json
{
  "mode": "standby",
  "gesture": "none",
  "action": "idle",
  "camera_ok": false,
  "control_enabled": true,
  "paused": true,
  "fps": 0.0,
  "connected_clients": 0,
  "timestamp": 0.0,
  "hand_present": false,
  "hand_lost_duration": 0.0,
  "cooldown_until": 0.0,
  "intent_phase": "idle"
}
```

客户端连接后立即收到一次快照，之后每 `broadcast_interval` 秒收到一次更新。

---

## gesture_overlay.py

原生置顶半透明状态浮层（PySide6/Qt，仅 Windows）。运行在独立后台线程，与 `GestureStatusServer` 同构（`start` / `stop` / `update`），显示设备状态、手势、FPS 等。

### 主类

| 方法 | 签名 | 说明 |
|------|------|------|
| `GestureOverlay.__init__` | `(*, click_through: bool = True, topmost_interval: float = 1.0, update_interval: float = 0.05, card_alpha: float = 0.72, width: int = 300, screen_size: Tuple[int, int] = (0, 0)) -> None` | 初始化浮层（参数均为关键字参数） |
| `GestureOverlay.start` | `() -> bool` | 启动 GUI 线程；失败返回 `False` |
| `GestureOverlay.stop` | `() -> None` | 停止浮层（可多次调用） |
| `GestureOverlay.update` | `(**fields: Any) -> None` | 线程安全地合并部分状态（controller 线程调用） |

### 模块级纯函数（派生浮层显示文本与颜色）

| 函数 | 签名 | 说明 |
|------|------|------|
| `derive_camera` | `(snapshot: Dict[str, Any]) -> Tuple[str, str]` | 由状态快照派生摄像头状态文本与颜色 |
| `derive_hand` | `(snapshot: Dict[str, Any]) -> Tuple[str, str]` | 由状态快照派生手部状态文本与颜色 |
| `derive_status` | `(snapshot, hand, now, forced_glow) -> Tuple[str, str, Optional[str]]` | 派生综合状态文本、颜色与高亮颜色 |
| `check_page_turn` | `(snapshot: Dict[str, Any]) -> Optional[str]` | 检测翻页动作，返回 `"next"` / `"previous"` / `None` |

---

## __init__.py

包级公共导出。使用 `__getattr__` 懒加载，导入包本身不触发子模块导入。

### 公开符号

`GestureController`（from `.gesture_controller`）, `Gesture`（from `.gesture_state`）, `ActionIntent`（from `.gesture_state`）

```python
__all__ = ["GestureController", "Gesture", "ActionIntent"]
```
