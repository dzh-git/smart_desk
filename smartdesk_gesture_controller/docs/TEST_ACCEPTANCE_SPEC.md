# TEST_ACCEPTANCE_SPEC.md

# SmartDesk Gesture Controller 测试与验收规范

## 1. 文档目的

本文档用于定义 SmartDesk Gesture Controller 的测试范围、验收标准和完成判定。

后续每一轮代码修改完成后，都必须按照本文档进行自测或自动化测试。

本文档重点解决以下问题：

1. 每个功能怎么测试。
2. 什么结果算通过。
3. 哪些问题必须阻塞合并。
4. 如何验证安全释放。
5. 如何验证 PPT、鼠标和 SolidWorks 的端到端效果。

---

## 2. 测试分层

项目测试分为五层：

```text
单元测试
状态机测试
动作层测试
Dry-run 端到端测试
真实软件端到端测试
```

对应关系：

| 测试层级          | 目标                         | 是否真实控制鼠标键盘    |
| ------------- | -------------------------- | ------------- |
| 单元测试          | 验证函数逻辑                     | 否             |
| 状态机测试         | 验证手势到 ActionIntent         | 否             |
| 动作层测试         | 验证 ActionIntent 到动作调用      | 使用 FakeDriver |
| Dry-run 端到端测试 | 摄像头识别 + 状态机 + 动作日志         | 否             |
| 真实端到端测试       | 实际控制 PPT / SolidWorks / 鼠标 | 是             |

---

## 3. 测试环境要求

### 3.1 开发测试环境

```text
Windows 10 / Windows 11
Python 3.10+
摄像头可用
PowerPoint 可用
SolidWorks 可用或至少有可替代窗口用于鼠标中键测试
```

### 3.2 依赖要求

```text
mediapipe
opencv-python
pyautogui
pywin32
pynput
websockets
pytest
```

### 3.3 安全要求

真实端到端测试前必须确认：

```text
Ctrl+Alt+G 暂停/恢复可用
Ctrl+Alt+Q 紧急退出可用
手离开摄像头后可以 release_all
Dry-run 模式已先通过
```

---

## 4. 必须通过的自动化测试

### 4.1 gesture_recognition 测试

目标：

```text
验证基础手势识别和自定义手势判断逻辑。
```

测试项：

```text
FIST / Closed_Fist 可以识别
OPEN_PALM / Open_Palm 可以识别
SINGLE_FINGER / Pointing_Up 可以识别
TWO_FINGER / Victory 可以识别
PINCH 距离小于阈值时触发
PINCH 距离大于释放阈值时释放
None 或低置信度手势不会触发动作
```

验收标准：

```text
所有单元测试通过
PINCH 使用滞回机制
低置信度手势被过滤
```

---

### 4.2 gesture_state 测试

目标：

```text
验证状态机是否按照 STATE_MACHINE_SPEC.md 输出正确 ActionIntent。
```

测试项：

```text
standby 中 Thumb_Up HOLD 触发 F5 并进入 presentation
standby 中 Open_Palm 不触发动作
presentation 中 Open_Palm 右挥触发 right
presentation 中 Open_Palm 左挥触发 left
presentation 中 Victory HOLD 触发 Ctrl+P 并进入 presentation_pen
presentation 中 Closed_Fist 触发 Esc + release_all + standby
presentation_pen 中 PINCH 触发 mouse_down(left)
presentation_pen 中 PINCH 释放触发 mouse_up(left)
mouse 中 Pointing_Up 触发 move
mouse 中 PINCH 短按触发 click(left)
mouse 中 PINCH 长按触发 mouse_down(left)
solidworks 中 Open_Palm 触发 middle mouse drag
solidworks 中 Victory 触发 Shift + middle mouse drag
solidworks 中 Closed_Fist 触发 release_all + standby
paused 中任意手势不触发动作
```

验收标准：

```text
状态切换正确
ActionIntent 顺序正确
所有退出路径包含 release_all
cooldown 内不会重复触发离散动作
```

---

### 4.3 gesture_actions 测试

目标：

```text
验证 ActionLayer 正确执行 ActionIntent。
```

测试项：

```text
press("f5") 被正确记录
hotkey(["ctrl", "p"]) 被正确记录
mouse_down("left") 被正确记录
mouse_up("left") 被正确记录
mouse_down("middle") 被正确记录
key_down("shift") 被正确记录
scroll(amount) 被正确记录
release_all 会释放 left / middle / right / shift / ctrl / alt
Dry-run 不实际控制鼠标键盘
```

验收标准：

```text
FakeDriver 动作日志符合预期
release_all 可重复调用
无动作参数缺失导致异常
```

---

### 4.4 gesture_controller 测试

目标：

```text
验证主循环在异常和退出时能安全释放。
```

测试项：

```text
摄像头读取失败时触发 release_all
KeyboardInterrupt 时触发 release_all
动作层异常时触发 release_all
Ctrl+Alt+G 暂停时触发 release_all
Ctrl+Alt+Q 退出时触发 release_all
--no-mouse 模式不执行真实动作
--no-debug 模式不显示调试窗口
```

验收标准：

```text
异常不会导致鼠标键卡住
退出时资源释放
摄像头关闭
OpenCV 窗口关闭
```

---

## 5. PPT 演示模式验收

### 5.1 前置条件

```text
PowerPoint 已打开
存在至少 5 页测试幻灯片
摄像头可以完整看到手部
程序处于 standby
```

### 5.2 测试清单

| 编号     | 操作                     | 预期结果           | 通过标准                  |
| ------ | ---------------------- | -------------- | --------------------- |
| PPT-01 | `Thumb_Up` 保持 1.5 秒    | 发送 F5，进入放映     | 成功进入放映                |
| PPT-02 | `Open_Palm` 向右挥 10 次   | 下一页            | 至少成功 9 次，误触不超过 1 次    |
| PPT-03 | `Open_Palm` 向左挥 10 次   | 上一页            | 至少成功 9 次，误触不超过 1 次    |
| PPT-04 | 快速连续挥手                 | 不连续翻多页         | 一次挥手最多翻 1 页           |
| PPT-05 | `Victory` 保持 0.5 秒     | 进入画笔模式         | 光标进入画笔                |
| PPT-06 | `Pointing_Up` 移动       | 画笔/指针移动        | 移动方向正确                |
| PPT-07 | `PINCH` 并移动            | 画线             | 可以画出线条                |
| PPT-08 | 释放 `PINCH`             | 停止画线           | 左键释放                  |
| PPT-09 | `Thumb_Down` 保持 0.5 秒  | 擦除画笔痕迹         | 当前页痕迹被擦除              |
| PPT-10 | `Thumb_Up` 保持 0.5 秒    | 退出画笔           | 光标恢复箭头                |
| PPT-11 | `Closed_Fist` 保持 0.8 秒 | 退出放映，回 standby | PPT 退出放映，状态机回 standby |

### 5.3 阻塞问题

以下问题必须修复后才能通过：

```text
握拳退出后 PPT 仍停留在放映模式
画笔模式退出后左键仍按住
一次挥手连续翻多页
standby 中 Open_Palm 误触 F5
```

---

## 6. 鼠标模式验收

### 6.1 前置条件

```text
打开一个普通窗口，例如浏览器或文件资源管理器
程序处于 standby
```

### 6.2 测试清单

| 编号       | 操作                     | 预期结果            | 通过标准           |
| -------- | ---------------------- | --------------- | -------------- |
| MOUSE-01 | `Pointing_Up` 保持 1 秒   | 进入 mouse 模式     | 状态显示 mouse     |
| MOUSE-02 | `Pointing_Up` 移动       | 鼠标移动            | 鼠标跟随且不明显抖动     |
| MOUSE-03 | `PINCH` 短按             | 左键单击            | 可以选中文件或按钮      |
| MOUSE-04 | `PINCH` 长按并移动          | 拖拽              | 可以拖动窗口或文件      |
| MOUSE-05 | 释放 `PINCH`             | 停止拖拽            | 左键释放           |
| MOUSE-06 | `Victory` 保持 0.5 秒     | 进入 mouse_scroll | 状态显示 scroll    |
| MOUSE-07 | `Victory` 上下移动         | 页面滚动            | 方向正确           |
| MOUSE-08 | `Thumb_Down` 保持 0.5 秒  | 右键单击            | 弹出右键菜单         |
| MOUSE-09 | `Closed_Fist` 保持 0.8 秒 | 退出 mouse        | 回 standby，释放左键 |
| MOUSE-10 | 拖拽中 `Thumb_Down`       | 不触发右键           | 拖拽中右键被阻止       |
| MOUSE-11 | `mouse_scroll` 中 `PINCH` | 不触发点击           | PINCH 在滚轮模式无效  |
| MOUSE-12 | `mouse_scroll` 中 `Thumb_Down` | 不触发右键      | Thumb_Down 在滚轮模式无效 |
| MOUSE-13 | `mouse` 中上下移动          | 不触发滚轮           | 普通 mouse 不误触滚轮 |
| MOUSE-14 | `mouse_scroll` 手丢失超时    | 回 mouse         | release_all 后回 mouse |
| MOUSE-15 | `mouse` 手丢失超时          | 保持 mouse        | release_all 但保持 mouse |

### 6.3 阻塞问题

```text
鼠标突然跳到屏幕边缘
PINCH 后左键无法释放
滚轮在普通 mouse 模式中误触
退出 mouse 后仍然控制鼠标
拖拽中右键误触
mouse_scroll 中 PINCH 误触发点击
mouse_scroll 中 Thumb_Down 误触发右键
```

---

## 7. SolidWorks 模式验收

### 7.1 前置条件

```text
SolidWorks 已打开
已加载一个简单零件或装配体
程序处于 standby
```

### 7.2 测试清单

| 编号    | 操作                     | 预期结果             | 通过标准                  |
| ----- | ---------------------- | ---------------- | --------------------- |
| SW-01 | `ILoveYou` 保持 1.5 秒    | 进入 solidworks 模式 | 状态显示 solidworks       |
| SW-02 | `Open_Palm` 移动         | 模型旋转             | 旋转方向基本符合手势移动          |
| SW-03 | 停止 `Open_Palm` 或手离开    | 中键释放             | 不再旋转                  |
| SW-04 | `Victory` 移动           | 模型平移             | 模型平移，不旋转              |
| SW-05 | 停止 `Victory` 或手离开      | Shift 和中键释放      | 不再平移                  |
| SW-06 | `PINCH` 距离增大           | 模型放大             | 缩放方向正确                |
| SW-07 | `PINCH` 距离减小           | 模型缩小             | 缩放方向正确                |
| SW-08 | `Thumb_Up` 保持 0.5 秒    | 缩放全部拟合           | 模型适配视图                |
| SW-09 | `ILoveYou` 保持 0.8 秒    | 等轴测视图            | 视图切换                  |
| SW-10 | `Closed_Fist` 保持 0.8 秒 | 退出 solidworks    | 回 standby，release_all |
| SW-11 | 旋转中切到 `Victory`         | 先释放中键，再 Shift+中键 | 旋转→平移切换平滑             |
| SW-12 | 平移中切到 `Open_Palm`       | 先释放中键+Shift，再中键 | 平移→旋转切换平滑             |
| SW-13 | 旋转/平移中进入 `PINCH`        | 先释放连续动作，再缩放     | 中键和 Shift 不卡住         |
| SW-14 | 手丢失超过 1 秒              | 释放中键+Shift       | release_all，保持 solidworks |
| SW-15 | 退出后 `active_continuous_action` | 被清空        | 无残留状态                 |

### 7.3 阻塞问题

```text
中键卡住
Shift 键卡住
旋转和平移同时触发
手丢失后模型仍在旋转或平移
Closed_Fist 后没有 release_all
旋转/平移/缩放未互斥
PINCH 缩放时中键或 Shift 卡住
退出 solidworks 后仍控制鼠标
```

---

## 8. 安全机制验收

### 8.1 测试清单

| 编号      | 操作                   | 预期结果                |
| ------- | -------------------- | ------------------- |
| SAFE-01 | 程序启动                 | 默认暂停或 standby，不控制鼠标 |
| SAFE-02 | `Ctrl+Alt+G`         | 暂停/恢复               |
| SAFE-03 | 暂停时做任意手势             | 不执行鼠标键盘动作           |
| SAFE-04 | `Ctrl+Alt+Q`         | 程序退出，并 release_all  |
| SAFE-05 | 鼠标拖拽时手离开摄像头          | 1 秒内释放左键            |
| SAFE-06 | SolidWorks 平移时手离开摄像头 | 1 秒内释放 Shift 和中键    |
| SAFE-07 | PPT 画线时手离开摄像头        | 1 秒内释放左键            |
| SAFE-08 | 程序异常退出模拟             | 执行 release_all      |

### 8.2 通过标准

```text
所有安全测试必须 100% 通过。
```

安全测试不允许用“偶尔失败”通过。

---

## 9. 性能验收

### 9.1 指标

| 指标         | 目标                  |
| ---------- | ------------------- |
| 平均 FPS     | ≥ 20                |
| 端到端主观延迟    | 无明显拖滞               |
| 端到端 P95 延迟 | ≤ 150 ms            |
| CPU 占用     | 普通演示电脑上可接受，建议 < 40% |
| 连续运行       | ≥ 60 分钟无崩溃          |
| 手势误触发率     | < 5%                |

### 9.2 记录要求

测试日志至少记录：

```text
测试时间
电脑型号
摄像头型号
分辨率
平均 FPS
最低 FPS
动作触发次数
误触发次数
异常日志
```

---

## 10. Dry-run 端到端验收

### 10.1 启动方式

```bash
python -m hands.gesture_controller --no-mouse
```

或使用启动脚本：

```bat
start_gesture_dry_run.bat
```

### 10.2 验收内容

```text
摄像头画面正常
手部 landmarks 正常显示
当前手势名称正常显示
当前 mode 正常显示
ActionIntent 日志正常显示
不会实际移动鼠标
不会实际按键盘
stable_duration 正常显示
active_continuous_action 正常显示
FPS 正常显示
```

### 10.3 通过标准

```text
所有计划手势都能在 debug 窗口看到正确识别
所有计划动作都能输出正确 ActionIntent
没有真实鼠标键盘动作发生
dry-run 可用于调试 PPT、mouse、SolidWorks 三种模式
```

---

## 10a. 真实端到端测试清单

以下测试需要在真实环境中执行（非 dry-run），确认系统能实际控制目标程序。

### 10a.1 PPT 端到端测试

| 编号       | 操作                     | 预期结果            |
| -------- | ---------------------- | --------------- |
| E2E-P-01 | standby 中 Thumb_Up 保持 1.5 秒 | PPT 进入放映，press("f5") |
| E2E-P-02 | Open_Palm 向右挥          | 下一页             |
| E2E-P-03 | Open_Palm 向左挥          | 上一页             |
| E2E-P-04 | Victory 保持 0.5 秒       | 进入画笔模式 Ctrl+P   |
| E2E-P-05 | Pointing_Up 移动         | 画笔/指针移动         |
| E2E-P-06 | PINCH 并移动              | 画线              |
| E2E-P-07 | Thumb_Down 保持 0.5 秒    | 擦除画笔痕迹 E       |
| E2E-P-08 | Thumb_Up 保持 0.5 秒      | 退出画笔 Ctrl+A    |
| E2E-P-09 | Closed_Fist 保持 0.8 秒   | 退出演示 Esc + release_all |

### 10a.2 Mouse 端到端测试

| 编号       | 操作                     | 预期结果            |
| -------- | ---------------------- | --------------- |
| E2E-M-01 | standby 中 Pointing_Up 保持 1.0 秒 | 进入 mouse 模式    |
| E2E-M-02 | Pointing_Up 移动         | 鼠标移动            |
| E2E-M-03 | PINCH 短按               | 左键单击            |
| E2E-M-04 | PINCH 长按并移动            | 拖拽              |
| E2E-M-05 | 松开 PINCH               | 释放左键            |
| E2E-M-06 | Victory 保持 0.5 秒       | 进入 mouse_scroll |
| E2E-M-07 | Victory 向上移动           | 向上滚动            |
| E2E-M-08 | Victory 向下移动           | 向下滚动            |
| E2E-M-09 | Thumb_Down 保持 0.5 秒    | 右键单击            |
| E2E-M-10 | Closed_Fist 保持 0.8 秒   | 退出 mouse + release_all |

### 10a.3 SolidWorks 端到端测试

| 编号       | 操作                     | 预期结果            |
| -------- | ---------------------- | --------------- |
| E2E-S-01 | standby 中 ILoveYou 保持 1.5 秒 | 进入 solidworks 模式 |
| E2E-S-02 | Open_Palm 移动           | 模型旋转（中键拖动）      |
| E2E-S-03 | 停止 Open_Palm           | 中键释放，停止旋转       |
| E2E-S-04 | Victory 移动             | 模型平移（Shift+中键）  |
| E2E-S-05 | 停止 Victory             | 中键+Shift 释放     |
| E2E-S-06 | PINCH 距离增大             | 模型放大            |
| E2E-S-07 | PINCH 距离减小             | 模型缩小            |
| E2E-S-08 | Thumb_Up 保持 0.5 秒      | 缩放全部拟合 F        |
| E2E-S-09 | ILoveYou 保持 0.8 秒      | 等轴测视图 Ctrl+7   |
| E2E-S-10 | Closed_Fist 保持 0.8 秒   | 退出 solidworks + release_all |

### 10a.4 安全端到端测试

| 编号       | 操作                   | 预期结果                    |
| -------- | -------------------- | ----------------------- |
| E2E-X-01 | 任意模式中 Ctrl+Alt+G     | 暂停，release_all          |
| E2E-X-02 | 暂停中 Ctrl+Alt+G       | 恢复到 standby             |
| E2E-X-03 | 任意模式中 Ctrl+Alt+Q     | 程序退出，release_all        |
| E2E-X-04 | mouse 拖拽时手离开摄像头 > 1 秒 | 释放左键，release_all，保持 mouse |
| E2E-X-05 | SolidWorks 平移时手离开 > 1 秒 | 释放中键+Shift，release_all，保持 solidworks |
| E2E-X-06 | PPT 画线时手离开摄像头 > 1 秒  | 释放左键，release_all，保持 pen |
| E2E-X-07 | 重复调用 release_all      | 不报错（幂等）                 |

---

## 10b. 阶段 7 真实设备试运行反馈修正清单

本阶段在现场完成，目标是通过真实摄像头和真实目标程序做小范围修正，使系统适合现场演示。每次修改后必须运行完整 pytest 回归测试。

### 10b.1 Dry-run 标定检查

```text
[ ] Closed_Fist 稳定
[ ] Open_Palm 稳定
[ ] Pointing_Up 稳定
[ ] Victory 稳定
[ ] Thumb_Up / Thumb_Down 稳定
[ ] ILoveYou 稳定
[ ] PINCH 距离在调试窗口显示合理
[ ] FPS 稳定在 20 以上
[ ] 调试窗口显示 pinch、swipe_dx、swipe_dy、hand_lost_duration、cooldown
```

### 10b.2 PPT 真实测试

```text
[ ] Open_Palm 左右翻页可用
[ ] 一次挥手最多翻 1 页
[ ] Victory 进入画笔
[ ] Pointing_Up 移动画笔
[ ] PINCH 画线稳定
[ ] Thumb_Down 擦除
[ ] Thumb_Up 退出画笔
[ ] Closed_Fist 退出演示
```

### 10b.3 Mouse 真实测试

```text
[ ] Pointing_Up 移动，鼠标不抖动、不跳边缘
[ ] PINCH 短按 = 左键单击，不长按变拖拽
[ ] PINCH 长按 + 移动 = 拖拽，释放后左键释放
[ ] Victory 进入滚轮，上下滚动方向符合预期
[ ] Thumb_Down 右键
[ ] Closed_Fist 退出鼠标模式
```

### 10b.4 SolidWorks 真实测试

```text
[ ] Open_Palm 旋转方向和灵敏度合理
[ ] Victory 平移方向和灵敏度合理
[ ] PINCH 缩放有反应，方向合理
[ ] 缩放没反应时，可调整 solidworks_min_zoom_step
[ ] Thumb_Up 缩放全部拟合
[ ] ILoveYou 等轴测视图
[ ] Closed_Fist 退出并释放中键和 Shift
```

### 10b.5 允许现场调整的参数

| 现象 | 调整参数 |
| ---- | -------- |
| 一次挥手翻多页 | 调大 page_turn_cooldown |
| 翻页不灵敏 | 调小 swipe_threshold_x |
| 翻页误触 | 调大 swipe_threshold_x |
| PINCH 不容易触发 | 调大 pinch_threshold |
| PINCH 边界抖动 | 增大 pinch_release_threshold 与 pinch_threshold 的差距 |
| 鼠标抖动 | 调大 mouse_smoothing，调小 mouse_speed |
| 鼠标跟手慢 | 调小 mouse_smoothing，调大 mouse_speed |
| 点击变拖拽 | 调大 drag_hold_time 或 click_max_movement_px |
| 滚轮方向相反 | 将 invert_scroll 设为 True |
| 滚轮太快 | 调小 scroll_amount 或调大 scroll_cooldown |
| SolidWorks 缩放方向相反 | 将 invert_scroll 设为 True（或 solidworks_zoom_sensitivity 负值） |
| SolidWorks 缩放没反应 | 调大 solidworks_min_zoom_step 或 solidworks_zoom_sensitivity |
| 旋转/平移太快 | 调小 solidworks_drag_sensitivity |
| 旋转/平移发抖 | 调大 solidworks_deadzone |

---

## 10c. 阶段 8 GestureRecognizer 接入测试清单

### 10c.1 自动化测试（必须全部通过）

```text
1. GestureRecognizer 输出 Closed_Fist → HandInput.gesture 为 Closed_Fist
2. GestureRecognizer 输出 Open_Palm → HandInput.gesture 为 Open_Palm
3. GestureRecognizer 输出 Pointing_Up → HandInput.gesture 为 Pointing_Up
4. GestureRecognizer 输出 Thumb_Up → HandInput.gesture 为 Thumb_Up
5. GestureRecognizer 输出 Thumb_Down → HandInput.gesture 为 Thumb_Down
6. GestureRecognizer 输出 Victory → HandInput.gesture 为 Victory
7. GestureRecognizer 输出 ILoveYou → HandInput.gesture 为 ILoveYou
8. 低置信度（< min_gesture_confidence）→ 回退旧规则
9. 低置信度 + fallback 关闭 → 输出 None
10. 旧规则 FIST → 归一化为 Closed_Fist
11. 旧规则 OPEN_PALM → 归一化为 Open_Palm
12. 旧规则 SINGLE_FINGER → 归一化为 Pointing_Up
13. 旧规则 TWO_FINGER → 归一化为 Victory
14. PINCH 仍由 landmarks 距离计算，不依赖官方分类
15. SWIPE 仍由 Open_Palm 轨迹在状态机中计算
16. 缺少 gesture_recognizer.task → 模型检查给出明确错误
17. use_gesture_recognizer=False → 不要求 gesture_recognizer.task 存在
18. 阶段 1–7 所有测试仍然通过
```

### 10c.2 Dry-run 真实验证（需要摄像头 + gesture_recognizer.task）

```text
1. 启动 dry-run 模式，确认调试窗口显示：
   - gesture（当前手势）
   - src（识别来源：gesture_recognizer / rule_fallback / none）
   - conf（置信度）
   - raw（原始手势名）
   - pinch_distance / swipe_dx / swipe_dy / FPS / mode / stable_duration
2. 分别做出 7 种官方手势，确认 src 显示 gesture_recognizer 且手势名正确
3. 遮挡摄像头或做出模糊手势，确认低置信度时 src 切换到 rule_fallback
4. 确认 PINCH / SWIPE / HOLD / DRAG 行为不受影响
5. 确认 PPT / mouse / SolidWorks 操作映射不变
```

### 10c.3 Closed_Fist 安全兜底验证

```text
1. 设置 fallback_to_rule_gestures=False
2. 做出握拳手势，确认即使 GestureRecognizer 置信度低，Closed_Fist 仍然被识别
3. 确认 Closed_Fist 仍能触发退出 / release_all
```

---

## 11. 回归测试要求

每次修改以下文件后，必须跑完整回归测试：

```text
gesture_recognition.py
gesture_state.py
gesture_actions.py
gesture_config.py
gesture_controller.py
```

最小回归测试包括：

```bash
pytest tests/test_gesture_recognition.py
pytest tests/test_gesture_state.py
pytest tests/test_gesture_actions.py
pytest tests/test_gesture_controller.py
```

如果测试命令不同，应在 README 或测试说明中更新。

---

## 12. 版本完成定义

### 12.1 PPT 第一版完成定义

```text
可以用手势启动 PPT
可以左右翻页
可以进入画笔并画线
可以擦除
可以退出画笔
可以退出演示
不会出现左键卡住
不会一次挥手翻多页
```

### 12.2 鼠标第一版完成定义

```text
可以进入鼠标模式
可以移动鼠标
可以左键点击
可以拖拽
可以滚轮
可以右键
可以安全退出
```

### 12.3 SolidWorks 第一版完成定义

```text
可以进入 SolidWorks 模式
可以旋转模型
可以平移模型
可以缩放模型
可以缩放全部拟合
可以退出并释放中键和 Shift
```

### 12.4 安全完成定义

```text
Ctrl+Alt+G 可暂停
Ctrl+Alt+Q 可退出
手丢失可 release_all
异常退出可 release_all
release_all 可重复调用
```

---

## 13. 不通过即阻塞的问题

以下问题出现时，不允许进入下一阶段：

```text
鼠标左键、中键、右键卡住
Shift / Ctrl / Alt 卡住
Closed_Fist 不能退出
Ctrl+Alt+Q 不能退出
手丢失后不释放
PPT 一次挥手连续翻多页
SolidWorks 旋转和平移同时触发
Dry-run 仍然控制真实鼠标键盘
```

---

## 14. 第一轮验收建议

第一轮代码修改完成后，建议只验收：

```text
PPT 完整闭环
状态机单元测试
动作层 FakeDriver 测试
release_all 安全测试
Dry-run 端到端测试
```

暂不强制验收：

```text
SolidWorks 全部视图定向
复杂鼠标右键/双击
双手缩放
打包 exe
```

---

## 15. 结论

本项目验收标准不是“代码能运行”这么简单，而是：

```text
动作要可控
退出要可靠
手丢失要释放
误触发要少
测试要可重复
```

所有功能开发完成后，必须按照本文档验收，不能只凭主观感觉判断完成。
