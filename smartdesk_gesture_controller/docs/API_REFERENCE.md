# SmartDesk Gesture Controller — API Reference (concise)

> 面向开发者的精简接口文档。含函数签名、参数、用途。不含实现细节。

---

## sendinput_utils.py

Windows SendInput 封装，替代 pyautogui，仅 Windows 可用。

### 公共函数

| 函数 | 签名 | 说明 |
|------|------|------|
| `moveTo` | `(x: float, y: float) -> None` | 光标移至绝对屏幕坐标，自动 clamp 到屏幕范围 |
| `moveRel` | `(dx: float, dy: float) -> None` | 光标相对移动 |
| `mouseDown` | `(button: str = "left", x: float\|None = None, y: float\|None = None) -> None` | 按下鼠标按键；传 x/y 则先移动再按下 |
| `mouseUp` | `(button: str = "left", x: float\|None = None, y: float\|None = None) -> None` | 释放鼠标按键 |
| `click` | `(button: str = "left", x: float\|None = None, y: float\|None = None) -> None` | 单击（按下+释放） |
| `scroll` | `(amount: int) -> None` | 垂直滚轮滚动，amount 单位为 WHEEL_DELTA（120/格） |
| `keyDown` | `(key: str) -> None` | 按住键盘按键；key 支持名称字符串（如 `"a"`, `"f1"`, `"shift"`） |
| `keyUp` | `(key: str) -> None` | 释放键盘按键 |
| `press` | `(key: str) -> None` | 按下并释放一个按键 |
| `hotkey` | `(*keys: str) -> None` | 组合键：依次按下，逆序释放 |
| `size` | `() -> Tuple[int, int]` | 返回主屏幕分辨率 (width, height) |

### 支持的 key 名称（部分）

`a`-`z`, `0`-`9`, `f1`-`f12`, `esc`, `enter`, `space`, `tab`, `backspace`, `delete`, `home`, `end`, `pageup`, `pagedown`, `left`, `up`, `right`, `down`, `shift`, `ctrl`, `alt`, `win`, `leftbracket` (`[`), `rightbracket` (`]`)

---

## gesture_camera.py

摄像头抽象层，支持 OpenCV / 工业相机两种后端。

### 工厂函数

| 函数 | 签名 | 说明 |
|------|------|------|
| `create_camera` | `(config: GestureConfig) -> CameraProtocol` | 根据 `config.camera_driver` 创建对应摄像头实例 |

### 实例接口（两类相机均实现）

| 方法 | 签名 | 说明 |
|------|------|------|
| `open` | `() -> self` | 打开摄像头；失败抛异常 |
| `read` | `() -> Tuple[bool, Optional[np.ndarray]]` | 读取一帧；返回 (success, frame) |
| `release` | `() -> None` | 释放摄像头 |

### 配置字段（GestureConfig）

`camera_driver` (`"opencv"` / `"industrial"`), `camera_index`, `camera_width`, `camera_height`, `camera_fps`, `camera_exposure`, `camera_autofocus`

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
| `config_from_args` | `(args: argparse.Namespace) -> GestureConfig` | 从命令行参数构建配置 |
| `resolve_screen_size` | `(config: GestureConfig) -> Tuple[int, int]` | 解析屏幕大小，返回 (w, h) |

### 关键配置字段

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `mode` | str | `"standby"` | 启动模式 |
| `camera_driver` | str | `"opencv"` | 摄像头驱动 |
| `camera_index` | int | `0` | 摄像头索引 |
| `use_gesture_recognizer` | bool | `True` | 是否启用 MediaPipe GestureRecognizer |
| `min_gesture_confidence` | float | `0.5` | 手势识别最低置信度 |
| `pause_on_start` | bool | `False` | 启动时是否暂停 |
| `enable_system_mouse` | bool | `True` | 是否执行真实鼠标/键盘操作 |
| `dry_run` | bool | `False` | dry-run 模式（不执行系统操作） |

> 完整字段见 `CONFIG_SPEC.md`。

---

## gesture_recognition.py

MediaPipe 手部关键点识别与手势判定。

### 数据类

| 类 | 字段 | 说明 |
|----|------|------|
| `HandInput` | `gesture, palm_xy, centroid_xy, index_tip_xy, pinch_distance, timestamp` | 单帧手部输入 |
| `GestureFrame` | `left_hand: Optional[HandInput], right_hand: Optional[HandInput], timestamp` | 一帧的完整识别结果 |

### 主类

| 类/方法 | 签名 | 说明 |
|----------|------|------|
| `HandRecognizer.__init__` | `(config: GestureConfig) -> None` | 初始化 MediaPipe Hands + GestureRecognizer |
| `HandRecognizer.process` | `(frame: np.ndarray) -> GestureFrame` | 输入 BGR 图像，返回手势识别结果 |
| `HandRecognizer.close` | `() -> None` | 释放 MediaPipe 资源 |

### 工具函数

| 函数 | 签名 | 说明 |
|------|------|------|
| `normalize_gesture_name` | `(raw: str) -> str\|None` | 手势名归一化（兼容 MediaPipe 官方名） |
| `check_model_files` | `(use_gesture_recognizer: bool) -> List[str]` | 返回缺失的模型文件路径列表 |

---

## gesture_intent_tracker.py

手势稳定化与去抖，将原始手势流转化为控制事件。

### 数据类

| 类 | 关键字段 | 说明 |
|----|----------|------|
| `GestureFrame` | `hand_present, raw_gesture, gesture_confidence, palm_xy, centroid_xy, pinch_distance_norm, timestamp` | 每帧输入 |
| `ControlEvent` | `type, phase, dx, dy, position, reason` | 跟踪器输出事件 |
| `TrackerResult` | `events, stable_gesture, intent_state, debug_info` | `update()` 的返回值 |

### 事件类型常量

`EVT_MODE_SWIPE_LEFT`, `EVT_MODE_SWIPE_RIGHT`, `EVT_PAGE_SWIPE_LEFT`, `EVT_PAGE_SWIPE_RIGHT`, `EVT_ROTATE_BEGIN`, `EVT_ROTATE_UPDATE`, `EVT_ROTATE_END`, `EVT_PAN_BEGIN`, `EVT_PAN_UPDATE`, `EVT_PAN_END`, `EVT_ZOOM_UPDATE`, `EVT_PEN_MODE_TOGGLE`, `EVT_PEN_DRAW_BEGIN`, `EVT_PEN_DRAW_UPDATE`, `EVT_PEN_DRAW_END`, `EVT_FIST_HOLD_COMMITTED`, `EVT_CANCEL`, `EVT_HAND_LOST_TIMEOUT`

### 主类

| 方法 | 签名 | 说明 |
|------|------|------|
| `GestureIntentTracker.__init__` | `(config: GestureConfig) -> None` | 初始化去抖参数 |
| `GestureIntentTracker.update` | `(frame: GestureFrame, current_mode: str, now: float) -> TrackerResult` | 输入一帧，输出控制事件列表 |
| `GestureIntentTracker.reset` | `() -> None` | 重置所有跟踪状态 |
| `GestureIntentTracker.cancel` | `(reason: str = "") -> List[ControlEvent]` | 取消当前 attempt/session，返回结束事件 |

---

## gesture_state.py

手势状态机，将 `ControlEvent` 转化为 `ActionIntent`。

### 数据类

| 类 | 关键字段 | 说明 |
|----|----------|------|
| `ActionIntent` | `type, params: Dict[str, Any]` | 操作意图（如 `"page_next"`, `"rotate"`, `"click"`） |
| `StepResult` | `intents: List[ActionIntent], mode: str` | `step()` 返回值 |

### 主类

| 方法 | 签名 | 说明 |
|------|------|------|
| `GestureState.__init__` | `(config: GestureConfig) -> None` | 初始化状态机 |
| `GestureState.step` | `(hand_input: HandInput, now: float, events: List[ControlEvent] = None) -> StepResult` | 输入手势/事件，输出操作意图列表 |
| `GestureState.reset` | `() -> None` | 重置状态机（切换模式/暂停时调用） |
| `GestureState.mode` | property `-> str` | 当前模式 |
| `GestureState.set_mode` | `(mode: str) -> None` | 切换模式；触发 `release_all` |

### 模式常量（GestureConfig 中定义）

`MODE_STANDBY = "standby"`, `MODE_PRESENTATION = "presentation"`, `MODE_PRESENTATION_PEN = "presentation_pen"`, `MODE_SOLIDWORKS = "solidworks"`

---

## gesture_actions.py

操作执行层，将 `ActionIntent` 转化为真实鼠标/键盘操作。

### 主类

| 方法 | 签名 | 说明 |
|------|------|------|
| `ActionLayer.__init__` | `(config: GestureConfig, dry_run: bool = False, driver: object = None) -> None` | 初始化；传 `driver` 可替换底层实现（测试用） |
| `ActionLayer.apply` | `(intent: ActionIntent, hand_input: HandInput, now: float) -> None` | 执行单个操作意图 |
| `ActionLayer.execute` | `(intents: List[ActionIntent], hand_input: HandInput, now: float) -> None` | 批量执行操作意图列表 |
| `ActionLayer.release_all` | `() -> None` | 释放所有按住的按键/鼠标按钮 |
| `ActionLayer.enabled` | property `-> bool` | 当前是否启用（未暂停） |
| `ActionLayer.pause` | `() -> None` | 暂停操作执行 |
| `ActionLayer.resume` | `() -> None` | 恢复操作执行 |

### FakeDriver（测试用）

| 类 | 说明 |
|----|------|
| `FakeDriver` | 不执行真实操作的空实现，记录调用历史供断言 |

---

## gesture_controller.py

主控循环，串联各模块。

### 主类

| 方法 | 签名 | 说明 |
|------|------|------|
| `GestureController.__init__` | `(config: GestureConfig, cap: object = None) -> None` | 初始化控制器；传 `cap` 可注入外部摄像头（测试用） |
| `GestureController.start` | `() -> None` | 启动主循环（阻塞，直到退出） |
| `GestureController.stop` | `() -> None` | 停止主循环（线程安全） |
| `GestureController.pause` | `() -> None` | 暂停手势识别 |
| `GestureController.resume` | `() -> None` | 恢复手势识别 |
| `GestureController.toggle_pause` | `() -> None` | 切换暂停/恢复状态 |

### 全局热键（默认）

`Ctrl+Alt+G`：切换暂停/恢复；`Ctrl+Alt+Q`：退出；调试窗口：`p`/`Space` 暂停，`q`/`Esc` 退出

---

## gesture_replay.py

录制与回放手势识别结果。

### 录制

| 类/方法 | 签名 | 说明 |
|----------|------|------|
| `GestureFrameRecorder.__init__` | `(config: GestureConfig = None) -> None` | 初始化录制器 |
| `GestureFrameRecorder.start` | `() -> None` | 创建录制文件（写入 `logs/`） |
| `GestureFrameRecorder.record_frame` | `(gesture_frame, tracker_result, mode, generated_events, *, state_paused, mode_changed) -> None` | 录制一帧 |
| `GestureFrameRecorder.close` | `() -> None` | 关闭录制文件 |
| `GestureFrameRecorder.enabled` | property `-> bool` | 是否正在录制 |

### 回放

| 函数 | 签名 | 说明 |
|------|------|------|
| `replay_record` | `(record_path: str, config: GestureConfig = None, *, dry_run: bool = True) -> ReplayResult` | 回放录制文件，dry_run=True 时不执行真实操作 |
| `load_record` | `(path: str) -> List[Dict]` | 加载 JSONL 录制文件，返回记录列表 |

### 回放结果

| 类 | 关键字段 | 说明 |
|----|----------|------|
| `ReplayResult` | `frames_processed, events_generated, intents_generated, mode_changes, errors` | 回放统计结果 |

---

## gesture_status_server.py

HTTP 状态查询服务（调试/监控用）。

### 主类

| 方法 | 签名 | 说明 |
|------|------|------|
| `GestureStatusServer.__init__` | `(controller: GestureController, port: int = 8765) -> None` | 初始化 HTTP 服务 |
| `GestureStatusServer.start` | `() -> None` | 启动服务（后台线程，非阻塞） |
| `GestureStatusServer.stop` | `() -> None` | 停止服务 |

### HTTP 接口

| 接口 | 方法 | 返回 |
|------|------|------|
| `/status` | GET | 当前状态 JSON（模式、暂停状态、FPS 等） |
| `/pause` | POST | 暂停手势识别 |
| `/resume` | POST | 恢复手势识别 |

---

## __init__.py

包级公共导出。

### 公开符号

`GestureController`, `GestureConfig`, `config_from_args`, `default_config`, `create_camera`, `HandRecognizer`, `GestureState`, `ActionLayer`, `GestureIntentTracker`, `GestureFrameRecorder`, `replay_record`
