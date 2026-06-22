# GESTURE_MAPPING_SPEC.md

# SmartDesk Gesture Controller 手势映射规范

## 1. 文档目的

本文档用于冻结 SmartDesk Gesture Controller 项目的手势含义与映射规则。

后续代码修改必须遵循本文档，不允许在未更新本文档的情况下自行新增、修改或复用手势含义。

本文档重点解决三个问题：

1. 系统支持哪些基础手势。
2. 每个模式下，每个手势对应什么动作。
3. 如何避免同一个手势在同一个模式下承担多个含义。

---

## 2. 适用范围

本文档适用于以下模块：

```text
hands/gesture_recognition.py
hands/gesture_state.py
hands/gesture_actions.py
hands/gesture_config.py
tests/test_gesture_recognition.py
tests/test_gesture_state.py
tests/test_gesture_actions.py
```

本文档不直接规定 UI 样式、摄像头型号、打包方式和部署方式。

---

## 3. 手势设计原则

### 3.1 同一模式内，手势含义必须唯一

同一个手势在同一个模式中只能对应一个主要动作。

例如：

```text
在 presentation 模式中：
Open_Palm 左右挥手 = 翻页
Open_Palm 保持不再用于启动演示
```

避免以下设计：

```text
Open_Palm 既用于启动演示，又用于翻页，又用于鼠标移动
```

### 3.2 低频操作使用低频手势

模式切换、退出、黑屏、等轴测等低频操作，应使用不容易误触的手势。

推荐：

```text
Closed_Fist：停止、退出、释放
ILoveYou：进入 SolidWorks 或触发低频特殊命令
Thumb_Up：确认、开始、适配视图
Thumb_Down：取消、擦除、右键等负向操作
```

### 3.3 高频连续控制使用稳定手势

旋转、平移、鼠标移动、画笔移动等连续控制，应使用稳定、易保持的手势。

推荐：

```text
Open_Palm：大范围拖动、旋转
Pointing_Up：精确指针、鼠标移动、画笔移动
Victory：二级工具、平移、滚轮子模式
PINCH：点击、拖拽、缩放
```

### 3.4 所有连续动作必须有释放条件

只要涉及以下动作，必须定义释放条件：

```text
mouseDown(left)
mouseDown(middle)
keyDown(shift)
drag
scroll submode
pen submode
```

释放条件至少包括：

```text
手势变化
手丢失
Closed_Fist
模式切换
暂停程序
退出程序
```

### 3.5 安全优先于功能完整

任何时候都必须保证：

```text
Closed_Fist 可以退出当前模式或子模式
手丢失超时后必须 release_all
Ctrl+Alt+G 可以暂停/恢复
Ctrl+Alt+Q 可以紧急退出
```

---

## 4. 手势分类

系统手势分为四类：

```text
官方静态手势
自定义静态手势
自定义动态手势
组合/保持手势
```

---

## 5. 官方静态手势

本项目后续手势识别层应接入 MediaPipe GestureRecognizer。

GestureRecognizer 输出的官方 canned gesture 作为静态手势的优先来源；项目原有的 landmarks 规则判断作为兼容兜底。

优先级如下：

1. MediaPipe GestureRecognizer 官方分类结果
2. 项目自定义 landmarks 规则兜底
3. 如果官方分类置信度低于阈值，则按 None 处理，或回退到规则判断

MediaPipe GestureRecognizer 官方支持以下 canned gesture：

| 官方手势标签 | 中文含义 | 项目内部标准名称 | 建议语义 |
|---|---|---|---|
| `None` | 未识别 / 无有效手势 | `None` | 无动作，必要时释放连续控制 |
| `Closed_Fist` | 握拳 | `Closed_Fist` | 停止、退出、释放所有按键 |
| `Open_Palm` | 张开手掌 | `Open_Palm` | 翻页、旋转、大范围拖动 |
| `Pointing_Up` | 单指向上 | `Pointing_Up` | 鼠标移动、画笔移动、精确指向 |
| `Thumb_Down` | 拇指向下 | `Thumb_Down` | 擦除、取消、右键、负向操作 |
| `Thumb_Up` | 拇指向上 | `Thumb_Up` | 确认、开始、适配视图 |
| `Victory` | V 字手势 | `Victory` | 画笔、平移、滚轮模式 |
| `ILoveYou` | I Love You 手势 | `ILoveYou` | 低频模式切换、特殊命令 |

### 5.1 手势名称兼容映射

为了兼容旧代码，识别层需要把旧规则手势名统一映射到官方手势名。

| 旧规则名称 | 新标准名称 | 说明 |
|---|---|---|
| `FIST` | `Closed_Fist` | 握拳 |
| `OPEN_PALM` | `Open_Palm` | 张开手掌 |
| `SINGLE_FINGER` | `Pointing_Up` | 单指指向 |
| `TWO_FINGER` | `Victory` | 双指 / V 字手势 |
| `NO_HAND` | `None` | 未检测到有效手势 |
| `UNKNOWN` | `None` | 未知或低置信度手势 |

状态机只应处理新标准名称。

也就是说，进入状态机前必须完成名称归一化：

```text
FIST -> Closed_Fist
OPEN_PALM -> Open_Palm
SINGLE_FINGER -> Pointing_Up
TWO_FINGER -> Victory
NO_HAND / UNKNOWN -> None
```

### 5.2 GestureRecognizer 接入原则

GestureRecognizer 负责输出官方静态手势分类结果，同时继续提供 hand landmarks。

本项目的识别策略调整为：

| 功能 | 识别来源 |
|---|---|
| `Closed_Fist` | GestureRecognizer 优先，规则判断兜底 |
| `Open_Palm` | GestureRecognizer 优先，规则判断兜底 |
| `Pointing_Up` | GestureRecognizer 优先，规则判断兜底 |
| `Thumb_Down` | GestureRecognizer 优先 |
| `Thumb_Up` | GestureRecognizer 优先 |
| `Victory` | GestureRecognizer 优先，旧 TWO_FINGER 规则兜底 |
| `ILoveYou` | GestureRecognizer 优先 |
| `None` | GestureRecognizer 输出 None，或低置信度结果 |
| `PINCH` | 仍使用 landmarks 自定义计算 |
| `SWIPE_LEFT / SWIPE_RIGHT` | 仍使用 landmarks 轨迹计算 |
| `HOLD` | 仍由状态机根据 stable_duration 判断 |
| `DRAG` | 仍由状态机根据手部位置变化判断 |

注意：

1. PINCH 不是 MediaPipe GestureRecognizer 的官方 canned gesture，因此不能依赖官方分类输出。
2. SWIPE_LEFT / SWIPE_RIGHT 是动态轨迹手势，也不属于官方静态手势，需要继续由 Open_Palm + 手掌中心轨迹计算。
3. HOLD 不是手势分类结果，而是状态机中的稳定保持时间判断。
4. DRAG 不是手势分类结果，而是连续动作状态。

### 5.3 置信度与兜底规则

识别层应读取 GestureRecognizer 输出的最高置信度手势。

推荐规则：

1. 如果最高置信度 >= min_gesture_confidence：
   使用 GestureRecognizer 输出的官方手势名。

2. 如果最高置信度 < min_gesture_confidence：
   优先尝试旧 landmarks 规则兜底。

3. 如果兜底规则也无法稳定判断：
   输出 None。

4. 对安全相关手势 Closed_Fist，可以允许规则判断兜底优先保留。
   原因：Closed_Fist 用于退出和 release_all，不能因为官方分类不稳定而完全失效。

5. 对 Thumb_Up、Thumb_Down、ILoveYou，优先使用 GestureRecognizer。
   原因：这些手势使用纯规则判断受摄像头角度影响较大，容易不稳定。

---

## 6. 自定义静态手势

### 6.1 PINCH

`PINCH` 不依赖官方 GestureRecognizer，而是由 landmarks 计算得到。

判断方式：

```text
thumb_tip = landmark[4]
index_tip = landmark[8]

pinch_distance = distance(thumb_tip, index_tip)

当 pinch_distance < pinch_threshold 时，认为进入 PINCH。
当 pinch_distance > pinch_release_threshold 时，认为释放 PINCH。
```

要求：

```text
pinch_release_threshold 必须大于 pinch_threshold
必须使用滞回机制，避免捏合边界抖动
```

推荐默认值：

```text
pinch_threshold = 0.045
pinch_release_threshold = 0.065
```

具体数值允许在 `gesture_config.py` 或未来的 `config.json` 中调整。

---

## 7. 自定义动态手势

### 7.1 SWIPE_LEFT / SWIPE_RIGHT

用于 PPT 翻页。

基础手势：

```text
Open_Palm
```

判断条件：

```text
在 swipe_time_window 内，手掌中心 x 方向位移超过 swipe_threshold_x
同时 y 方向位移不能过大
```

推荐规则：

```text
SWIPE_RIGHT:
    dx > swipe_threshold_x
    abs(dy) < swipe_threshold_y_limit

SWIPE_LEFT:
    dx < -swipe_threshold_x
    abs(dy) < swipe_threshold_y_limit
```

推荐默认值：

```text
swipe_threshold_x = 0.18
swipe_threshold_y_limit = 0.12
swipe_time_window = 0.8s
swipe_cooldown = 0.8s
```

### 7.2 HOLD

用于确认类动作。

判断方式：

```text
同一手势连续稳定保持超过 hold_time
```

要求：

```text
HOLD 期间如果手势变化，计时重置
HOLD 期间如果手丢失，计时重置
HOLD 触发后必须进入 cooldown
```

### 7.3 DRAG

用于鼠标拖拽、SolidWorks 旋转、SolidWorks 平移。

判断方式：

```text
某个连续控制手势保持时，根据手掌中心或食指位置计算 dx / dy
```

要求：

```text
DRAG 必须有 begin / update / end 三个阶段
禁止每帧重复 mouseDown + mouseUp
```

---

## 8. 全局手势映射

全局手势在所有模式下均生效。

| 手势               | 触发条件                      | 动作               | 说明          |
| ---------------- | ------------------------- | ---------------- | ----------- |
| `None`           | 手丢失超过 `hand_lost_timeout` | `release_all`    | 释放所有鼠标键和辅助键 |
| `Closed_Fist`    | 保持 0.5–0.8 秒              | 退出当前子模式 / 停止连续动作 | 优先级最高       |
| `Closed_Fist` 长按 | 保持 1.5 秒                  | 回到 `standby`     | 强制回待机       |
| `Ctrl+Alt+G`     | 键盘热键                      | 暂停 / 恢复          | 不依赖手势识别     |
| `Ctrl+Alt+Q`     | 键盘热键                      | 紧急退出程序           | 不依赖手势识别     |

全局规则：

```text
任何模式下，只要触发 Closed_Fist，都必须先执行 release_all，再切换状态。
```

---

## 9. Standby 待机模式手势映射

待机模式的目标是避免误触。

| 手势            | 触发条件     | 动作                        | 说明                 |
| ------------- | -------- | ------------------------- | ------------------ |
| `Thumb_Up`    | 保持 1.5 秒 | 发送 `F5`，进入 `presentation` | 启动 PPT 演示          |
| `Pointing_Up` | 保持 1.0 秒 | 进入 `mouse`                | 启动鼠标控制             |
| `ILoveYou`    | 保持 1.5 秒 | 进入 `solidworks`           | 启动 SolidWorks 查看模式 |
| `Open_Palm`   | 任意       | 不执行动作                     | 避免自然抬手误触           |
| `Closed_Fist` | 任意       | 保持待机                      | 不执行动作              |
| `None`        | 任意       | 不执行动作                     | 安全待机               |

说明：

```text
standby 模式下不使用 Open_Palm 启动演示。
原因：Open_Palm 是自然伸手动作，误触概率较高。
```

---

## 10. PPT 演示模式手势映射

模式名称：

```text
presentation
```

适用场景：

```text
PowerPoint 已打开，或已经进入幻灯片放映模式。
```

| 功能     | 手势                     | 动作                                           | 优先级 |
| ------ | ---------------------- | -------------------------------------------- | --- |
| 下一页    | `Open_Palm` 向右挥        | `press("right")` 或 `press("pagedown")`       | 高   |
| 上一页    | `Open_Palm` 向左挥        | `press("left")` 或 `press("pageup")`          | 高   |
| 进入画笔模式 | `Victory` 保持 0.5 秒     | `hotkey("ctrl", "p")`，进入 `presentation_pen`  | 中   |
| 擦除画笔痕迹 | `Thumb_Down` 保持 0.5 秒  | `press("e")`                                 | 中   |
| 取消画笔   | `Thumb_Up` 保持 0.5 秒    | `hotkey("ctrl", "a")`                        | 中   |
| 退出演示   | `Closed_Fist` 保持 0.8 秒 | `press("esc")` + `release_all` + 回 `standby` | 高   |
| 黑屏     | `ILoveYou` 保持 0.8 秒    | `press("b")`                                 | 低   |

限制：

```text
presentation 模式下，Thumb_Up 不再触发 F5。
presentation 模式下，Open_Palm 保持不触发任何动作，只识别左右挥动。
```

---

## 11. PPT 画笔子模式手势映射

模式名称：

```text
presentation_pen
```

进入条件：

```text
presentation 模式下 Victory 保持 0.5 秒
```

| 功能   | 手势                     | 动作                                           |
| ---- | ---------------------- | -------------------------------------------- |
| 移动画笔 | `Pointing_Up` 移动       | 鼠标移动                                         |
| 开始画线 | `PINCH` 开始             | `mouse_down("left")`                         |
| 持续画线 | `PINCH` 保持 + 移动        | 鼠标移动                                         |
| 停止画线 | `PINCH` 释放             | `mouse_up("left")`                           |
| 擦除痕迹 | `Thumb_Down` 保持 0.5 秒  | `press("e")`                                 |
| 退出画笔 | `Thumb_Up` 保持 0.5 秒    | `hotkey("ctrl", "a")`，回 `presentation`       |
| 退出演示 | `Closed_Fist` 保持 0.8 秒 | `press("esc")` + `release_all` + 回 `standby` |

限制：

```text
presentation_pen 中，Victory 不再重复触发 Ctrl+P。
PINCH 只负责画线，不负责普通点击。
```

---

## 12. 鼠标模式手势映射

模式名称：

```text
mouse
```

| 功能      | 手势                     | 动作                          |
| ------- | ---------------------- | --------------------------- |
| 鼠标移动    | `Pointing_Up`          | 根据食指或手掌中心移动鼠标               |
| 左键单击    | `PINCH` 短按             | `click("left")`             |
| 拖拽开始    | `PINCH` 长按             | `mouse_down("left")`        |
| 拖拽持续    | `PINCH` 长按 + 移动        | 鼠标移动                        |
| 拖拽结束    | `PINCH` 释放             | `mouse_up("left")`          |
| 进入滚轮子模式 | `Victory` 保持 0.5 秒     | 进入 `mouse_scroll`           |
| 右键单击    | `Thumb_Down` 保持 0.5 秒  | `click("right")`            |
| 退出鼠标模式  | `Closed_Fist` 保持 0.8 秒 | `release_all` + 回 `standby` |

限制：

```text
鼠标模式下，Open_Palm 不执行动作。
避免用户自然张手时干扰鼠标控制。
```

---

## 13. 鼠标滚轮子模式手势映射

模式名称：

```text
mouse_scroll
```

| 功能     | 手势                        | 动作                |
| ------ | ------------------------- | ----------------- |
| 向上滚动   | `Victory` + 手向上移动         | `scroll(+amount)` |
| 向下滚动   | `Victory` + 手向下移动         | `scroll(-amount)` |
| 退出滚轮模式 | `Closed_Fist` 或 `None` 超时 | 回 `mouse`         |

限制：

```text
只有进入 mouse_scroll 后，手掌上下移动才会触发滚轮。
普通 mouse 模式下不允许 y 方向移动直接触发滚轮。
```

---

## 14. SolidWorks 模式手势映射

模式名称：

```text
solidworks
```

| 功能               | 手势                     | 动作                          | 优先级 |
| ---------------- | ---------------------- | --------------------------- | --- |
| 旋转模型             | `Open_Palm` + 移动       | 按住中键拖动                      | 高   |
| 平移模型             | `Victory` + 移动         | `Shift` + 中键拖动              | 高   |
| 缩放模型             | `PINCH` 距离变化           | 鼠标滚轮                        | 高   |
| 缩放全部拟合           | `Thumb_Up` 保持 0.5 秒    | `press("f")`                | 中   |
| 等轴测视图            | `ILoveYou` 保持 0.8 秒    | `hotkey("ctrl", "7")`       | 中   |
| 退出 SolidWorks 模式 | `Closed_Fist` 保持 0.8 秒 | `release_all` + 回 `standby` | 高   |

### 14.1 旋转模型规则

```text
Open_Palm 首次稳定出现并产生移动：
    mouse_down("middle")

Open_Palm 持续移动：
    move_rel(dx, dy)

Open_Palm 消失、手势变化、手丢失、Closed_Fist：
    mouse_up("middle")
```

禁止：

```text
每帧执行 mouse_down + move + mouse_up
```

### 14.2 平移模型规则

```text
Victory 首次稳定出现并产生移动：
    key_down("shift")
    mouse_down("middle")

Victory 持续移动：
    move_rel(dx, dy)

Victory 消失、手势变化、手丢失、Closed_Fist：
    mouse_up("middle")
    key_up("shift")
```

### 14.3 缩放模型规则

```text
PINCH 距离增大：
    scroll(+amount)

PINCH 距离减小：
    scroll(-amount)
```

如果 PINCH 距离变化在死区内，不触发滚轮。

---

## 15. 手势优先级

当同一帧或同一时间窗口内识别到多个可能动作时，按以下优先级处理：

```text
1. Ctrl+Alt+Q 紧急退出
2. Ctrl+Alt+G 暂停/恢复
3. Closed_Fist 停止/退出
4. None 超时释放
5. 当前连续动作释放逻辑
6. 当前模式下的 HOLD 动作
7. 当前模式下的动态动作
8. 当前模式下的普通静态动作
```

---

## 16. 冷却时间规则

所有离散动作必须有冷却时间。

离散动作包括：

```text
翻页
开始演示
退出演示
进入画笔
擦除
取消画笔
右键
缩放全部拟合
等轴测
模式切换
```

推荐默认值：

```text
page_turn_cooldown = 0.8s
mode_switch_cooldown = 1.0s
click_cooldown = 0.25s
right_click_cooldown = 0.5s
pen_toggle_cooldown = 0.6s
solidworks_view_cooldown = 0.8s
```

---

## 17. 手势稳定时间规则

需要保持的手势必须经过稳定时间确认。

推荐默认值：

```text
start_presentation_hold = 1.5s
enter_mouse_hold = 1.0s
enter_solidworks_hold = 1.5s
exit_mode_hold = 0.8s
pen_mode_hold = 0.5s
erase_hold = 0.5s
right_click_hold = 0.5s
fit_view_hold = 0.5s
isometric_view_hold = 0.8s
```

---

## 18. 第一版实现范围

当前版本在原有 landmarks 规则识别的基础上，新增 MediaPipe GestureRecognizer 接入要求。

接入后，各模式下的手势操作映射保持不变，只改变静态手势的识别来源。

具体映射如下：

```text
1. Standby:
   - Thumb_Up 启动 PPT
   - Pointing_Up 进入鼠标模式
   - ILoveYou 进入 SolidWorks 模式

2. PPT:
   - Open_Palm 左右翻页
   - Victory 进入画笔
   - Thumb_Down 擦除
   - Thumb_Up 取消画笔
   - Closed_Fist 退出演示

3. Mouse:
   - Pointing_Up 移动
   - PINCH 左键点击
   - PINCH 长按拖拽
   - Victory 进入滚轮模式
   - Thumb_Down 右键
   - Closed_Fist 退出

4. SolidWorks:
   - Open_Palm 旋转
   - Victory 平移
   - PINCH 缩放
   - Thumb_Up 缩放全部拟合
   - ILoveYou 等轴测
   - Closed_Fist 退出
```

暂缓实现：

```text
白屏 W
多种视图定向 Ctrl+1 / Ctrl+2 / Ctrl+3
双手缩放
多台电脑控制
复杂手势教学 UI
```

### 18.1 GestureRecognizer 接入后不改变的内容

接入 GestureRecognizer 后，以下内容不应改变：

1. 状态机模式名称不变：
   standby
   presentation
   presentation_pen
   mouse
   mouse_scroll
   solidworks
   paused

2. ActionIntent 接口不变。

3. release_all 逻辑不变。

4. PINCH 仍然通过 landmarks 距离计算。

5. SWIPE_LEFT / SWIPE_RIGHT 仍然通过 Open_Palm 的轨迹计算。

6. HOLD 仍然由状态机根据 stable_duration 计算。

7. DRAG / move_rel / scroll 等连续动作逻辑不变。

8. PPT、mouse、SolidWorks 的操作映射不变。

本次接入 GestureRecognizer 的目标是提升静态手势识别稳定性，而不是重新设计交互。

### 18.2 GestureRecognizer 接入后的模型文件要求

接入 GestureRecognizer 后，项目根目录需要同时检查以下模型文件：

```text
hand_landmarker.task
gesture_recognizer.task
```

说明：

1. 如果后续完全切换到 GestureRecognizer，并且 GestureRecognizer 已经提供 landmarks，则可以评估是否仍需要 hand_landmarker.task。
2. 在过渡阶段，建议保留 hand_landmarker.task，避免破坏现有 PINCH / SWIPE / DRAG 逻辑。
3. 现场演示不应依赖自动下载模型文件。
4. 如果缺少 gesture_recognizer.task，应给出明确错误提示。

### 18.3 最小代码改动目标

代码实现时应遵循最小改动原则：

1. 在 gesture_recognition.py 中新增 GestureRecognizer 初始化和推理逻辑。
2. 新增 gesture_recognizer.task 模型文件检查。
3. 输出统一 HandInput，字段尽量保持兼容。
4. HandInput 中的 gesture 名称统一为官方标准名称：
   Closed_Fist
   Open_Palm
   Pointing_Up
   Thumb_Down
   Thumb_Up
   Victory
   ILoveYou
   None

5. 保留 landmarks 输出，继续支持 PINCH / SWIPE / DRAG。
6. 状态机 gesture_state.py 尽量不大改。
7. 动作层 gesture_actions.py 不应修改。
8. 已有阶段 1–7 测试必须继续通过。
9. 新增测试应重点覆盖：
   - GestureRecognizer 官方手势名归一化
   - 低置信度结果回退 None
   - PINCH 仍由 landmarks 计算
   - SWIPE 仍由 Open_Palm 轨迹计算
   - 状态机不因识别来源变化而改变行为

---

## 19. 后续修改要求

任何新增手势必须先修改本文档，再改代码。

新增手势时必须补充：

```text
1. 手势名称
2. 识别来源
3. 所属模式
4. 触发条件
5. 动作
6. 冷却时间
7. 释放条件
8. 测试方法
```

---

## 20. 结论

本项目第一版手势设计目标不是“手势越多越好”，而是：

```text
PPT 演示闭环稳定
鼠标模式不误触
SolidWorks 能旋转、平移、缩放
任何时候都能安全退出和释放按键
```

后续开发必须优先保证安全性、稳定性和可测试性。
