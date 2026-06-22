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

## 3. 配置结构建议

建议定义：

```python
from dataclasses import dataclass

@dataclass
class GestureConfig:
    # camera
    camera_index: int = 0
    camera_width: int = 640
    camera_height: int = 480
    camera_fps: int = 30

    # recognizer
    min_hand_detection_confidence: float = 0.6
    min_hand_presence_confidence: float = 0.6
    min_tracking_confidence: float = 0.6
    min_gesture_confidence: float = 0.65

    # timing
    hand_lost_timeout: float = 1.0
    start_presentation_hold: float = 1.5
    enter_mouse_hold: float = 1.0
    enter_solidworks_hold: float = 1.5
    exit_mode_hold: float = 0.8
    pen_mode_hold: float = 0.5
    erase_hold: float = 0.5
    right_click_hold: float = 0.5
    fit_view_hold: float = 0.5
    isometric_view_hold: float = 0.8

    # cooldown
    page_turn_cooldown: float = 0.8
    mode_switch_cooldown: float = 1.0
    click_cooldown: float = 0.25
    right_click_cooldown: float = 0.5
    pen_toggle_cooldown: float = 0.6
    solidworks_view_cooldown: float = 0.8

    # swipe
    swipe_threshold_x: float = 0.18
    swipe_threshold_y_limit: float = 0.12
    swipe_time_window: float = 0.8

    # pinch
    pinch_threshold: float = 0.045
    pinch_release_threshold: float = 0.065
    pinch_zoom_deadzone: float = 0.01

    # mouse
    mouse_smoothing: float = 0.35
    mouse_speed: float = 1.0
    mouse_max_step_px: int = 80
    drag_hold_time: float = 0.35
    click_max_movement_px: int = 25

    # scroll
    scroll_threshold_y: float = 0.08
    scroll_amount: int = 5
    scroll_cooldown: float = 0.12

    # solidworks
    solidworks_drag_sensitivity: float = 1.2
    solidworks_zoom_sensitivity: float = 8.0
    solidworks_deadzone: float = 0.01

    # debug
    show_debug_window: bool = True
    debug_window_always_on_top: bool = True
    show_landmarks: bool = True
    show_fps: bool = True
    show_action_log: bool = True

    # safety
    start_paused: bool = True
    dry_run: bool = False
    enable_hotkeys: bool = True
```

---

## 4. 摄像头参数

### 4.1 camera_index

```text
默认值：0
单位：无
含义：OpenCV 摄像头索引
```

说明：

```text
0 通常代表默认摄像头
如果外接 USB 摄像头无法打开，可以尝试 1、2、3
```

---

### 4.2 camera_width / camera_height

```text
默认值：640 × 480
单位：像素
```

影响：

```text
分辨率越高，识别画面越清晰，但 CPU 占用更高
分辨率越低，速度更快，但手势细节可能变差
```

推荐：

```text
开发调试：640 × 480
性能优先：320 × 240
现场演示：640 × 480
```

---

### 4.3 camera_fps

```text
默认值：30
单位：fps
```

说明：

```text
目标帧率，不保证摄像头一定达到
实际 FPS 应在 debug 窗口显示
```

---

## 5. 识别置信度参数

### 5.1 min_hand_detection_confidence

```text
默认值：0.6
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

---

## 6. 时间参数

### 6.1 hand_lost_timeout

```text
默认值：1.0
单位：秒
```

含义：

```text
手离开摄像头画面超过该时间后，触发 release_all。
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

### 6.2 start_presentation_hold

```text
默认值：1.5
单位：秒
```

含义：

```text
standby 模式下，Thumb_Up 保持多久触发 F5。
```

推荐：

```text
不要低于 1 秒，避免误触启动 PPT。
```

---

### 6.3 enter_mouse_hold

```text
默认值：1.0
单位：秒
```

含义：

```text
standby 模式下，Pointing_Up 保持多久进入鼠标模式。
```

---

### 6.4 enter_solidworks_hold

```text
默认值：1.5
单位：秒
```

含义：

```text
standby 模式下，ILoveYou 保持多久进入 SolidWorks 模式。
```

说明：

```text
SolidWorks 模式会控制中键、Shift 和滚轮，误触风险较高，因此保持时间应略长。
```

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
默认值：0.25
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
用于判断挥手轨迹的时间窗口。
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

---

## 10. 鼠标参数

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

## 11. 滚轮参数

### 11.1 scroll_threshold_y

```text
默认值：0.08
单位：归一化坐标
```

含义：

```text
mouse_scroll 模式下，手在 y 方向移动超过该阈值才触发滚轮。
```

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

### 12.3 solidworks_deadzone

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

### 13.2 debug_window_always_on_top

```text
默认值：True
```

含义：

```text
调试窗口是否置顶。
```

---

### 13.3 show_landmarks

```text
默认值：True
```

含义：

```text
是否在调试窗口显示手部关键点。
```

---

### 13.4 show_fps

```text
默认值：True
```

含义：

```text
是否显示实时 FPS。
```

---

### 13.5 show_action_log

```text
默认值：True
```

含义：

```text
是否在调试窗口或日志中显示动作触发记录。
```

---

## 14. 安全参数

### 14.1 start_paused

```text
默认值：True
```

含义：

```text
程序启动后是否默认暂停。
```

建议：

```text
现场演示和真实控制时必须为 True。
```

---

### 14.2 dry_run

```text
默认值：False
```

含义：

```text
是否只识别手势和输出动作日志，不实际控制鼠标键盘。
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
python -m hands.gesture_controller --mode mouse
python -m hands.gesture_controller --mode solidworks
python -m hands.gesture_controller --no-debug
python -m hands.gesture_controller --no-mouse
python -m hands.gesture_controller --camera 1
```

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
hand_lost_timeout
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
swipe_time_window
page_turn_cooldown
click_cooldown
mouse_smoothing
mouse_speed
solidworks_drag_sensitivity
solidworks_zoom_sensitivity
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
