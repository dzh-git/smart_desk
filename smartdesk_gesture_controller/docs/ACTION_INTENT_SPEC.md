# ACTION_INTENT_SPEC.md

# SmartDesk Gesture Controller 动作意图接口规范

## 1. 文档目的

本文档用于定义 SmartDesk Gesture Controller 中状态机与动作层之间的接口。

状态机 `gesture_state.py` 不直接调用 PyAutoGUI，而是输出声明式动作意图 `ActionIntent`。

动作层 `gesture_actions.py` 只负责接收 `ActionIntent` 并执行实际鼠标、键盘操作。

本文档重点解决以下问题：

1. 状态机可以输出哪些动作。
2. 每种动作需要哪些字段。
3. 动作层如何执行这些动作。
4. Dry-run 模式如何测试动作。
5. `release_all` 应该释放哪些按键和鼠标键。

---

## 2. 基本原则

### 2.1 状态机不直接执行系统操作

禁止在 `gesture_state.py` 中直接调用：

```python
pyautogui.press(...)
pyautogui.hotkey(...)
pyautogui.mouseDown(...)
pyautogui.mouseUp(...)
pyautogui.moveTo(...)
pyautogui.scroll(...)
```

状态机只能输出：

```python
ActionIntent(...)
```

实际执行由 `gesture_actions.py` 完成。

---

### 2.2 ActionIntent 必须是声明式的

`ActionIntent` 描述“要做什么”，而不是描述“怎么做”。

例如：

```python
ActionIntent(type="press", key="f5")
ActionIntent(type="hotkey", keys=["ctrl", "p"])
ActionIntent(type="mouse_down", button="middle")
ActionIntent(type="release_all")
```

不要在 `ActionIntent` 中写具体 PyAutoGUI 代码。

---

### 2.3 ActionIntent 必须可测试

所有动作都必须可以在 `FakeDriver` 中测试。

Dry-run 模式下：

```text
状态机照常输出 ActionIntent
动作层不实际控制鼠标和键盘
FakeDriver 记录动作日志
单元测试检查动作日志是否符合预期
```

---

### 2.4 安全动作优先

以下动作不受 cooldown 限制：

```text
release_all
mouse_up
key_up
pause
quit
```

即使系统处于冷却时间内，也必须允许安全释放。

---

## 3. ActionIntent 数据结构

建议定义：

```python
from dataclasses import dataclass, field
from typing import Any

@dataclass
class ActionIntent:
    type: str
    key: str | None = None
    keys: list[str] = field(default_factory=list)
    button: str | None = None
    x: float | None = None
    y: float | None = None
    dx: float | None = None
    dy: float | None = None
    amount: int | None = None
    text: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)
```

字段说明：

| 字段       | 类型          | 用途                               |
| -------- | ----------- | -------------------------------- |
| `type`   | `str`       | 动作类型，必填                          |
| `key`    | `str`       | 单个键盘按键                           |
| `keys`   | `list[str]` | 组合快捷键                            |
| `button` | `str`       | 鼠标按键，`left` / `middle` / `right` |
| `x`      | `float`     | 绝对鼠标 x 坐标                        |
| `y`      | `float`     | 绝对鼠标 y 坐标                        |
| `dx`     | `float`     | 相对鼠标 x 位移                        |
| `dy`     | `float`     | 相对鼠标 y 位移                        |
| `amount` | `int`       | 滚轮滚动量                            |
| `text`   | `str`       | 状态提示或调试文本                        |
| `meta`   | `dict`      | 调试信息或扩展信息                        |

---

## 4. 支持的 ActionIntent 类型

第一版支持以下动作类型：

```text
press
hotkey
mouse_down
mouse_up
click
move_to
move_rel
scroll
key_down
key_up
release_all
status
noop
```

---

## 5. 键盘动作

### 5.1 press

用于按下并释放单个按键。

示例：

```python
ActionIntent(type="press", key="f5")
ActionIntent(type="press", key="esc")
ActionIntent(type="press", key="right")
ActionIntent(type="press", key="left")
ActionIntent(type="press", key="e")
ActionIntent(type="press", key="b")
ActionIntent(type="press", key="f")
```

动作层执行：

```python
pyautogui.press(intent.key)
```

约束：

```text
key 必须非空
press 不用于组合快捷键
press 不用于持续按住的按键
```

---

### 5.2 hotkey

用于组合快捷键。

示例：

```python
ActionIntent(type="hotkey", keys=["ctrl", "p"])
ActionIntent(type="hotkey", keys=["ctrl", "a"])
ActionIntent(type="hotkey", keys=["ctrl", "7"])
```

动作层执行：

```python
pyautogui.hotkey(*intent.keys)
```

约束：

```text
keys 必须是非空列表
keys 中按键顺序应与实际按下顺序一致
```

---

### 5.3 key_down

用于按住某个键。

示例：

```python
ActionIntent(type="key_down", key="shift")
```

动作层执行：

```python
pyautogui.keyDown(intent.key)
```

适用场景：

```text
SolidWorks 平移：Shift + 中键拖动
```

约束：

```text
key_down 必须有对应 key_up
切换模式、手丢失、退出程序时必须 release_all
```

---

### 5.4 key_up

用于释放某个键。

示例：

```python
ActionIntent(type="key_up", key="shift")
```

动作层执行：

```python
pyautogui.keyUp(intent.key)
```

约束：

```text
key_up 必须允许重复调用
即使该键当前没有按下，也不能导致程序崩溃
```

---

## 6. 鼠标动作

### 6.1 move_to

用于绝对移动鼠标。

示例：

```python
ActionIntent(type="move_to", x=960, y=540)
```

动作层执行：

```python
pyautogui.moveTo(intent.x, intent.y)
```

适用场景：

```text
鼠标模式
PPT 画笔模式
```

约束：

```text
x 和 y 必须非空
动作层应限制 x/y 不超过屏幕边界
```

---

### 6.2 move_rel

用于相对移动鼠标。

示例：

```python
ActionIntent(type="move_rel", dx=20, dy=-10)
```

动作层执行：

```python
pyautogui.moveRel(intent.dx, intent.dy)
```

适用场景：

```text
SolidWorks 旋转
SolidWorks 平移
鼠标拖拽
画笔拖动
```

约束：

```text
dx/dy 必须经过灵敏度和最大速度限制
单帧移动量不应过大
```

---

### 6.3 mouse_down

用于按住鼠标键。

示例：

```python
ActionIntent(type="mouse_down", button="left")
ActionIntent(type="mouse_down", button="middle")
```

动作层执行：

```python
pyautogui.mouseDown(button=intent.button)
```

适用场景：

```text
PPT 画笔画线
鼠标拖拽
SolidWorks 中键旋转
SolidWorks Shift + 中键平移
```

约束：

```text
mouse_down 必须有对应 mouse_up
禁止每帧重复 mouse_down
```

---

### 6.4 mouse_up

用于释放鼠标键。

示例：

```python
ActionIntent(type="mouse_up", button="left")
ActionIntent(type="mouse_up", button="middle")
```

动作层执行：

```python
pyautogui.mouseUp(button=intent.button)
```

约束：

```text
mouse_up 必须允许重复调用
即使当前鼠标键没有按下，也不能报错
```

---

### 6.5 click

用于鼠标单击。

示例：

```python
ActionIntent(type="click", button="left")
ActionIntent(type="click", button="right")
```

动作层执行：

```python
pyautogui.click(button=intent.button)
```

约束：

```text
click 只能用于离散点击
click 不用于拖拽和连续绘制
```

---

### 6.6 scroll

用于滚轮滚动。

示例：

```python
ActionIntent(type="scroll", amount=5)
ActionIntent(type="scroll", amount=-5)
```

动作层执行：

```python
pyautogui.scroll(intent.amount)
```

适用场景：

```text
鼠标滚轮模式
SolidWorks 缩放模型
```

约束：

```text
amount 必须限制最大值
禁止单帧滚动过大
scroll 必须有冷却或死区
```

---

## 7. 安全动作

### 7.1 release_all

用于释放所有可能被按住的鼠标键和键盘键。

示例：

```python
ActionIntent(type="release_all")
```

动作层必须执行：

```python
pyautogui.mouseUp(button="left")
pyautogui.mouseUp(button="middle")
pyautogui.mouseUp(button="right")

pyautogui.keyUp("shift")
pyautogui.keyUp("ctrl")
pyautogui.keyUp("alt")
```

后续如果增加更多持续按键，也必须加入 `release_all`。

### 7.2 release_all 的触发场景

以下场景必须触发：

```text
Closed_Fist 退出当前模式
手丢失超时
模式切换
暂停程序
退出程序
摄像头读取失败
MediaPipe 推理异常
动作层异常
程序 KeyboardInterrupt
```

### 7.3 release_all 的幂等性

`release_all` 必须是幂等的。

也就是说：

```text
重复调用 release_all 不应报错
没有任何按键按下时调用 release_all 不应报错
```

---

## 8. 状态提示动作

### 8.1 status

用于向调试窗口或 WebSocket 状态服务器输出当前状态。

示例：

```python
ActionIntent(type="status", text="Presentation: Open Palm Swipe = Page, Fist = Exit")
```

动作层可以：

```text
更新调试窗口显示
写入日志
广播 WebSocket 状态
```

状态提示不应控制鼠标或键盘。

---

### 8.2 noop

用于明确表示“不执行动作”。

示例：

```python
ActionIntent(type="noop")
```

适用场景：

```text
standby 中识别到 Open_Palm
paused 中识别到任意手势
cooldown 内忽略重复动作
```

---

## 9. ActionIntent 执行顺序

当状态机一次输出多个动作时，动作层必须按顺序执行。

例如退出 PPT 画笔模式：

```python
[
    ActionIntent(type="mouse_up", button="left"),
    ActionIntent(type="hotkey", keys=["ctrl", "a"]),
]
```

退出 PPT 演示：

```python
[
    ActionIntent(type="mouse_up", button="left"),
    ActionIntent(type="press", key="esc"),
    ActionIntent(type="release_all"),
]
```

SolidWorks 平移开始：

```python
[
    ActionIntent(type="key_down", key="shift"),
    ActionIntent(type="mouse_down", button="middle"),
]
```

SolidWorks 平移结束：

```python
[
    ActionIntent(type="mouse_up", button="middle"),
    ActionIntent(type="key_up", key="shift"),
]
```

---

## 10. 动作冲突处理

### 10.1 鼠标中键冲突

如果当前已经按下中键，再次收到 `mouse_down("middle")`：

```text
动作层可以忽略重复 mouse_down
状态机应避免重复输出
```

### 10.2 Shift 键冲突

如果当前处于 SolidWorks 平移状态，必须确保：

```text
key_down("shift") 只执行一次
平移结束时 key_up("shift")
任何异常退出时 release_all
```

### 10.3 左键拖拽冲突

如果当前左键已按下，不能再触发普通 `click("left")`。

应先：

```text
mouse_up("left")
再根据状态决定是否 click
```

---

## 11. FakeDriver 规范

测试时使用 `FakeDriver` 代替 PyAutoGUI。

### 11.1 FakeDriver 需要记录的动作

```python
fake_driver.events = [
    ("press", "f5"),
    ("hotkey", ["ctrl", "p"]),
    ("mouse_down", "left"),
    ("mouse_up", "left"),
    ("move_rel", 10, -5),
    ("scroll", 5),
    ("release_all",),
]
```

### 11.2 FakeDriver 不应实际控制鼠标

FakeDriver 只能记录动作，不执行系统操作。

### 11.3 单元测试示例

```python
def test_exit_presentation_releases_all():
    actions.execute([
        ActionIntent(type="press", key="esc"),
        ActionIntent(type="release_all"),
    ])

    assert ("press", "esc") in fake_driver.events
    assert ("release_all",) in fake_driver.events
```

---

## 12. Dry-run 模式规范

启动参数：

```bash
python -m hands.gesture_controller --no-mouse
```

Dry-run 模式下：

```text
摄像头正常读取
MediaPipe 正常识别
状态机正常输出 ActionIntent
动作层不调用真实 PyAutoGUI
调试窗口显示将要执行的动作
日志记录动作序列
```

Dry-run 模式用于：

```text
调试手势映射
测试状态机
现场演示前校准
避免误操作电脑
```

---

## 13. 日志规范

动作层建议输出结构化日志。

示例：

```text
[Action] press key=f5 mode=standby reason=start_presentation
[Action] hotkey keys=ctrl+p mode=presentation reason=enter_pen
[Action] mouse_down button=middle mode=solidworks reason=rotate_begin
[Action] release_all mode=solidworks reason=fist_exit
```

日志至少包含：

```text
动作类型
动作参数
当前模式
触发原因
时间戳
是否 dry-run
```

---

## 14. 第一版必须支持的动作

第一版必须实现：

```text
press
hotkey
mouse_down
mouse_up
click
move_to
move_rel
scroll
key_down
key_up
release_all
status
noop
```

暂缓实现：

```text
double_click
drag_to
typewrite
screenshot
window_activate
```

---

## 15. 结论

`ActionIntent` 是状态机和动作层之间的边界。

后续开发必须遵守：

```text
状态机只判断意图
动作层只执行意图
测试层可以替换动作层
release_all 永远优先
```

这样才能保证项目可测试、可扩展，并且避免手势控制程序抢占鼠标后无法释放。
