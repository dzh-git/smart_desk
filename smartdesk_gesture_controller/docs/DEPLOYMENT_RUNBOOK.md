# DEPLOYMENT_RUNBOOK.md

# SmartDesk Gesture Controller 部署与演示操作手册

## 1. 文档目的

本文档用于指导 SmartDesk Gesture Controller 在 Windows 电脑上的部署、启动、调试、演示和故障处理。

适用场景：

```text
开发机本地测试
PPT 演示现场
SolidWorks 模型展示现场
大屏非接触控制演示
```

本文档不是开发规范，开发规范请参考：

```text
docs/GESTURE_MAPPING_SPEC.md
docs/STATE_MACHINE_SPEC.md
docs/ACTION_INTENT_SPEC.md
docs/CONFIG_SPEC.md
docs/TEST_ACCEPTANCE_SPEC.md
```

---

## 2. 系统要求

### 2.1 操作系统

推荐：

```text
Windows 10
Windows 11
```

不建议第一版支持：

```text
macOS
Linux
多人多电脑控制
云端远程控制
```

---

### 2.2 硬件要求

最低要求：

```text
普通 Windows 笔记本或台式机
USB 摄像头或内置摄像头
4GB 内存以上
可运行 Python 3.10+
```

推荐要求：

```text
Windows 10/11
8GB 内存以上
USB 摄像头
摄像头帧率 30 FPS
摄像头分辨率 640×480 或以上
演示时稳定光照
```

SolidWorks 演示建议：

```text
独立显卡或较强核显
能流畅运行 SolidWorks
提前打开零件或装配体
```

---

### 2.3 软件要求

```text
Python 3.10+
PowerPoint
SolidWorks
Git，可选
VS Code，可选
```

Python 依赖：

```text
mediapipe
opencv-python
pyautogui
pywin32
pynput
websockets
pytest
```

---

## 3. 项目目录结构

推荐项目目录：

```text
smartdesk_gesture_controller/
│
├── hands/
│   ├── __init__.py
│   ├── gesture_recognition.py
│   ├── gesture_state.py
│   ├── gesture_controller.py
│   ├── gesture_actions.py
│   ├── gesture_config.py
│   └── gesture_status_server.py
│
├── docs/
│   ├── GESTURE_MAPPING_SPEC.md
│   ├── STATE_MACHINE_SPEC.md
│   ├── ACTION_INTENT_SPEC.md
│   ├── CONFIG_SPEC.md
│   ├── TEST_ACCEPTANCE_SPEC.md
│   ├── PROJECT_PLAN.md
│   └── DEPLOYMENT_RUNBOOK.md
│
├── tests/
│   ├── test_gesture_actions.py
│   ├── test_gesture_controller.py
│   ├── test_gesture_recognition.py
│   └── test_gesture_state.py
│
├── hand_landmarker.task
├── gesture_recognizer.task
├── requirements.txt
├── start_gesture.bat
└── README.md
```

说明：

```text
hand_landmarker.task 是 MediaPipe 手部关键点模型。
gesture_recognizer.task 是 MediaPipe 官方手势识别模型，如果接入 GestureRecognizer，需要本地携带。
```

现场演示不应依赖自动下载模型。

---

## 4. 首次部署流程

### 4.1 创建虚拟环境

在项目根目录打开 PowerShell：

```powershell
python -m venv .venv
```

激活虚拟环境：

```powershell
.venv\Scripts\activate
```

---

### 4.2 安装依赖

```powershell
pip install -r requirements.txt
```

如果安装速度慢，可以使用镜像源，但不要把镜像源写死到项目代码中。

---

### 4.3 检查模型文件

确认项目根目录存在：

```text
hand_landmarker.task        — MediaPipe 手部关键点检测（必需）
gesture_recognizer.task     — MediaPipe 官方手势分类（use_gesture_recognizer=True 时必需）
```

如果 `use_gesture_recognizer=False`（在 `gesture_config.py` 中设置），则只需要 `hand_landmarker.task`，程序退回纯 landmarks 规则识别。

如果模型文件不存在，程序启动时会给出明确错误提示：

```text
[Error] Model file not found: hand_landmarker.task
[Error] Model file not found: gesture_recognizer.task
        Place gesture_recognizer.task in the project root,
        or set use_gesture_recognizer=False to use rule-based fallback only.
```

不要在现场演示时依赖网络下载模型。

---

### 4.4 检查摄像头

运行：

```powershell
python -m hands.gesture_controller --no-mouse
```

预期结果：

```text
摄像头窗口打开
能看到实时画面
能看到手部关键点
显示当前 FPS
显示当前手势名称
不会实际控制鼠标
```

如果摄像头打不开，尝试：

```powershell
python -m hands.gesture_controller --camera 1 --no-mouse
python -m hands.gesture_controller --camera 2 --no-mouse
```

---

## 5. 启动方式

### 5.1 Dry-run 调试模式

```powershell
python -m hands.gesture_controller --no-mouse
```

用途：

```text
识别手势
显示状态
输出 ActionIntent
不实际控制鼠标键盘
适合调试和现场标定
```

---

### 5.2 正常启动

```powershell
python -m hands.gesture_controller
```

推荐程序启动后默认处于：

```text
paused 或 standby
```

不要启动后立即控制鼠标。

---

### 5.3 PPT 演示模式启动

方式一：从 standby 通过手势进入。

```text
Thumb_Up 保持 1.5 秒
```

方式二：命令行直接进入 presentation。

```powershell
python -m hands.gesture_controller --mode presentation
```

---

### 5.4 鼠标模式启动

方式一：从 standby 通过手势进入。

```text
Pointing_Up 保持 1.0 秒
```

方式二：命令行直接进入 mouse。

```powershell
python -m hands.gesture_controller --mode mouse
```

---

### 5.5 SolidWorks 模式启动

方式一：从 standby 通过手势进入。

```text
ILoveYou 保持 1.5 秒
```

方式二：命令行直接进入 solidworks。

```powershell
python -m hands.gesture_controller --mode solidworks
```

---

### 5.6 无调试窗口启动

```powershell
python -m hands.gesture_controller --no-debug
```

用途：

```text
正式演示
减少屏幕干扰
降低 CPU 占用
```

注意：

```text
第一次调试不要使用 --no-debug
确认手势识别稳定后再关闭调试窗口
```

---

## 6. 一键启动脚本

推荐 `start_gesture.bat` 内容：

```bat
@echo off
cd /d %~dp0

if not exist .venv (
    echo [Error] .venv not found. Please create virtual environment first.
    pause
    exit /b 1
)

call .venv\Scripts\activate

echo Starting SmartDesk Gesture Controller...
python -m hands.gesture_controller

pause
```

Dry-run 版本可以新增：

```bat
@echo off
cd /d %~dp0

call .venv\Scripts\activate

echo Starting SmartDesk Gesture Controller in dry-run mode...
python -m hands.gesture_controller --no-mouse

pause
```

---

## 7. 演示前检查清单

### 7.1 通用检查

演示前必须确认：

```text
电脑电源已连接
摄像头已连接
摄像头画面清晰
光照稳定
背景不过于杂乱
模型文件存在
Python 虚拟环境可用
依赖已安装
Ctrl+Alt+G 可暂停
Ctrl+Alt+Q 可退出
```

---

### 7.2 手势识别检查

使用 dry-run 模式检查以下手势：

```text
Closed_Fist
Open_Palm
Pointing_Up
Thumb_Up
Thumb_Down
Victory
ILoveYou
PINCH
```

每个手势至少确认：

```text
调试窗口显示名称正确
不会频繁跳变
保持动作时 stable_duration 正常增加
```

---

### 7.3 安全检查

必须测试：

```text
鼠标拖拽时手离开摄像头，左键能释放
SolidWorks 平移时手离开摄像头，Shift 和中键能释放
PPT 画笔画线时手离开摄像头，左键能释放
Closed_Fist 可以退出当前模式
Ctrl+Alt+G 可以暂停
Ctrl+Alt+Q 可以退出
```

---

## 8. PPT 演示操作说明

### 8.1 准备

```text
1. 打开 PowerPoint 文件
2. 让 PowerPoint 窗口位于前台
3. 启动手势程序
4. 确认程序处于 standby
```

### 8.2 操作手势

| 功能   | 手势                     |
| ---- | ---------------------- |
| 开始演示 | `Thumb_Up` 保持 1.5 秒    |
| 下一页  | `Open_Palm` 向右挥        |
| 上一页  | `Open_Palm` 向左挥        |
| 进入画笔 | `Victory` 保持 0.5 秒     |
| 移动画笔 | `Pointing_Up` 移动       |
| 画线   | `PINCH` 并移动            |
| 擦除画笔 | `Thumb_Down` 保持 0.5 秒  |
| 取消画笔 | `Thumb_Up` 保持 0.5 秒    |
| 退出演示 | `Closed_Fist` 保持 0.8 秒 |

### 8.3 注意事项

```text
翻页动作要清晰，不要斜向挥手。
一次挥手后等待页面变化，不要连续快速挥。
画笔模式下，先确认 Pointing_Up 能移动光标，再 PINCH 画线。
退出演示时使用 Closed_Fist，不要直接关闭程序。
```

---

## 9. 鼠标模式操作说明

### 9.1 进入鼠标模式

从 standby：

```text
Pointing_Up 保持 1.0 秒
```

### 9.2 操作手势

| 功能     | 手势                     |
| ------ | ---------------------- |
| 鼠标移动   | `Pointing_Up` 移动       |
| 左键单击   | `PINCH` 短按             |
| 拖拽     | `PINCH` 长按并移动          |
| 释放拖拽   | 松开 `PINCH`             |
| 进入滚轮模式 | `Victory` 保持 0.5 秒     |
| 滚轮     | `Victory` 上下移动         |
| 右键     | `Thumb_Down` 保持 0.5 秒  |
| 退出鼠标模式 | `Closed_Fist` 保持 0.8 秒 |

### 9.3 注意事项

```text
鼠标模式比 PPT 模式更容易误操作。
调试时建议先使用 --no-mouse。
如果鼠标不受控，立即按 Ctrl+Alt+G 暂停或 Ctrl+Alt+Q 退出。
```

---

## 10. SolidWorks 模式操作说明

### 10.1 准备

```text
1. 打开 SolidWorks
2. 打开一个简单零件或装配体
3. 确认 SolidWorks 窗口处于前台
4. 启动手势程序
5. 从 standby 进入 solidworks 模式
```

### 10.2 进入 SolidWorks 模式

```text
ILoveYou 保持 1.5 秒
```

### 10.3 操作手势

| 功能     | 手势                     |
| ------ | ---------------------- |
| 旋转模型   | `Open_Palm` 移动         |
| 平移模型   | `Victory` 移动           |
| 缩放模型   | `PINCH` 距离变化           |
| 缩放全部拟合 | `Thumb_Up` 保持 0.5 秒    |
| 等轴测视图  | `ILoveYou` 保持 0.8 秒    |
| 退出模式   | `Closed_Fist` 保持 0.8 秒 |

### 10.4 注意事项

```text
Open_Palm 用于旋转，Victory 用于平移，两者不要混用。
如果模型持续旋转，立即 Closed_Fist 或 Ctrl+Alt+G。
如果平移后键盘状态异常，按 Ctrl+Alt+Q 退出程序。
退出 SolidWorks 模式时必须 release_all。
```

---

## 11. 参数标定流程

### 11.1 标定顺序

建议按以下顺序调整：

```text
1. 摄像头位置
2. 光照
3. 手势识别置信度
4. PINCH 阈值
5. 挥手阈值
6. 鼠标平滑和速度
7. 滚轮阈值
8. SolidWorks 灵敏度
9. 手丢失超时时间
```

---

### 11.2 摄像头标定

推荐位置：

```text
摄像头正对用户上半身或手部活动区域
手距离摄像头 0.5–1.5 米
手部完整进入画面
避免强背光
避免画面中出现多只无关手
```

参数：

```text
camera_index = 0       # 摄像头编号，外接 USB 可尝试 1/2
camera_width = 640     # 调试推荐 640x480
camera_height = 480
camera_fps = 30
```

---

### 11.3 PPT 翻页标定

参数：

```text
swipe_threshold_x = 0.18       # 归一化 x 位移阈值，调大=更难翻页
swipe_threshold_y_limit = 0.12 # y 方向限制，斜挥被拒绝
swipe_time_window = 0.8        # 轨迹时间窗口（秒）
page_turn_cooldown = 0.8       # 翻页后冷却（秒）
```

如果翻页不灵敏：

```text
调小 swipe_threshold_x
调小 swipe_time_window
```

如果容易误翻页：

```text
调大 swipe_threshold_x
调大 page_turn_cooldown
```

如果一次挥手翻多页：

```text
优先调大 page_turn_cooldown
确认 swipe_armed 机制未被绕过
```

---

### 11.4 PINCH 标定

参数：

```text
pinch_threshold = 0.045          # normalized 进入阈值
pinch_release_threshold = 0.065  # normalized 释放阈值（必须 > pinch_threshold）
pinch_click_distance = 35.0      # camera-px fallback 阈值
pinch_zoom_deadzone = 0.01       # SolidWorks 缩放死区
```

如果 PINCH 不容易触发：

```text
适当调大 pinch_threshold
```

如果 PINCH 误触发：

```text
适当调小 pinch_threshold
适当调大 pinch_release_threshold 与 pinch_threshold 的差距
```

约束：

```text
pinch_release_threshold 必须大于 pinch_threshold
使用滞回机制避免边界抖动
```

---

### 11.5 鼠标标定

参数：

```text
mouse_smoothing = 0.35      # 0–1，越大越平滑（延迟也越大）
mouse_speed = 1.0           # 速度倍率
mouse_max_step_px = 80      # 单帧最大移动像素，防跳
drag_hold_time = 0.35       # PINCH 长按变拖拽的时间（秒）
click_max_movement_px = 25  # 短按允许的最大移动像素
click_cooldown = 0.25       # 点击冷却（秒）
right_click_hold = 0.5      # 右键 HOLD 时间
right_click_cooldown = 0.5  # 右键冷却
```

如果鼠标抖动：

```text
优先调大 mouse_smoothing（如 0.5）
调小 mouse_speed（如 0.7）
调小 mouse_max_step_px（如 40）
```

如果鼠标跟手慢：

```text
调小 mouse_smoothing（如 0.15）
调大 mouse_speed（如 1.5）
```

如果短按容易变拖拽：

```text
调大 drag_hold_time（如 0.5）
调大 click_max_movement_px
```

---

### 11.6 滚轮标定

参数：

```text
scroll_threshold_y = 0.08   # y 方向移动阈值（归一化）
scroll_amount = 5           # 每次滚轮步长
scroll_cooldown = 0.12      # 滚轮冷却（秒）
invert_scroll = False       # 全局反转滚动方向（mouse_scroll + SolidWorks 缩放）
```

方向说明：

```text
手向上移动 = scroll(+amount) = 向上滚动 / 放大视图方向
手向下移动 = scroll(-amount) = 向下滚动
```

如果滚轮太灵敏：

```text
调大 scroll_threshold_y
调大 scroll_cooldown
调小 scroll_amount
```

如果滚动方向相反：

```text
将 invert_scroll 设为 True（集中控制方向，不要散落修改 scroll 逻辑）
```

---

### 11.7 SolidWorks 标定

参数：

```text
solidworks_drag_sensitivity = 1.2    # 旋转/平移灵敏度
solidworks_zoom_sensitivity = 8.0    # 缩放灵敏度
solidworks_min_zoom_step = 1         # 缩放最小滚轮步长（避免 amount=0 没反应）
solidworks_deadzone = 0.01           # 旋转/平移死区（归一化）
pinch_zoom_deadzone = 0.01           # PINCH 缩放死区
solidworks_view_cooldown = 0.8       # 视图快捷键冷却
fit_view_hold = 0.5                  # Thumb_Up 拟合 HOLD 时间
isometric_view_hold = 0.8            # ILoveYou 等轴测 HOLD 时间
```

如果模型旋转太慢：

```text
调大 solidworks_drag_sensitivity
```

如果模型旋转太快或发抖：

```text
调小 solidworks_drag_sensitivity
调大 solidworks_deadzone
```

如果缩放太慢或经常 amount=0 没反应：

```text
调大 solidworks_zoom_sensitivity
或调大 solidworks_min_zoom_step（如 2 或 3）
```

如果缩放太敏感：

```text
调小 solidworks_zoom_sensitivity
调大 pinch_zoom_deadzone
```

如果 SolidWorks 缩放方向相反：

```text
优先将 invert_scroll 设为 True（集中控制方向）
或者把 solidworks_zoom_sensitivity 设为负值（如 -8.0）
```

---

### 11.8 手丢失安全标定

参数：

```text
hand_lost_timeout = 1.0   # 手丢失超时时间（秒）
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

## 12. Dry-Run 标定模式

### 12.1 启动 dry-run

```powershell
python -m hands.gesture_controller --no-mouse
```

或使用启动脚本：

```bat
start_gesture_dry_run.bat
```

### 12.2 Dry-run 显示信息

dry-run 模式下调试窗口显示以下信息，用于现场标定：

```text
FPS              — 当前帧率
[MODE]           — 当前模式（standby/presentation/mouse/solidworks 等）
gesture          — 当前识别到的手势名称
note             — 状态提示文本
src              — 手势识别来源（gesture_recognizer / rule_fallback / none）
conf             — GestureRecognizer 置信度
raw              — 原始手势名（归一化前）
stable           — 当前手势稳定持续时间（秒）
action           — 当前连续动作（如 solidworks_rotate）
L-down/M-down    — 鼠标左键/中键按下状态
Shift-down       — Shift 键按下状态
Pinch            — PINCH 状态
pinch            — pinch_distance 值
swipe dx/dy      — 手掌中心位移
lost             — 手丢失持续时间
cooldown         — 冷却剩余时间
DRY-RUN          — 提示不控制真实鼠标
```

通过 `src` 字段可以判断当前手势是来自 GestureRecognizer（更稳定）还是旧规则兜底。如果 `src` 长期显示 `rule_fallback`，说明 GestureRecognizer 置信度偏低，可能需要调整 `min_gesture_confidence` 或检查光照条件。

### 12.3 Dry-run 安全保证

```text
1. dry-run 不能真实移动鼠标
2. dry-run 不能真实按键
3. dry-run 仍输出 ActionIntent 日志
4. dry-run 可用于调试 PPT、mouse、SolidWorks 三种模式
5. FakeDriver 记录所有动作但不执行
```

### 12.4 使用 dry-run 标定流程

```text
1. 启动 dry-run 模式
2. 确认摄像头画面清晰
3. 逐一测试手势，确认识别稳定
4. 观察 stable_duration 是否正常增长
5. 观察模式切换是否正确
6. 观察 ActionIntent 输出是否符合预期
7. 调整参数后重新测试
8. 确认稳定后切换到正式模式
```

---

## 13. 常见问题处理

### 12.1 摄像头打不开

现象：

```text
程序启动后黑屏或报错
```

处理：

```text
1. 检查摄像头是否被其他软件占用
2. 关闭微信、腾讯会议、OBS 等占用摄像头的软件
3. 尝试 --camera 1 或 --camera 2
4. 重新插拔 USB 摄像头
5. 检查 Windows 隐私设置是否允许摄像头访问
```

---

### 12.2 手势识别不稳定

处理：

```text
1. 调整光照
2. 保证手部完整进入画面
3. 避免背景中有其他手或复杂纹理
4. 降低 min_gesture_confidence 做调试
5. 确认 landmarks 是否稳定
```

---

### 12.3 PPT 无法翻页

处理：

```text
1. 确认 PowerPoint 位于前台
2. 确认已经进入 presentation 模式
3. 确认 Open_Palm 左右挥手被识别
4. 检查 page_turn_cooldown 是否过大
5. 尝试使用 PageDown/PageUp 替代 Right/Left
```

---

### 12.4 PPT 无法退出放映

处理：

```text
1. 使用 Closed_Fist 保持 0.8 秒
2. 检查是否输出 press("esc")
3. 手动按 Esc 确认 PowerPoint 正常响应
4. 检查动作层是否执行了 pyautogui.press("esc")
```

---

### 12.5 鼠标卡住

处理：

```text
1. 立即按 Ctrl+Alt+G 暂停
2. 如果仍未释放，按 Ctrl+Alt+Q 退出
3. 手动点击鼠标左键/中键释放
4. 检查 release_all 是否包含 left/middle/right
5. 检查手丢失是否触发 release_all
```

---

### 12.6 SolidWorks 模型一直旋转

处理：

```text
1. 做 Closed_Fist 退出模式
2. 按 Ctrl+Alt+G 暂停
3. 按 Ctrl+Alt+Q 退出
4. 检查 mouse_up("middle") 是否执行
5. 检查 Open_Palm 结束条件是否正确
```

---

### 12.7 SolidWorks 平移后键盘异常

可能原因：

```text
Shift 没有释放
```

处理：

```text
1. 按 Ctrl+Alt+Q 退出程序
2. 手动按一下 Shift
3. 检查 release_all 是否包含 key_up("shift")
4. 检查 Victory 结束时是否执行 key_up("shift")
```

---

## 14. 日志检查

建议日志至少包含：

```text
当前时间
当前模式
当前手势
稳定时间
动作意图
是否 dry-run
FPS
错误信息
```

示例：

```text
[12:01:05] mode=standby gesture=Thumb_Up stable=1.50 action=press:f5
[12:01:07] mode=presentation gesture=Open_Palm action=press:right
[12:01:15] mode=solidworks action=mouse_down:middle reason=rotate_begin
[12:01:20] mode=solidworks action=release_all reason=fist_exit
```

---

## 15. 现场演示建议流程

推荐演示顺序：

```text
1. 先展示 dry-run 模式，说明系统能识别手势但不控制电脑
2. 展示 PPT：开始、翻页、画笔、擦除、退出
3. 展示鼠标：移动、点击、拖拽、滚轮
4. 展示 SolidWorks：旋转、平移、缩放、适配视图
5. 展示安全机制：Closed_Fist、Ctrl+Alt+G、Ctrl+Alt+Q
```

不要一开始就演示 SolidWorks，因为它对鼠标中键和 Shift 依赖更强，风险更高。

---

## 16. 打包建议

第一版可以先不打包，使用 Python 脚本运行。

后续如果要打包 exe，可以使用：

```text
PyInstaller
```

打包要求：

```text
模型文件必须随包携带
配置文件必须可外部修改
日志文件必须可查看
Ctrl+Alt+G / Ctrl+Alt+Q 必须可用
release_all 必须在退出前执行
```

暂不建议第一轮就打包，因为调试和修改会更麻烦。

---

## 17. 演示前最终确认表

演示前逐项确认：

```text
[ ] 摄像头可用
[ ] 模型文件存在
[ ] Python 环境可用
[ ] 依赖已安装
[ ] dry-run 模式可启动
[ ] Closed_Fist 可识别
[ ] Thumb_Up 可识别
[ ] Open_Palm 可识别
[ ] Victory 可识别
[ ] PINCH 可识别
[ ] Ctrl+Alt+G 可暂停
[ ] Ctrl+Alt+Q 可退出
[ ] PPT 已打开
[ ] SolidWorks 已打开
[ ] release_all 测试通过
[ ] 鼠标没有卡住风险
```

---

## 18. 结论

部署和演示时，优先级顺序必须是：

```text
安全退出 > 手势稳定 > PPT 演示 > 鼠标控制 > SolidWorks 控制 > 打包美化
```

只要出现鼠标键、键盘键卡住或无法退出的问题，应立即停止演示并修复安全机制。
