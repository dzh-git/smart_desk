# CONFIG_SPEC.md

# SmartDesk Gesture Controller 配置参数规范

## 1. 文档目的

本文档用于统一 SmartDesk Gesture Controller 项目的所有可调参数。

后续涉及手势阈值、冷却时间、鼠标灵敏度、安全超时、摄像头参数、调试开关等内容，必须优先写入配置层，不允许散落在业务代码中。

本文档重点解决以下问题：

1. 哪些参数可以调整。
2. 参数默认值是多少。
3. 参数单位是什么。
4. 参数影响哪些功能。
5. 后续如何支持现场标定和外部配置文件。

---

## 2. 配置设计原则

### 2.1 参数集中管理

所有参数必须集中在：

```text
hands/gesture_config.py
```

后续可以扩展为：

```text
config/default_config.json
config/local_config.json
```

但第一版仍以 `gesture_config.py` 为主。

---

### 2.2 禁止魔法数字

禁止在以下文件中直接写死阈值和时间：

```text
gesture_recognition.py
gesture_state.py
gesture_actions.py
gesture_controller.py
```

错误示例：

```python
if pinch_distance < 0.045:
    ...
```

推荐写法：

```python
if pinch_distance < config.pinch_threshold:
    ...
```

---

### 2.3 参数必须有注释

每个参数至少说明：

```text
含义
默认值
单位
影响范围
调大/调小的效果
```

---

### 2.4 现场可调优先

与用户手势、摄像头角度、屏幕尺寸相关的参数，应优先设计为可调参数。

例如：

```text
pinch_threshold
swipe_threshold_x
mouse_smoothing
solidworks_drag_sensitivity
hand_lost_timeout
```

---

## 3. 当前配置结构

当前 `hands/gesture_config.py` 中与第一版主流程直接相关的字段如下。未列出的兼容字段仍保留在代码中：

```python
from dataclasses import dataclass
from typing import Tuple

@dataclass
class GestureConfig:
    # ── Camera ──────────────────────────────────────────────────────────────
    camera_index: int = 0
    camera_width: int = 640
    camera_height: int = 480
    camera_fps: int = 30
    camera_auto_exposure: float = 0  # Windows DirectShow: 0 = manual
    camera_exposure: int = -5
    camera_brightness: int = 0
    camera_gain: int = 10
    map_margin: int = 50  # legacy alias for controller compat

    # ── Recognizer confidence ───────────────────────────────────────────────
    min_hand_detection_confidence: float = 0.7
    min_hand_presence_confidence: float = 0.6
    min_tracking_confidence: float = 0.5
    min_gesture_confidence: float = 0.65
    max_num_hands: int = 1

    # ── GestureRecognizer (Phase 8) ────────────────────────────────────────
    use_gesture_recognizer: bool = True
    gesture_recognizer_model_path: str = "gesture_recognizer.task"
    fallback_to_rule_gestures: bool = True

    # ── Timing / hold times (seconds) ───────────────────────────────────────
    hand_loss_timeout: float = 1.0
    start_presentation_hold: float = 1.5  # deprecated
    enter_mouse_hold: float = 1.0  # deprecated
    enter_solidworks_hold: float = 1.5  # deprecated
    exit_mode_hold: float = 0.8
    pen_mode_hold: float = 0.5
    erase_hold: float = 0.5  # deprecated
    right_click_hold: float = 0.5  # deprecated
    fit_view_hold: float = 0.5  # deprecated
    isometric_view_hold: float = 0.8  # deprecated

    # ── Cooldowns (seconds) ─────────────────────────────────────────────────
    page_turn_cooldown: float = 0.8
    mode_switch_cooldown: float = 1.0
    click_cooldown: float = 0.35
    right_click_cooldown: float = 0.5
    pen_toggle_cooldown: float = 0.6
    solidworks_view_cooldown: float = 0.8

    # ── Wave / swipe detection ──────────────────────────────────────────────
    wave_threshold: float = 10.0  # legacy, camera-px threshold
    wave_cooldown: float = 1.0
    swipe_threshold_x: float = 0.15
    swipe_threshold_y_limit: float = 0.12
    swipe_time_window: float = 0.8
    iloveyou_swipe_threshold_x: float = 0.22

    # ── Pinch ───────────────────────────────────────────────────────────────
    pinch_click_distance: float = 35.0  # legacy, camera-px
    pinch_threshold: float = 0.045
    pinch_release_threshold: float = 0.065
    pinch_zoom_deadzone: float = 0.01

    # ── Mouse movement (deprecated: mouse mode disabled) ───────────────────
    smoothening: float = 1.0  # legacy
    mouse_smoothing: float = 0.35
    mouse_speed: float = 1.0
    mouse_max_step_px: int = 80
    mouse_fps: int = 20
    drag_cooldown: float = 0.3
    drag_hold_time: float = 0.35
    single_cooldown: float = 0.25
    click_max_movement_px: int = 25
    fist_exit_cooldown: float = 1.0

    # ── Scroll (deprecated: mouse_scroll mode disabled) ─────────────────────
    scroll_threshold_y: float = 0.08
    scroll_amount: int = 5
    scroll_cooldown: float = 0.12
    invert_scroll: bool = False

    # ── SolidWorks ──────────────────────────────────────────────────────────
    solidworks_drag_sensitivity: float = 1.2
    solidworks_zoom_sensitivity: float = 8.0
    solidworks_min_zoom_step: int = 1
    solidworks_deadzone: float = 0.01

    # ── Control-flow tracker (Phase 1) ───────────────────────────────────
    gesture_enter_frames: int = 4
    gesture_enter_window_frames: int = 5
    gesture_keep_grace_frames: int = 6
    gesture_enter_confidence: float = 0.70
    gesture_keep_confidence: float = 0.45
    intent_lost_timeout: float = 0.25
    mode_arm_duration: float = 0.20
    mode_swipe_timeout: float = 3.0
    page_swipe_timeout: float = 2.0
    landmark_smoothing: float = 0.45
    motion_deadzone: float = 0.015
    max_motion_step: float = 0.08
    max_motion_velocity: float = 1.5
    min_motion_duration: float = 0.12
    direction_consistency_frames: int = 3

    # ── Behavior / safety switches ──────────────────────────────────────────
    initial_mode: str = "standby"
    enable_system_mouse: bool = True
    dry_run: bool = False
    show_debug_window: bool = True
    debug_window_topmost: bool = True
    debug_window_always_on_top: bool = True  # legacy alias
    debug_window_scale: float = 1.5
    show_landmarks: bool = True
    show_fps: bool = True
    show_action_log: bool = True
    pause_on_start: bool = False
    start_paused: bool = False  # alias for pause_on_start
    enable_hotkeys: bool = True
    exit_key: str = "q"

    # ── Global hotkeys ───────────────────────────────────────────────────────
    hotkey_toggle_pause: str = "<ctrl>+<alt>+g"
    hotkey_emergency_exit: str = "<ctrl>+<alt>+q"

    # ── Gesture recording / replay ─────────────────────────────────────────
    record_gestures: bool = True
    gesture_record_dir: str = "logs"

    # ── Status broadcast server ─────────────────────────────────────────────
    status_server_enabled: bool = True
    status_server_host: str = "127.0.0.1"
    status_server_port: int = 8765
    status_broadcast_interval: float = 0.2

    # ── Derived (filled lazily) ─────────────────────────────────────────────
    screen_size: Tuple[int, int] = (0, 0)
```

---

## 4. 摄像头参数

### 4.1 camera_index

```text
默认值：0
单位：无
含义：OpenCV 摄像头索引
```

说明：0 通常代表默认摄像头。如果外接 USB 摄像头无法打开，可以尝试 1、2、3。

### 4.2 camera_width / camera_height

```text
默认值：640 × 480
单位：像素
```

影响：分辨率越高，识别画面越清晰，但 CPU 占用更高。推荐：开发调试 640×480，性能优先 320×240。

### 4.3 camera_fps

```text
默认值：30
单位：fps
```

说明：该字段记录目标帧率；实际 FPS 在 debug 窗口显示。

### 4.4 camera_auto_exposure

```text
默认值：0（Windows DirectShow：0 = 手动曝光）
```

说明：摄像头自动曝光设置。Windows DirectShow: 0.25 = manual, 0.75 = auto。Linux V4L2: 0 = manual, 1 = auto。

### 4.5 camera_exposure

```text
默认值：-5
单位：对数尺度
```

说明：手动曝光值（驱动相关，通常 -1 ~ -13）。

### 4.6 camera_brightness

```text
默认值：0
单位：0~60（该摄像头）
```

说明：摄像头亮度设置。

### 4.7 camera_gain

```text
默认值：10
单位：0~100（该摄像头）
```

说明：摄像头增益设置。

---

## 5. 识别置信度参数

### 5.1 min_hand_detection_confidence

```text
默认值：0.7
范围：0.0–1.0
```

调大：

```text
减少误检测
可能导致手刚进入画面时识别慢
```

调小：

```text
更容易检测到手
可能增加误检
```

---

### 5.2 min_gesture_confidence

```text
默认值：0.65
范围：0.0–1.0
```

说明：

```text
如果接入 MediaPipe GestureRecognizer，该参数用于过滤低置信度官方手势。
```

建议：

```text
调试阶段：0.5
演示阶段：0.65–0.75
```

当前 `HandLandmarker` 实际使用 `min_hand_detection_confidence=0.7` 和 `min_tracking_confidence=0.5`。`min_hand_presence_confidence=0.6` 字段已保留，但当前构造参数尚未消费它。

---

## 6. 时间参数

### 6.1 hand_loss_timeout / hand_lost_timeout

```text
字段名：hand_loss_timeout（dataclass 字段）
属性别名：hand_lost_timeout（property，指向同一个值）
默认值：1.0
单位：秒
```

含义：

```text
手离开摄像头画面超过该时间后，同一次连续手丢失事件只触发一次 `release_all`。有效手重新出现后重新布防。

代码中使用：hand_loss_timeout（dataclass 字段）
配置文件中可使用：hand_lost_timeout（property 别名，更符合命名规范）
```

调大：

```text
短暂遮挡不会马上释放
但风险是鼠标键保持更久
```

调小：

```text
更安全
但可能因短暂识别失败频繁释放
```

推荐范围：

```text
0.5–1.2 秒
```

---

### 6.2 start_presentation_hold（已废弃）

> **Deprecated in simplified demo version**
>
> 第一版不再使用 Thumb_Up 启动 PPT，因此此参数已废弃。

原含义：

```text
standby 模式下，Thumb_Up 保持多久触发 F5。
```

**第一版不使用此参数。保留为后续版本参考。**

---

### 6.3 enter_mouse_hold（已废弃）

> **Deprecated in simplified demo version**
>
> 第一版禁用 mouse 模式，因此此参数已废弃。

原含义：

```text
standby 模式下，Pointing_Up 保持多久进入鼠标模式。
```

**第一版不使用此参数。保留为后续版本参考。**

---

### 6.4 enter_solidworks_hold（已废弃）

> **Deprecated in simplified demo version**
>
> 第一版使用 ILoveYou 滑动切换模式，不再使用 HOLD，因此此参数已废弃。

原含义：

```text
standby 模式下，ILoveYou 保持多久进入 SolidWorks 模式。
```

**第一版不使用此参数。使用 iloveyou_swipe_threshold_x 和 mode_switch_cooldown 替代。**

---

### 6.5 exit_mode_hold

```text
默认值：0.8
单位：秒
```

含义：

```text
Closed_Fist 保持多久退出当前模式。
```

说明：

```text
该参数不宜过长，否则紧急停止不够快。
```

---

### 6.6 控制流程稳定参数

以下参数用于 `GestureIntentTracker`，只控制模式切换、PPT 翻页和 SolidWorks 旋转 / 平移 / 缩放的第一阶段迁移流程。

| 参数 | 默认值 | 单位 | 含义 |
| ---- | ---- | ---- | ---- |
| `gesture_enter_frames` | 4 | 帧 | 进入候选所需匹配帧数 |
| `gesture_enter_window_frames` | 5 | 帧 | 进入候选统计窗口 |
| `gesture_keep_grace_frames` | 6 | 帧 | attempt/session 中允许的短暂分类异常帧数 |
| `gesture_enter_confidence` | 0.70 | 0–1 | 官方分类进入候选的最低置信度 |
| `gesture_keep_confidence` | 0.45 | 0–1 | 已进入流程后的保持参考置信度 |
| `intent_lost_timeout` | 0.25 | 秒 | 分类保持失败的最长容忍时间 |
| `mode_arm_duration` | 0.20 | 秒 | ILoveYou 进入模式切换 armed 前的最短稳定时间 |
| `mode_swipe_timeout` | 3.0 | 秒 | 模式切换 attempt 的最长追踪时间 |
| `page_swipe_timeout` | 2.0 | 秒 | 翻页 attempt 的最长追踪时间 |
| `landmark_smoothing` | 0.45 | 0–1 | landmarks 低通滤波中当前观测值权重 |
| `motion_deadzone` | 0.015 | 归一化坐标 | 运动死区 |
| `max_motion_step` | 0.08 | 归一化坐标/帧 | 单帧位移限幅 |
| `max_motion_velocity` | 1.5 | 归一化坐标/秒 | 速度限制 |
| `min_motion_duration` | 0.12 | 秒 | 动态动作最短持续时间 |
| `direction_consistency_frames` | 3 | 帧 | 方向一致性确认帧数 |

约束：

```text
官方分类结果进入候选必须满足 gesture_enter_frames / gesture_enter_window_frames 和 gesture_enter_confidence。
规则回退结果不参与 confidence 判断，但仍必须满足帧数、arm_duration 和轨迹一致性。
raw_gesture=None 且 hand_present=True 只计入分类失败容忍。
hand_present=False 才使用 hand_loss_timeout。
intent_lost_timeout 不得代替 hand_loss_timeout。
位移、速度、死区和轨迹阈值统一使用标准化坐标。
```

---

## 7. 冷却时间参数

### 7.1 page_turn_cooldown

```text
默认值：0.8
单位：秒
```

含义：

```text
PPT 翻页后，至少等待多久才允许下一次翻页。
```

调大：

```text
减少一次挥手触发多页
```

调小：

```text
翻页更灵敏，但容易连续误触
```

---

### 7.2 mode_switch_cooldown

```text
默认值：1.0
单位：秒
```

含义：

```text
模式切换后，短时间内不允许再次切换。
```

---

### 7.3 click_cooldown

```text
默认值：0.35
单位：秒
```

含义：

```text
PINCH 点击后，至少等待多久才允许下一次点击。
```

---

### 7.4 pen_toggle_cooldown

```text
默认值：0.6
单位：秒
```

含义：

```text
进入或退出画笔模式后的冷却时间。
```

---

## 8. 挥手参数

### 8.1 swipe_threshold_x

```text
默认值：0.18
单位：归一化坐标
```

含义：

```text
Open_Palm 在 x 方向移动超过该距离，才认为是左右挥手。
```

调大：

```text
需要更大幅度挥手，误触更少
```

调小：

```text
更灵敏，但容易误翻页
```

---

### 8.2 swipe_threshold_y_limit

```text
默认值：0.12
单位：归一化坐标
```

含义：

```text
挥手时 y 方向移动不能超过该值，否则不认为是水平翻页手势。
```

---

### 8.3 swipe_time_window

```text
默认值：0.8
单位：秒
```

含义：

```text
旧状态机轨迹窗口兼容字段。
第一阶段控制流程驱动后，模式切换使用 mode_swipe_timeout，PPT 翻页使用 page_swipe_timeout。
未迁移的兼容逻辑仍可临时读取 swipe_time_window。
```

---

## 8.x ILoveYou 滑动参数

### 8.x.1 iloveyou_swipe_threshold_x

```text
默认值：0.22
单位：归一化坐标
```

含义：

```text
ILoveYou 手势在 x 方向移动超过该距离，才认为是模式切换滑动。
```

调大：

```text
需要更大幅度滑动，误触更少
```

调小：

```text
更灵敏，但容易误切换模式
```

---

### 8.x.2 垂直限制（复用 swipe_threshold_y_limit）

```text
默认值：0.12
单位：归一化坐标
```

含义：

```text
当前代码没有独立的 `iloveyou_swipe_y_limit` 字段。ILoveYou 滑动复用 `swipe_threshold_y_limit = 0.12`。
```

---

### 8.x.3 时间窗口

```text
默认值：0.8
单位：秒
```

含义：

```text
第一阶段新增 `mode_swipe_timeout = 0.80`，用于 ILoveYou 模式切换 attempt 的最长追踪时间。
旧兼容逻辑可继续读取 `swipe_time_window`，但新 Tracker 不应把模式切换和翻页强行复用同一个时间窗口。
```

---

### 8.x.4 mode_switch_cooldown

```text
默认值：1.0
单位：秒
```

含义：

```text
模式切换后，短时间内不允许再次切换。
```

---

## 9. 捏合参数

### 9.1 pinch_threshold

```text
默认值：0.045
单位：归一化距离
```

含义：

```text
拇指尖和食指尖距离小于该值时，认为进入 PINCH。
```

---

### 9.2 pinch_release_threshold

```text
默认值：0.065
单位：归一化距离
```

含义：

```text
拇指尖和食指尖距离大于该值时，认为释放 PINCH。
```

约束：

```text
pinch_release_threshold 必须大于 pinch_threshold。
```

原因：

```text
使用滞回机制，避免捏合边界抖动。
```

---

### 9.3 pinch_zoom_deadzone

```text
默认值：0.01
单位：归一化距离
```

含义：

```text
SolidWorks 缩放时，PINCH 距离变化小于该值则不触发滚轮。
```

说明：

```text
SolidWorks 缩放必须基于 pinch_distance、pinch_threshold、pinch_release_threshold 和 pinch_zoom_deadzone。
不得依赖 MediaPipe GestureRecognizer 输出名为 PINCH 的静态类别。
```

---

## 10. 鼠标参数（已废弃）

> **Deprecated in simplified demo version**
>
> mouse 模式在第一版简化演示中已禁用。以下参数保留为后续版本兼容，不在第一版代码中使用。

### 10.1 mouse_smoothing

```text
默认值：0.35
范围：0.0–1.0
```

含义：

```text
鼠标移动平滑系数。
```

调大：

```text
鼠标移动更平滑，但延迟更明显
```

调小：

```text
鼠标跟手更快，但抖动更明显
```

---

### 10.2 mouse_speed

```text
默认值：1.0
```

含义：

```text
手势位移映射到鼠标位移的速度倍率。
```

---

### 10.3 mouse_max_step_px

```text
默认值：80
单位：像素
```

含义：

```text
单帧鼠标最大移动距离。
```

目的：

```text
避免识别抖动导致鼠标突然飞走。
```

---

### 10.4 drag_hold_time

```text
默认值：0.35
单位：秒
```

含义：

```text
PINCH 持续多久后，从点击候选变为拖拽。
```

---

### 10.5 click_max_movement_px

```text
默认值：25
单位：像素
```

含义：

```text
PINCH 短按期间，如果移动超过该距离，不再认为是普通点击。
```

---

## 11. 滚轮参数（已废弃）

> **Deprecated in simplified demo version**
>
> mouse_scroll 模式在第一版简化演示中已禁用。以下参数保留为后续版本兼容，SolidWorks 的 PINCH 缩放参数（solidworks_zoom_sensitivity 等）不受影响。

### 11.1 scroll_threshold_y

```text
默认值：0.08
单位：归一化坐标
```

含义：

```text
mouse_scroll 模式下，手在 y 方向移动超过该阈值才触发滚轮。
```

> **已废弃**：第一版简化演示不使用 mouse_scroll 模式，此参数保留为后续版本兼容。

---

### 11.2 scroll_amount

```text
默认值：5
单位：滚轮单位
```

含义：

```text
每次滚动的滚轮步长。
```

---

### 11.3 scroll_cooldown

```text
默认值：0.12
单位：秒
```

含义：

```text
连续滚轮触发的最小间隔。
```

---

## 12. SolidWorks 参数

### 12.1 solidworks_drag_sensitivity

```text
默认值：1.2
```

含义：

```text
手部移动映射到 SolidWorks 中键拖动的倍率。
```

调大：

```text
模型旋转/平移更快
```

调小：

```text
模型控制更细腻
```

---

### 12.2 solidworks_zoom_sensitivity

```text
默认值：8.0
```

含义：

```text
PINCH 距离变化映射到滚轮缩放量的倍率。
```

---

### 12.3 solidworks_min_zoom_step

```text
默认值：1
单位：滚轮单位
```

含义：PINCH 变化超过死区但换算后滚轮量为 0 时，保证至少输出该步长。

---

### 12.4 solidworks_deadzone

```text
默认值：0.01
单位：归一化坐标
```

含义：

```text
SolidWorks 旋转/平移时，手部位移小于该值不触发鼠标移动。
```

---

## 13. 调试参数

### 13.1 show_debug_window

```text
默认值：True
```

含义：

```text
是否显示 OpenCV 调试窗口。
```

---

### 13.2 debug_window_topmost / debug_window_always_on_top

```text
字段名：debug_window_topmost（dataclass 字段）
遗留字段：debug_window_always_on_top（保留为兼容）
默认值：True
```

含义：

```text
调试窗口是否置顶显示。

主要字段：debug_window_topmost
遗留字段：debug_window_always_on_top（为了兼容旧代码保留）
```

---

### 13.3 show_landmarks

```text
默认值：True
```

含义：

```text
兼容配置字段；当前只要启用调试窗口就会绘制关键点，尚未按该字段分支。
```

---

### 13.4 show_fps

```text
默认值：True
```

含义：

```text
兼容配置字段；当前只要启用调试窗口就会显示实时 FPS，尚未按该字段分支。
```

---

### 13.5 show_action_log

```text
默认值：True
```

含义：

```text
兼容配置字段；当前日志和调试信息尚未统一按该字段开关。
```

---

## 14. 安全参数

### 14.1 pause_on_start / start_paused

```text
字段名：pause_on_start（dataclass 字段）
属性别名：start_paused（property，指向同一个值）
默认值：False
```

含义：

```text
启动时光标控制是否暂停。

代码中使用：pause_on_start（dataclass 字段）
配置文件中可使用：start_paused（property 别名，符合规范文档拼写）
```

建议：

```text
现场演示时建议设为 True，避免误触。
双击 .bat 启动时默认为 False（立即激活），可通过 --no-pause-on-start 或 --start-unpaused 参数覆盖。
```

---

### 14.2 dry_run

```text
默认值：False
```

含义：

```text
CLI 状态记录字段。真正决定动作层是否控制系统的是 `enable_system_mouse`；`--no-mouse` 会同时设置 `dry_run=True` 和 `enable_system_mouse=False`。
```

启动示例：

```bash
python -m hands.gesture_controller --no-mouse
```

---

### 14.3 enable_hotkeys

```text
默认值：True
```

含义：

```text
是否启用 Ctrl+Alt+G 和 Ctrl+Alt+Q。
```

建议：

```text
除单元测试外，不应关闭。
```

---

## 15. 命令行覆盖规则

第一版至少支持以下命令行参数：

```bash
python -m hands.gesture_controller --mode presentation
python -m hands.gesture_controller --mode solidworks
python -m hands.gesture_controller --no-debug
python -m hands.gesture_controller --no-mouse
python -m hands.gesture_controller --camera 1
```

> `--mode mouse` 仍作为兼容 CLI 值被解析，但当前状态机禁用了 `mouse` / `mouse_scroll`；进入后会安全释放并回到 `standby`。现场不要使用该参数。

命令行优先级：

```text
命令行参数 > 本地 config 文件 > 默认配置
```

第一版如果没有 config 文件，则：

```text
命令行参数 > gesture_config.py 默认值
```

---

## 16. 后续 config.json 建议

后续可以新增：

```text
config/default_config.json
config/local_config.json
```

示例：

```json
{
  "camera_index": 0,
  "camera_width": 640,
  "camera_height": 480,
  "pinch_threshold": 0.045,
  "pinch_release_threshold": 0.065,
  "swipe_threshold_x": 0.18,
  "page_turn_cooldown": 0.8,
  "mouse_smoothing": 0.35,
  "solidworks_drag_sensitivity": 1.2,
  "start_paused": true,
  "dry_run": false
}
```

要求：

```text
default_config.json 提交到仓库
local_config.json 不提交到仓库
```

---

## 17. 参数标定建议

现场调试时，优先调整以下参数：

```text
pinch_threshold
pinch_release_threshold
swipe_threshold_x
page_turn_cooldown
mouse_smoothing
mouse_speed
solidworks_drag_sensitivity
solidworks_zoom_sensitivity
hand_loss_timeout（并提供 hand_lost_timeout 属性别名）
```

标定顺序：

```text
1. 摄像头角度和光照
2. 手部关键点稳定性
3. PINCH 阈值
4. Open_Palm 左右挥手阈值
5. 鼠标移动灵敏度
6. SolidWorks 旋转/平移/缩放灵敏度
7. 冷却时间
8. 手丢失释放时间
```

---

## 18. 第一版必须配置化的参数

第一版必须配置化：

```text
camera_index
camera_width
camera_height
hand_lost_timeout
pinch_threshold
pinch_release_threshold
swipe_threshold_x
swipe_threshold_y_limit
mode_swipe_timeout
page_swipe_timeout
page_turn_cooldown
click_cooldown
mouse_smoothing
mouse_speed
solidworks_drag_sensitivity
solidworks_zoom_sensitivity
gesture_enter_frames
gesture_enter_window_frames
gesture_keep_grace_frames
gesture_enter_confidence
gesture_keep_confidence
intent_lost_timeout
mode_arm_duration
landmark_smoothing
motion_deadzone
max_motion_step
max_motion_velocity
min_motion_duration
direction_consistency_frames
start_paused
dry_run
show_debug_window
```

暂缓配置化：

```text
复杂多用户配置
不同应用单独配置文件
GUI 参数调节面板
远程配置同步
```

---

## 19. 结论

配置层的目标是：

```text
参数集中
含义清楚
现场可调
避免魔法数字
不改代码也能调试体验
```

后续开发中，凡是涉及阈值、时间、灵敏度、安全超时的内容，都必须进入配置层。
