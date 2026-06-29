# SmartDesk Gesture Controller

这是一个独立的 Windows 本地手势控制程序，用摄像头识别手势，并通过 `pyautogui` 模拟鼠标、键盘操作，用于控制中央主机上的 `/display` 大屏、PPT、SolidWorks 或其他桌面程序。

它不属于 SmartDesk 前端、FastAPI 后端或语音识别模块。它只需要和会议桌系统同时运行在中央主机上。

## 目录结构

```text
smartdesk_gesture_controller/
  hands/
    gesture_config.py        # 配置与 CLI 参数
    gesture_actions.py       # pyautogui 动作层 + FakeDriver 测试驱动
    gesture_state.py         # 手势模式状态机
    gesture_recognition.py   # MediaPipe 手势识别与分类
    gesture_status_server.py # 本地状态广播 ws://127.0.0.1:8765
    gesture_controller.py    # 主循环入口
  tests/
    test_gesture_*.py
  requirements.txt
  start_gesture.bat
  README.md
```

## 安装

在 Windows 中进入本目录，创建并激活虚拟环境，再安装依赖：

```bat
cd /d D:\Ai_project\smart_desktop\smartdesk_gesture_controller
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

如果只运行单元测试，仍建议安装 `pytest`。真实摄像头控制需要 `mediapipe`、`opencv-python`、`pyautogui`、`keyboard`、`pynput`（可选兼容）等依赖。

> **注意**：以下所有 `python` 命令均在 `.venv\Scripts\` 下执行。如果直接使用系统 `python` 会提示 `No module named 'cv2'`。推荐双击 `start_gesture.bat` 或先激活虚拟环境再手动运行。

## 启动方式

推荐使用启动脚本（双击 `start_gesture.bat`），它会自动使用 `.venv\Scripts\python.exe` 并检查模型文件。

如果需要手动运行，务必使用虚拟环境解释器：

### 1. 安全 dry-run 验证

只识别手势，不控制系统鼠标键盘：

```bat
.venv\Scripts\python -m hands.gesture_controller --no-mouse
```

### 2. 正式启动

默认启动后处于暂停/standby，需要按 `Ctrl+Alt+G` 恢复控制：

```bat
.venv\Scripts\python -m hands.gesture_controller
```

### 3. 使用启动脚本

```bat
start_gesture.bat
```

### 4. 指定模式

PPT / 浏览器翻页：

```bat
.venv\Scripts\python -m hands.gesture_controller --mode presentation
```

通用鼠标控制：

```bat
.venv\Scripts\python -m hands.gesture_controller --mode mouse
```

### 5. 常用参数

```text
--camera N             指定摄像头编号，默认 0
--mode presentation    启用后进入演示翻页模式
--mode mouse           启用后进入鼠标控制模式
--no-mouse             dry-run，不控制系统鼠标键盘
--no-debug             不显示 OpenCV 调试窗口
--no-server            不启动 ws://127.0.0.1:8765 状态广播
--no-pause-on-start    启动后直接激活，不等待 Ctrl+Alt+G
--start-unpaused       同 --no-pause-on-start
```

## 停止方式

优先使用：

```text
Ctrl+Alt+G   暂停 / 恢复（全局热键，由 keyboard 库实现）
Ctrl+Alt+Q   紧急退出，释放鼠标后退出
q / Esc      在调试窗口中退出
p / Space    在调试窗口中暂停 / 恢复（keyboard 全局热键失效时的兜底）
Ctrl+C       在启动终端中停止进程
```

如果鼠标处于拖动状态，退出流程会调用 `release_all()`，避免鼠标左键长期按住。

## 手势映射

### standby 待机模式

```text
Thumb_Up 保持 1.5 秒：启动 PPT 演示（F5），进入 presentation
Pointing_Up 保持 1.0 秒：进入 mouse 鼠标模式
ILoveYou 保持 1.5 秒：进入 solidworks 模式
Open_Palm：不触发动作（避免误触）
Closed_Fist：释放所有按键，保持待机
```

### presentation 演示模式

```text
张开手掌向右挥动：下一页 / right
张开手掌向左挥动：上一页 / left
Victory 保持 0.5 秒：进入画笔模式（Ctrl+P），进入 presentation_pen
Thumb_Down 保持 0.5 秒：擦除画笔痕迹（E）
Thumb_Up 保持 0.5 秒：取消画笔（Ctrl+A），保持 presentation
Closed_Fist 保持 0.8 秒：退出演示（Esc + release_all），回 standby
```

翻页使用 swipe_threshold_x / swipe_threshold_y_limit / swipe_time_window / page_turn_cooldown
参数控制，一次挥手最多翻一页。

### presentation_pen 画笔模式

```text
Pointing_Up 移动：移动画笔/指针
PINCH 捏合开始：按下左键画线 mouse_down("left")
PINCH 保持 + 移动：持续画线
PINCH 释放：停止画线 mouse_up("left")
Thumb_Down 保持 0.5 秒：擦除画笔痕迹（E）
Thumb_Up 保持 0.5 秒：退出画笔（mouse_up + Ctrl+A），回 presentation
Closed_Fist 保持 0.8 秒：退出演示（mouse_up + Esc + release_all），回 standby
手丢失超过 1 秒：mouse_up("left") + release_all，保持 presentation_pen
```

PINCH 使用 pinch_threshold / pinch_release_threshold 滞回机制，避免边界抖动。

### mouse 鼠标模式

```text
单指（Pointing_Up）：移动鼠标
PINCH 短按：左键单击 click("left")
PINCH 长按（>= drag_hold_time）：拖拽 mouse_down("left")
PINCH 长按 + 移动：持续拖拽移动
PINCH 释放（拖拽中）：释放左键 mouse_up("left")
Victory 保持 0.5 秒：进入滚轮模式 mouse_scroll
Thumb_Down 保持 0.5 秒：右键单击 click("right")
Closed_Fist 保持 0.8 秒：release_all，回 standby
手丢失超过 1 秒：release_all，清除拖拽状态，保持 mouse
```

PINCH 使用滞回机制（pinch_threshold / pinch_release_threshold），避免边界抖动。
短按与长按通过 drag_hold_time 和 click_max_movement_px 区分。
鼠标移动使用 mouse_smoothing 平滑、mouse_speed 速度倍率、mouse_max_step_px 限速。

### mouse_scroll 滚轮模式

```text
Victory 向上移动：scroll(+amount) 向上滚动
Victory 向下移动：scroll(-amount) 向下滚动
Pointing_Up 保持 0.5 秒：回 mouse 模式
Closed_Fist 保持 0.8 秒：release_all，回 standby
手丢失超过 1 秒：release_all，回 mouse 模式
```

滚轮方向：手向上 = 向上滚动（放大视图方向），手向下 = 向下滚动。
只有 mouse_scroll 模式允许 Victory 上下移动触发滚轮，普通 mouse 模式不会误触。
mouse_scroll 中 PINCH 不触发点击，Thumb_Down 不触发右键，Open_Palm 不触发动作。

### solidworks 模式

```text
Open_Palm + 移动：mouse_down("middle") + move_rel — 模型旋转
Victory + 移动：key_down("shift") + mouse_down("middle") + move_rel — 模型平移
PINCH 距离变化：scroll(+/-amount) — 模型缩放
Thumb_Up 保持 0.5 秒：press("f") — 缩放全部拟合
ILoveYou 保持 0.8 秒：hotkey("ctrl","7") — 等轴测视图
Closed_Fist 保持 0.8 秒：release_all，回 standby
手丢失超过 1 秒：release_all（释放 middle + shift），保持 solidworks
```

旋转/平移/缩放互斥：同一时间只执行一种连续动作，切换时先释放前一个动作的按键。
旋转和平移使用 solidworks_drag_sensitivity 控制灵敏度，solidworks_deadzone 过滤抖动。
缩放使用 pinch_zoom_deadzone 死区和 solidworks_zoom_sensitivity 灵敏度。
PINCH 距离增大 → scroll(+) 缩放放大；距离减小 → scroll(-) 缩放缩小。

### paused 暂停模式

```text
Ctrl+Alt+G：暂停/恢复（恢复后一律回 standby，由 keyboard 库全局热键）
Ctrl+Alt+Q：紧急退出（release_all 后退出）
p / Space：在调试窗口中暂停/恢复（keyboard 全局热键失效时兜底）
q / Esc：在调试窗口中退出
暂停中任意手势不触发硬件动作
```

## 本地状态广播

程序默认启动：

```text
ws://127.0.0.1:8765
```

广播内容示例：

```json
{
  "mode": "mouse",
  "gesture": "single_finger",
  "action": "Single-finger mouse",
  "camera_ok": true,
  "control_enabled": true,
  "paused": false,
  "fps": 29.4,
  "connected_clients": 0,
  "timestamp": 1718600000.0
}
```

这个接口只用于未来大屏显示手势状态；不控制 SmartDesk 业务。

## 测试

```bat
.venv\Scripts\python -m pytest tests -q
```

当前测试不需要真实摄像头，不会控制系统鼠标。共 270 项测试，覆盖：

- ActionIntent / ActionLayer / FakeDriver（阶段 1）
- 状态机 7 模式 + HOLD + cooldown + None 超时（阶段 2）
- PPT 演示模式闭环：Thumb_Up 启动、SWIPE 翻页、Victory 画笔、PINCH 画线、
  Thumb_Down 擦除、Thumb_Up 取消画笔、Closed_Fist 退出（阶段 3）
- 鼠标模式增强：Pointing_Up 移动、PINCH 短按点击/长按拖拽、Victory 滚轮、
  Thumb_Down 右键、Closed_Fist 退出、None 超时释放（阶段 4）
- SolidWorks 查看模式：Open_Palm 旋转、Victory 平移、PINCH 缩放、Thumb_Up 拟合、
  ILoveYou 等轴测、Closed_Fist 退出、旋转/平移/缩放互斥、None 超时释放（阶段 5）

运行单个测试文件：

```bat
.venv\Scripts\python -m pytest tests/test_gesture_state.py -q
.venv\Scripts\python -m pytest tests/test_gesture_actions.py -q
.venv\Scripts\python -m pytest tests/test_gesture_controller.py -q
```

## 模型文件

程序启动时检查以下模型文件是否存在于项目根目录：

```text
hand_landmarker.task        — MediaPipe 手部关键点检测（必需）
gesture_recognizer.task     — MediaPipe 官方手势分类（use_gesture_recognizer=True 时必需）
```

如果模型文件不存在，程序会输出错误并退出：

```text
[Error] Model file not found: hand_landmarker.task
        Expected path: .../hand_landmarker.task
        Please place the model file in the project root before running the demo.

[Error] Model file not found: gesture_recognizer.task
        Expected path: .../gesture_recognizer.task
        Place gesture_recognizer.task in the project root,
        or set use_gesture_recognizer=False to use rule-based fallback only.
```

不要在现场演示时依赖网络下载模型。请提前将模型文件放入项目根目录。

如果暂时没有 `gesture_recognizer.task`，可以在 `gesture_config.py` 中设置 `use_gesture_recognizer=False`，程序会退回到纯 landmarks 规则识别。

## 启动脚本

项目提供多个启动脚本：

```text
start_gesture.bat                 正式启动（默认 mouse 模式）
start_gesture_dry_run.bat         dry-run 标定模式（不控制鼠标键盘）
start_gesture_presentation.bat    直接进入 PPT 演示模式
start_gesture_mouse.bat           直接进入鼠标模式
start_gesture_solidworks.bat      直接进入 SolidWorks 模式
```

所有启动脚本都会检查 `.venv` 和 `hand_landmarker.task` 是否存在。`gesture_recognizer.task` 在 `use_gesture_recognizer=True`（默认）时也会被检查。

## 参数标定

所有可调参数集中在 `hands/gesture_config.py`。现场标定说明详见 `docs/DEPLOYMENT_RUNBOOK.md` 第 11 节。

常用标定参数：

```text
pinch_threshold / pinch_release_threshold   — PINCH 滞回阈值
swipe_threshold_x / page_turn_cooldown      — PPT 翻页灵敏度
mouse_smoothing / mouse_speed               — 鼠标平滑和速度
scroll_threshold_y / scroll_amount          — 滚轮灵敏度
invert_scroll                               — 全局反转滚动方向（mouse_scroll + SolidWorks 缩放）
use_gesture_recognizer                      — 是否启用 MediaPipe GestureRecognizer（默认 True）
min_gesture_confidence                      — GestureRecognizer 置信度阈值（默认 0.65）
fallback_to_rule_gestures                   — 低置信度时是否回退旧规则（默认 True）
solidworks_drag_sensitivity                 — SolidWorks 旋转/平移灵敏度
solidworks_zoom_sensitivity                 — SolidWorks 缩放灵敏度
solidworks_min_zoom_step                    — SolidWorks 缩放最小滚轮步长（避免 amount=0 没反应）
hand_lost_timeout                           — 手丢失超时
```

如果 SolidWorks 缩放方向相反，把 `solidworks_zoom_sensitivity` 设为负值，或把 `invert_scroll` 设为 `True`。
如果鼠标抖动，优先调大 `mouse_smoothing`，调小 `mouse_speed`。
如果 PPT 一次挥手翻多页，优先调大 `page_turn_cooldown`。
如果 SolidWorks 缩放经常没反应，调大 `solidworks_min_zoom_step`（如 2 或 3）。

## 架构说明（阶段 1 整理后）

### ActionIntent 动作意图

状态机 `gesture_state.py` 只输出 `ActionIntent`，不直接调用 pyautogui。所有 13 种动作类型定义如下：

```text
press        按下并释放单个按键
hotkey       组合快捷键（如 Ctrl+P）
mouse_down   按住鼠标键
mouse_up     释放鼠标键
click        鼠标单击
move_to      绝对移动鼠标
move_rel     相对移动鼠标
scroll       滚轮滚动
key_down     按住键盘键
key_up       释放键盘键
release_all  释放所有鼠标键和辅助键
status       状态提示（不控制鼠标键盘）
noop         无动作
```

### ActionLayer 动作层

`gesture_actions.py` 提供统一执行入口：

```python
actions.execute(intents)  # 接受单个 ActionIntent、列表、None 或空列表
```

### release_all 安全释放

`release_all` 无条件释放以下按键，可重复调用，幂等：

```text
mouse_up("left")   mouse_up("middle")   mouse_up("right")
key_up("shift")    key_up("ctrl")       key_up("alt")
```

### 配置层

所有可调参数集中在 `gesture_config.py` 的 `GestureConfig` dataclass 中。旧字段名（`cam_width`、`min_detection_confidence` 等）通过属性别名保持兼容。

### FakeDriver 测试驱动

单元测试使用 `FakeDriver` 替代 pyautogui，记录动作日志但不执行真实系统操作。

## 与 SmartDesk 主项目的关系

- 不修改 SmartDesk 前端。
- 不修改 SmartDesk FastAPI 后端。
- 不修改 WebSocket 业务协议。
- 不依赖会议、投票、字幕、语音识别功能。
- 作为独立 Windows 本地进程运行。

推荐部署方式：会议桌系统正常启动后，另开一个终端或双击 `start_gesture.bat` 启动本程序。

## 常见问题

### 程序启动报 "Model file not found"

确认 `hand_landmarker.task`（以及 `use_gesture_recognizer=True` 时的 `gesture_recognizer.task`）在项目根目录。不要依赖网络下载。

如果暂时没有 `gesture_recognizer.task`，可在 `gesture_config.py` 中设置 `use_gesture_recognizer=False` 退回纯规则识别。

### 程序启动报 "No module named 'cv2'"

使用了系统 `python` 而非虚拟环境内的 Python。请使用 `.venv\Scripts\python -m hands.gesture_controller` 或直接双击 `start_gesture.bat`。

### 摄像头打不开

尝试 `--camera 1` 或 `--camera 2`。关闭其他占用摄像头的软件（微信、腾讯会议、OBS）。如果报错 `No module named 'cv2'`，说明使用了错误的 Python 环境（见上一条）。

### 鼠标不受控

立即按 `Ctrl+Alt+G` 暂停或 `Ctrl+Alt+Q` 退出。调试时先用 `--no-mouse` dry-run 模式。

如果 `Ctrl+Alt+G` 无效，先点击调试窗口使其获得焦点，然后按 `p` 或 `Space` 暂停/恢复；
仍无效时可用 `--start-unpaused` 测试。

### Ctrl+Alt+G 全局热键无效

现象：启动后按 `Ctrl+Alt+G` 没有反应。

原因：当前使用 `keyboard` 库注册全局热键；某些 Windows 环境（如高权限软件、远程桌面）可能注册失败。

处理：

```text
1. 点击调试窗口，使其获得焦点
2. 按 p / Space 暂停/恢复
3. 按 q / Esc 退出
4. 仍无效时加 --start-unpaused 启动：
   .venv\Scripts\python -m hands.gesture_controller --start-unpaused
```

### PPT 一次挥手翻多页

调大 `page_turn_cooldown`（如 1.2 秒）。

### 鼠标抖动

调大 `mouse_smoothing`（如 0.5），调小 `mouse_speed`（如 0.7）。

### PINCH 不容易触发

调大 `pinch_threshold`。使用 dry-run 观察 `pinch_distance` 值。

### SolidWorks 缩放方向相反

把 `solidworks_zoom_sensitivity` 设为负值（如 -8.0）。

### SolidWorks 平移后 Shift 卡住

按 `Ctrl+Alt+Q` 退出程序。确认 `release_all` 包含 `key_up("shift")`。

### 手离开后鼠标/按键没有释放

确认 `hand_lost_timeout` 设置合理（0.5–1.2 秒）。按 `Ctrl+Alt+G` 暂停会触发 `release_all`。