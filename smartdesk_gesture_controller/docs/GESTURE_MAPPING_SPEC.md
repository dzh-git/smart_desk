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
hands/gesture_intent_tracker.py
hands/gesture_state.py
hands/gesture_actions.py
hands/gesture_config.py
tests/test_gesture_recognition.py
tests/test_gesture_intent_tracker.py
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
ILoveYou：模式切换（PPT ↔ SolidWorks ↔ Standby）
Victory：画笔模式进入/退出
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

第一阶段中，手势类别只作为进入控制流程的信号。进入 attempt/session 后，不要求每一帧继续识别为同一个手势，后续主要由标准化位置、位移、速度、pinch_distance 和超时规则维持流程。

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

| 官方手势标签 | 中文含义 | 项目内部标准名称 | 建议语义 | 状态 |
|---|---|---|---|---|
| `None` | 未识别 / 无有效手势 | `None` | 无动作，必要时释放连续控制 | 保留 |
| `Closed_Fist` | 握拳 | `Closed_Fist` | 停止、退出、释放所有按键 | 保留 |
| `Open_Palm` | 张开手掌 | `Open_Palm` | 翻页、旋转、大范围拖动 | 保留 |
| `Pointing_Up` | 单指向上 | `Pointing_Up` | 鼠标移动、画笔移动、精确指向 | 保留 |
| `Thumb_Down` | 拇指向下 | 识别层保留；状态机归一化为 `None` | **已废弃** - 第一版不使用 | 废弃 |
| `Thumb_Up` | 拇指向上 | 识别层保留；状态机归一化为 `None` | **已废弃** - 第一版不使用 | 废弃 |
| `Victory` | V 字手势 | `Victory` | 画笔、平移、滚轮模式 | 保留 |
| `ILoveYou` | I Love You 手势 | `ILoveYou` | 模式切换、特殊命令 | 保留 |

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

状态机处理标准名称；当前实现会进一步把 `Thumb_Up` / `Thumb_Down` 归一化为 `None`，确保其不进入任何功能分支。

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

| 功能 | 识别来源 | 状态 |
|---|---|---|
| `Closed_Fist` | GestureRecognizer 优先，规则判断兜底 | 保留 |
| `Open_Palm` | GestureRecognizer 优先，规则判断兜底 | 保留 |
| `Pointing_Up` | GestureRecognizer 优先，规则判断兜底 | 保留 |
| `Thumb_Down` | **第一版禁用** | 废弃 |
| `Thumb_Up` | **第一版禁用** | 废弃 |
| `Victory` | GestureRecognizer 优先，旧 TWO_FINGER 规则兜底 | 保留 |
| `ILoveYou` | GestureRecognizer 优先 | 保留 |
| `None` | GestureRecognizer 输出 None，或低置信度结果 | 保留 |
| `PINCH` | 仍使用 landmarks 自定义计算 | 保留 |
| `SWIPE_LEFT / SWIPE_RIGHT` | 仍使用 landmarks 轨迹计算 | 保留 |
| `HOLD` | 仍由状态机根据 stable_duration 判断 | 保留 |
| `DRAG` | 仍由状态机根据手部位置变化判断 | 保留 |

**废弃说明**：

```text
Thumb_Up / Thumb_Down 在真实摄像头环境中容易受手腕角度、左右手、摄像头镜像影响，
误识别风险较高。第一版稳定演示中不再使用这两个手势触发动作。
```

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

4. 规则回退结果不参与 `gesture_enter_confidence` 判断，但不能直接绕过稳定确认。进入控制流程仍必须满足 `gesture_enter_frames`、`gesture_enter_window_frames`、必要的 `arm_duration` 和轨迹一致性。

5. 对安全相关手势 Closed_Fist，可以允许规则判断兜底优先保留。
   原因：Closed_Fist 用于退出和 release_all，不能因为官方分类不稳定而完全失效。

6. **Thumb_Up、Thumb_Down 在第一版中禁用**。
   原因：这些手势使用纯规则判断受摄像头角度影响较大，容易不稳定。
   第一版稳定演示中不再使用这两个手势触发动作。

---

## 6. 自定义静态手势

### 6.1 PINCH

`PINCH` 不依赖官方 GestureRecognizer，而是由 landmarks 计算得到。

判断方式：

```text
thumb_tip = landmark[4]
index_tip = landmark[8]

pinch_distance = distance(thumb_tip, index_tip)
pinch_distance_norm = pinch_distance / hand_size  # 尺度无关

当 pinch_distance_norm < pinch_threshold 时，认为进入 PINCH。
当 pinch_distance_norm > pinch_release_threshold 时，认为释放 PINCH。
```

要求：

```text
pinch_release_threshold 必须大于 pinch_threshold
必须使用滞回机制，避免捏合边界抖动
pinch_distance_norm 是尺度无关的归一化值（0–1），不受手离摄像头远近影响
```

推荐默认值：

```text
pinch_threshold = 0.045
pinch_release_threshold = 0.2
```

具体数值允许在 `gesture_config.py` 或未来的 `config.json` 中调整。

---

## 7. 自定义动态手势

### 7.1 SWIPE_LEFT / SWIPE_RIGHT

用于 PPT 翻页。第一阶段由 `GestureIntentTracker` 输出 `page_swipe_left/right`，状态机不再直接根据 raw gesture 维护翻页轨迹。

基础手势：

```text
Open_Palm
```

判断条件：

```text
Open_Palm 稳定进入 page attempt 后，在 `page_swipe_timeout` 内，手掌中心 x 方向位移超过 swipe_threshold_x
同时 y 方向位移不能过大
同一 attempt 只能 committed 一次
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
swipe_threshold_x = 0.15
swipe_threshold_y_limit = 0.12
page_swipe_timeout = 2.0s
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

用于鼠标拖拽、SolidWorks 旋转、SolidWorks 平移。第一阶段 SolidWorks 旋转和平移由 `ControlSession` 管理。

判断方式：

```text
某个连续控制手势保持时，根据手掌中心或食指位置计算 dx / dy
```

要求：

```text
DRAG 必须有 begin / update / end 三个阶段
禁止每帧重复 mouseDown + mouseUp
session 活动期间不得启动第二种控制或模式切换
```

### 7.4 GestureIntentTracker 第一阶段事件

第一阶段固定输出以下 `ControlEvent.type`：

```text
mode_swipe_left
mode_swipe_right
page_swipe_left
page_swipe_right
rotate_begin
rotate_update
rotate_end
pan_begin
pan_update
pan_end
zoom_update
cancel
hand_lost_timeout
pen_mode_toggle
pen_draw_begin
pen_draw_update
pen_draw_end
fist_hold_committed
```

模式切换、翻页和缩放使用短期 `attempt_id`。旋转和平移使用 `session_id`。画笔绘制（`pen_draw`）使用 `session_id`（持有左键）。画笔切换和握拳退出使用短期 `attempt_id`（HOLD-to-commit 模式）。同一个 attempt 在 committed 后，直到 released / cancelled / timeout 前不得再次 committed。

---

## 8. 全局手势映射

全局手势在所有模式下均生效。

| 手势               | 触发条件                      | 动作               | 说明          |
| ---------------- | ------------------------- | ---------------- | ----------- |
| `None`           | 每次连续手丢失首次超过 `hand_lost_timeout` | `release_all` | 后续无手帧不重复释放，见手后重新布防 |
| `Closed_Fist`    | standby 中立即；活动模式保持 0.8 秒 | 释放或退出当前模式 | 优先级最高 |
| `Ctrl+Alt+G`     | 键盘热键                      | 暂停 / 恢复          | 不依赖手势识别     |
| `Ctrl+Alt+Q`     | 键盘热键                      | 紧急退出程序           | 不依赖手势识别     |

全局规则：

```text
standby 中 Closed_Fist 立即执行 `release_all` 并保持待机；presentation、presentation_pen、solidworks 中保持 0.8 秒后按各模式退出序列释放并回待机。
```

**注意**：第一版中 `Thumb_Up` / `Thumb_Down` 不再触发任何全局动作。

识别层仍可报告这两个官方标签，但当前状态机兼容映射会把它们转换为 `None`。

---

## 9. Standby 待机模式手势映射

待机模式的目标是避免误触，并提供稳定的模式切换方式。

| 手势            | 触发条件     | 动作                        | 说明                 |
| ------------- | -------- | ------------------------- | ------------------ |
| `ILoveYou`    | 向右滑动    | 进入 `presentation`          | 切换到 PPT 演示模式      |
| `ILoveYou`    | 向左滑动    | 进入 `solidworks`           | 切换到 SolidWorks 模式  |
| `Closed_Fist` | 任意       | 保持待机 / `release_all`    | 确保安全              |
| `Open_Palm`   | 任意       | 不执行动作                     | 避免自然抬手误触           |
| `Pointing_Up` | 任意       | 不执行动作                     | 第一版不使用此手势启动鼠标模式  |
| `Victory`     | 任意       | 不执行动作                     | 避免误触              |
| `None`        | 任意       | 不执行动作                     | 安全待机               |

**模式切换说明**：

```text
Standby 不再通过 Thumb_Up 启动 PPT，也不再进入 mouse 模式。
模式切换统一由 ILoveYou 左右滑完成。

ILoveYou 滑动方向规则（Phase 9 最终版）：

  standby:
    右滑 → presentation
    左滑 → solidworks

  presentation:
    右滑 → standby
    左滑 → solidworks

  solidworks:
    右滑 → presentation
    左滑 → standby

进入 presentation 时不发送 F5，PPT 幻灯片放映由用户手动启动。
standby → presentation / solidworks 只更新内部模式，不输出系统动作；从活动模式离开时执行安全释放（`release_all`）。Closed_Fist HOLD 退出活动模式时会额外发送 `Esc`；ILoveYou 滑动切换只发送 `release_all`，不发送 `Esc`。
```

**滑动检测要求**：

```text
1. ILoveYou 必须先满足 gesture_enter_frames / gesture_enter_window_frames、gesture_enter_confidence 和 mode_arm_duration。
2. armed 后只跟踪 palm_xy 轨迹，不要求后续帧继续识别为 ILoveYou。
3. swipe 必须满足 x 方向阈值、y 方向限制、min_motion_duration 和 direction_consistency_frames。
4. 同一 gesture_attempt_id committed 后，直到 released/cancelled/timeout 前不得再次 committed。
5. mode_switch_cooldown 由 GestureState 管理。
6. 推荐参数：
   - iloveyou_swipe_threshold_x = 0.18
   - swipe_threshold_y_limit = 0.12（ILoveYou 复用）
   - mode_swipe_timeout = 3.0s
   - mode_switch_cooldown = 1.0s
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
| 模式切换   | `ILoveYou` 右滑/左滑     | 右滑：`release_all` 并回 standby；左滑：`release_all` 并进 solidworks | 中   |
| 退出演示   | `Closed_Fist` 保持 0.8 秒 | `press("esc")` + `release_all` + 回 `standby` | 高   |
| 手丢失超时  | `None` 首次超过超时时间    | `release_all`，保持 `presentation`；连续无手不重复 | 高 |

**第一版简化说明**：

```text
PPT 模式不再提供手势擦除。
第一版只保留翻页、进入画笔、退出演示和模式切换。
```

限制：

```text
presentation 模式下，Victory 不再重复触发 Ctrl+P。
presentation 模式下 Open_Palm 保持不触发任何动作，只识别左右挥动。
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
| 退出画笔 | `Victory` 保持 0.5 秒     | `hotkey("ctrl", "a")`，回 `presentation`       |
| 退出演示 | `Closed_Fist` 保持 0.8 秒 | `press("esc")` + `release_all` + 回 `standby` |
| 手丢失  | `None` 首次超过超时时间    | 按需 `mouse_up("left")` + `release_all`，保持 `presentation_pen`；连续无手不重复 |

**画笔切换说明**：

```text
Victory 在 presentation 中表示进入画笔；
Victory 在 presentation_pen 中表示退出画笔。
```

限制：

```text
presentation_pen 中，Victory 不再重复触发 Ctrl+P。
PINCH 只负责画线，不负责普通点击。
```

---

## 12. 鼠标模式手势映射（已废弃）

> **Deprecated / Disabled in simplified demo version**
>
> 由于当前演示重点是 PPT 和 SolidWorks，且鼠标模式会增加误触和调试成本，
> 简化版本暂时禁用 mouse / mouse_scroll。

模式名称：

```text
mouse（已废弃）
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

**第一版不启用此模式。保留为后续版本参考。**

---

## 13. 鼠标滚轮子模式手势映射（已废弃）

> **Deprecated / Disabled in simplified demo version**
>
> 由于当前演示重点是 PPT 和 SolidWorks，且鼠标模式会增加误触和调试成本，
> 简化版本暂时禁用 mouse / mouse_scroll。

模式名称：

```text
mouse_scroll（已废弃）
```

| 功能     | 手势                        | 动作                |
| ------ | ------------------------- | ----------------- |
| 向上滚动   | `Victory` + 手向上移动         | `scroll(+amount)` |
| 向下滚动   | `Victory` + 手向下移动         | `scroll(-amount)` |
| 退出滚轮模式 | `Closed_Fist` 或 `None` 超时 | 回 `mouse`         |

**第一版不启用此模式。保留为后续版本参考。**

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
| 模式切换             | `ILoveYou` 右滑/左滑     | 右滑：结束连续动作并切到 presentation（无 release_all）；左滑：结束连续动作 + `release_all` 后切到 standby | 中 |
| 退出 SolidWorks 模式 | `Closed_Fist` 保持 0.8 秒 | 结束连续动作 + `press("esc")` + `release_all` + 回 `standby` | 高   |
| 手丢失超时            | `None` 首次超过超时时间    | 按需释放中键/Shift + `release_all`，保持 `solidworks`；连续无手不重复 | 高 |

### 14.1 旋转模型规则

```text
Open_Palm 通过 Tracker 稳定确认并超过最小运动要求后：
    mouse_down("middle")

rotate session 持续：
    move_rel(dx, dy)

rotate session 正常结束：
    mouse_up("middle")

真正手丢失超时、模式切换、异常或退出：
    mouse_up("middle")（如需要）+ release_all
```

禁止：

```text
每帧执行 mouse_down + move + mouse_up
分类抖动时立即结束 rotate
rotate 活动期间启动 pan / zoom / mode switch
```

### 14.2 平移模型规则

```text
Victory 通过 Tracker 稳定确认并超过最小运动要求后：
    key_down("shift")
    mouse_down("middle")

pan session 持续：
    move_rel(dx, dy)

pan session 正常结束：
    mouse_up("middle")
    key_up("shift")

真正手丢失超时、模式切换、异常或退出：
    mouse_up("middle") + key_up("shift")（如需要）+ release_all
```

### 14.3 缩放模型规则

```text
pinch_distance_norm 距离增大且超过 deadzone：
    scroll(+amount)

pinch_distance_norm 距离减小且超过 deadzone：
    scroll(-amount)
```

如果 `pinch_distance_norm` 变化在死区内，不触发滚轮。SolidWorks 缩放使用 `pinch_distance_norm`（拇指尖与食指尖距离除以 `hand_size`，尺度无关），不依赖 `PINCH` 静态分类名称，也不使用原始像素距离。

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
进入/退出画笔
退出演示
模式切换
```

推荐默认值：

```text
page_turn_cooldown = 0.8s
mode_switch_cooldown = 1.0s
click_cooldown = 0.35s  # 兼容 mouse 逻辑，当前模式已禁用
right_click_cooldown = 0.5s
pen_toggle_cooldown = 0.6s
solidworks_view_cooldown = 0.8s
```

其中 `click_cooldown`、`right_click_cooldown`、`solidworks_view_cooldown` 是当前保留的兼容配置；简化主流程不使用对应鼠标点击或视图快捷键动作。

---

## 17. 手势稳定时间规则

需要保持的手势必须经过稳定时间确认。

推荐默认值：

```text
exit_mode_hold = 0.8s
pen_mode_hold = 0.5s
mode_switch_cooldown = 1.0s
page_turn_cooldown = 0.8s
```

**已废弃参数**（第一版不使用）：

```text
start_presentation_hold  # 不再使用 Thumb_Up 启动 PPT
enter_mouse_hold          # mouse 模式已禁用
erase_hold                # 不再使用 Thumb_Down 擦除
right_click_hold          # 不再使用 Thumb_Down 右键
fit_view_hold             # 不再使用 Thumb_Up 拟合视图
isometric_view_hold       # 不再使用 ILoveYou 等轴测
```

**新增参数说明**：

```text
iloveyou_swipe_threshold_x = 0.18  # ILoveYou 专用 x 方向阈值
swipe_threshold_y_limit = 0.12     # Open_Palm / ILoveYou 共用 y 限制
mode_swipe_timeout = 3.0s          # 模式切换 attempt 最长追踪时间
page_swipe_timeout = 2.0s          # 翻页 attempt 最长追踪时间
mode_switch_cooldown = 1.0s        # 模式切换冷却时间
pen_mode_hold = 0.5s               # Victory 进入/退出画笔的保持时间
exit_mode_hold = 0.8s              # Closed_Fist 退出活动模式保持时间
```

---

## 18. 第一版简化实现范围

当前阶段在已有 GestureRecognizer / landmarks 识别基础上，新增 `GestureIntentTracker` 控制流程层。

已迁移到 Tracker 事件路径的功能包括：模式切换、PPT 翻页、SolidWorks 旋转/平移/缩放、PPT 画笔绘制（PINCH）、Victory 画笔切换（HOLD toggle）、Closed_Fist 退出（HOLD commit）。暂停恢复仍由控制器兼容路径处理。

**第一版简化实现范围**：

```text
1. Standby:
   - ILoveYou 稳定进入 attempt 后右滑进入 presentation
   - ILoveYou 稳定进入 attempt 后左滑进入 solidworks
   - Closed_Fist 保持待机 / release_all

2. PPT:
   - Open_Palm 稳定进入 attempt 后左右翻页
   - Victory 进入画笔
   - Victory 退出画笔
   - Closed_Fist 退出演示

3. PPT 画笔:
   - Pointing_Up 移动画笔
   - PINCH 画线
   - Victory 退出画笔
   - Closed_Fist 退出演示

4. SolidWorks:
   - Open_Palm 稳定进入 rotate session 后旋转
   - Victory 稳定进入 pan session 后平移
   - pinch_distance 缩放
   - ILoveYou 稳定进入 attempt 后右滑/左滑切换模式
   - Closed_Fist 退出
```

**暂缓实现**：

```text
- Thumb_Up（已废弃）
- Thumb_Down（已废弃）
- mouse（已废弃）
- mouse_scroll（已废弃）
- 手势擦除
- SolidWorks 拟合视图
- SolidWorks 等轴测视图
- 白屏 W
- 多种视图定向 Ctrl+1 / Ctrl+2 / Ctrl+3
- 双手缩放
- 多台电脑控制
- 复杂手势教学 UI
```

### 18.1 控制流程驱动后不改变的内容

接入 `GestureIntentTracker` 后，以下内容不应改变：

1. 状态机模式名称不变：
   standby
   presentation
   presentation_pen
   solidworks
   paused
   ~~mouse（已废弃）~~
   ~~mouse_scroll（已废弃）~~

2. ActionIntent 接口不变。

3. release_all 的安全用途不变，但同一次手丢失事件不得逐帧重复输出。

4. PINCH / 缩放仍然通过 landmarks 的 pinch_distance 计算，不依赖静态 PINCH 分类名。

5. SWIPE_LEFT / SWIPE_RIGHT 仍然通过轨迹计算，但由 Tracker 输出 page/mode ControlEvent。

6. 未迁移的 HOLD 仍然由状态机兼容路径根据 stable_duration 计算。

7. move_rel / scroll / mouse_down / mouse_up 等 ActionIntent 不新增类型。

8. PPT、SolidWorks 的操作映射不变（已简化）。

本次目标是提升动态控制稳定性，而不是一次重写所有模式。

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

### 18.3 第一阶段最小代码改动目标

代码实现时应遵循最小改动原则：

1. 新增 `hands/gesture_intent_tracker.py`。
2. 识别层输出 `GestureFrame` 所需字段：hand_present、raw_gesture、gesture_confidence、gesture_source、palm_xy、index_tip_xy、pinch_distance、timestamp。
3. `GestureState` 新增 ControlEvent 处理路径，同时保留未迁移功能的 HandInput 兼容路径。
4. 模式切换、PPT 翻页、SolidWorks 旋转/平移/缩放只消费 Tracker 输出事件。
5. PPT 画笔绘制（PINCH）、Victory 画笔切换（HOLD toggle）、Closed_Fist 退出（HOLD commit）已迁移到 Tracker 事件路径（`EVT_PEN_DRAW_*`、`EVT_PEN_MODE_TOGGLE`、`EVT_FIST_HOLD_COMMITTED`）。暂停恢复不在 Tracker 迁移范围。
6. 动作层 `gesture_actions.py` 不应新增动作类型。
7. 已有测试必须继续通过。
8. 新增测试应重点覆盖：
   - raw_gesture=None 与 hand_present=False 的区别
   - attempt_id 防重复提交
   - session_id 防重复 mouse_down/key_down
   - 分类抖动不打断 rotate/pan
   - pinch_distance 缩放不依赖 PINCH 分类名
   - hand_lost_timeout 只触发一次安全释放

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

本项目第一版手势设计目标不是"手势越多越好"，而是：

```text
PPT 演示闭环稳定
SolidWorks 能旋转、平移、缩放
模式切换简单可靠（ILoveYou 滑动）
任何时候都能安全退出和释放按键
减少误识别风险（废弃 Thumb_Up / Thumb_Down）
```

后续开发必须优先保证安全性、稳定性和可测试性。

**第一版简化重点**：

1. 只保留 6 个稳定手势：Closed_Fist、Open_Palm、Pointing_Up、Victory、ILoveYou、PINCH
2. 使用 ILoveYou 滑动切换模式，避免使用容易误识别的 Thumb_Up / Thumb_Down
3. 禁用 mouse / mouse_scroll 模式，降低演示复杂度
4. 删除手势擦除功能，简化 PPT 画笔模式
5. 删除 SolidWorks 拟合视图和等轴测视图，降低误触风险
