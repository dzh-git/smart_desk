# PROJECT_PLAN.md

# SmartDesk Gesture Controller 项目修改计划书

## 1. 文档目的

本文档用于规划 SmartDesk Gesture Controller 后续修改的阶段、任务边界、执行顺序和验收目标。

后续使用 Codex、Claude Code 或人工修改代码时，必须先阅读以下规范文档：

```text
docs/GESTURE_MAPPING_SPEC.md
docs/STATE_MACHINE_SPEC.md
docs/ACTION_INTENT_SPEC.md
docs/CONFIG_SPEC.md
docs/TEST_ACCEPTANCE_SPEC.md
```

本文档不重新定义手势、不重新定义状态机、不重新定义接口，只负责把任务拆成可执行阶段。

---

## 2. 当前项目状态

当前项目已经具备以下基础能力：

```text
1. 使用摄像头采集图像
2. 使用 MediaPipe 检测手部关键点
3. 使用规则启发式方法判断基础手势
4. 通过状态机将手势转换为动作意图
5. 通过 PyAutoGUI 控制鼠标和键盘
6. 支持 PPT 基础翻页
7. 支持基础鼠标移动和点击
8. 支持调试窗口
9. 支持 dry-run 模式
10. 支持全局热键暂停和退出
```

当前主要问题：

```text
1. 手势映射还没有完全冻结
2. 状态机模式不够清晰
3. PPT 演示模式不完整
4. SolidWorks 模式有预留但未真正实现
5. 鼠标模式缺少右键、滚轮、拖拽等完整体验
6. release_all 需要进一步强化
7. 配置参数需要统一管理
8. 测试验收标准需要补齐
```

---

## 3. 总体目标

本轮修改目标不是追求所有功能一次性做满，而是完成一个稳定、可演示、可继续扩展的第一版。

第一版目标：

```text
PPT：可以启动、翻页、画笔、擦除、退出
鼠标：可以移动、点击、拖拽、滚动、退出
SolidWorks：可以旋转、平移、缩放、适配视图、退出
安全：任何时候可以暂停、退出、释放鼠标和按键
调试：能看到当前模式、手势、FPS、动作日志
测试：状态机和动作层可用 FakeDriver 自动化测试
```

---

## 4. 开发原则

### 4.1 先规范，后代码

必须先完成并确认以下文档：

```text
1. GESTURE_MAPPING_SPEC.md
2. STATE_MACHINE_SPEC.md
3. ACTION_INTENT_SPEC.md
4. CONFIG_SPEC.md
5. TEST_ACCEPTANCE_SPEC.md
```

再开始正式改代码。

---

### 4.2 不允许 Codex 自由发挥手势逻辑

后续给 Codex 的提示词必须明确：

```text
严格按照 docs/GESTURE_MAPPING_SPEC.md 和 docs/STATE_MACHINE_SPEC.md 实现。
不要自行新增手势。
不要改变手势含义。
不要改变状态机模式名称。
不要绕过 ActionIntent 直接调用 PyAutoGUI。
```

---

### 4.3 安全优先

所有功能实现必须满足：

```text
Closed_Fist 可以退出当前模式
手丢失超时后 release_all
Ctrl+Alt+G 可以暂停/恢复
Ctrl+Alt+Q 可以紧急退出
异常退出前 release_all
```

如果安全机制和功能体验冲突，优先保证安全机制。

---

### 4.4 每个阶段必须可验收

每个阶段完成后必须：

```text
1. 运行相关单元测试
2. 运行 dry-run 端到端测试
3. 更新对应文档
4. 记录已知问题
```

---

## 5. 阶段划分

项目修改分为 7 个阶段：

```text
阶段 0：规范冻结
阶段 1：动作意图与配置层整理
阶段 2：状态机重构
阶段 3：PPT 演示模式闭环
阶段 4：鼠标模式增强
阶段 5：SolidWorks 最小闭环
阶段 6：测试、标定与部署
```

---

## 6. 阶段 0：规范冻结

### 6.1 目标

冻结后续代码实现的规则依据。

### 6.2 任务

```text
1. 新增 docs/GESTURE_MAPPING_SPEC.md
2. 新增 docs/STATE_MACHINE_SPEC.md
3. 新增 docs/ACTION_INTENT_SPEC.md
4. 新增 docs/CONFIG_SPEC.md
5. 新增 docs/TEST_ACCEPTANCE_SPEC.md
6. 更新 README.md 中的文档索引
```

### 6.3 不做事项

```text
不改核心代码
不新增功能
不调整手势阈值
不修改 PyAutoGUI 动作
```

### 6.4 验收标准

```text
docs/ 目录中存在上述 5 份规范文档
README.md 能指向这些文档
文档中的模式名称、手势名称、动作名称保持一致
```

---

## 7. 阶段 1：动作意图与配置层整理

### 7.1 目标

先把状态机和动作层之间的接口整理清楚，避免后续功能直接耦合 PyAutoGUI。

### 7.2 涉及文件

```text
hands/gesture_state.py
hands/gesture_actions.py
hands/gesture_config.py
tests/test_gesture_actions.py
tests/test_gesture_state.py
```

### 7.3 任务 1.1：统一 ActionIntent 数据结构

实现或整理：

```text
ActionIntent(type="press", key="f5")
ActionIntent(type="hotkey", keys=["ctrl", "p"])
ActionIntent(type="mouse_down", button="left")
ActionIntent(type="mouse_up", button="left")
ActionIntent(type="move_to", x=..., y=...)
ActionIntent(type="move_rel", dx=..., dy=...)
ActionIntent(type="scroll", amount=...)
ActionIntent(type="key_down", key="shift")
ActionIntent(type="key_up", key="shift")
ActionIntent(type="release_all")
ActionIntent(type="status", text="...")
ActionIntent(type="noop")
```

要求：

```text
状态机只输出 ActionIntent
动作层统一执行 ActionIntent
单元测试使用 FakeDriver
```

### 7.4 任务 1.2：完善 release_all

`release_all` 必须释放：

```text
left mouse
middle mouse
right mouse
shift
ctrl
alt
```

要求：

```text
release_all 可以重复调用
没有任何按键按下时调用也不能报错
程序退出和异常时必须调用
```

### 7.5 任务 1.3：整理配置参数

将以下参数集中到 `gesture_config.py`：

```text
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

禁止在业务代码中继续写魔法数字。

### 7.6 验收标准

```text
ActionIntent 类型完整
FakeDriver 可以记录动作
release_all 单元测试通过
配置参数集中管理
pytest tests/test_gesture_actions.py 通过
```

---

## 8. 阶段 2：状态机重构

### 8.1 目标

按照 `STATE_MACHINE_SPEC.md` 重构状态机，使模式边界清晰。

### 8.2 涉及文件

```text
hands/gesture_state.py
tests/test_gesture_state.py
```

### 8.3 需要支持的模式

```text
MODE_STANDBY
MODE_PRESENTATION
MODE_PRESENTATION_PEN
MODE_MOUSE
MODE_MOUSE_SCROLL
MODE_SOLIDWORKS
MODE_PAUSED
```

### 8.4 任务 2.1：实现状态切换骨架

实现以下切换：

```text
standby + Thumb_Up HOLD -> presentation
standby + Pointing_Up HOLD -> mouse
standby + ILoveYou HOLD -> solidworks
presentation + Victory HOLD -> presentation_pen
presentation + Closed_Fist HOLD -> standby
presentation_pen + Thumb_Up HOLD -> presentation
mouse + Victory HOLD -> mouse_scroll
mouse + Closed_Fist HOLD -> standby
solidworks + Closed_Fist HOLD -> standby
任意模式 + Ctrl+Alt+G -> paused
paused + Ctrl+Alt+G -> standby
```

### 8.5 任务 2.2：实现 HOLD 机制

要求：

```text
同一手势持续超过指定时间才触发
手势变化后重新计时
手丢失后重新计时
触发后进入 cooldown
```

### 8.6 任务 2.3：实现动态手势窗口

用于 PPT 左右翻页：

```text
Open_Palm + dx > swipe_threshold_x -> SWIPE_RIGHT
Open_Palm + dx < -swipe_threshold_x -> SWIPE_LEFT
abs(dy) 必须小于 swipe_threshold_y_limit
```

### 8.7 任务 2.4：实现手丢失处理

要求：

```text
短暂 None 不切换模式
超过 hand_lost_timeout 后 release_all
清除连续动作状态
```

### 8.8 验收标准

```text
状态机单元测试覆盖所有模式
Closed_Fist 退出路径全部包含 release_all
cooldown 内不会重复触发离散动作
pytest tests/test_gesture_state.py 通过
```

---

## 9. 阶段 3：PPT 演示模式闭环

### 9.1 目标

完成 PPT 演示的第一版完整闭环。

### 9.2 涉及文件

```text
hands/gesture_state.py
hands/gesture_actions.py
hands/gesture_config.py
tests/test_gesture_state.py
tests/test_gesture_actions.py
```

### 9.3 功能范围

```text
Thumb_Up 保持 1.5 秒：启动演示 F5
Open_Palm 向右挥：下一页
Open_Palm 向左挥：上一页
Victory 保持 0.5 秒：进入画笔 Ctrl+P
Pointing_Up：画笔移动
PINCH：画线
Thumb_Down：擦除 E
Thumb_Up：取消画笔 Ctrl+A
Closed_Fist：退出演示 Esc + release_all
```

### 9.4 不做事项

```text
不实现白屏 W
不实现复杂激光笔模式
不做 PPT 内容编辑
不做自动识别 PowerPoint 文件
```

### 9.5 验收标准

```text
PPT 可以用手势启动
左右翻页准确率至少 90%
一次挥手不会连续翻多页
画笔可以进入、画线、擦除、退出
握拳可以退出放映
退出后没有鼠标左键卡住
```

---

## 10. 阶段 4：鼠标模式增强

### 10.1 目标

让鼠标模式成为可用的通用手势控制模式。

### 10.2 功能范围

```text
Pointing_Up：鼠标移动
PINCH 短按：左键单击
PINCH 长按：拖拽
Victory 保持：进入滚轮模式
Victory 上下移动：滚轮
Thumb_Down 保持：右键
Closed_Fist：退出鼠标模式
```

### 10.3 重点问题

```text
鼠标移动要平滑
PINCH 点击和拖拽要区分
滚轮必须在 mouse_scroll 子模式中触发
退出时必须释放左键
```

### 10.4 不做事项

```text
不做双击
不做多指复杂组合
不做多屏幕高级映射
```

### 10.5 验收标准

```text
鼠标能稳定移动
可以左键点击
可以拖拽并释放
可以滚轮
可以右键
握拳退出后不再控制鼠标
```

---

## 11. 阶段 5：SolidWorks 最小闭环

### 11.1 目标

实现 SolidWorks 查看模式的最小可用版本。

### 11.2 功能范围

```text
ILoveYou 保持 1.5 秒：进入 SolidWorks 模式
Open_Palm + 移动：中键拖动旋转
Victory + 移动：Shift + 中键拖动平移
PINCH 距离变化：滚轮缩放
Thumb_Up：缩放全部拟合 F
ILoveYou：等轴测 Ctrl+7
Closed_Fist：退出并 release_all
```

### 11.3 关键实现要求

旋转模型：

```text
Open_Palm 开始移动 -> mouse_down(middle)
Open_Palm 持续移动 -> move_rel(dx, dy)
Open_Palm 结束 -> mouse_up(middle)
```

平移模型：

```text
Victory 开始移动 -> key_down(shift) + mouse_down(middle)
Victory 持续移动 -> move_rel(dx, dy)
Victory 结束 -> mouse_up(middle) + key_up(shift)
```

缩放模型：

```text
PINCH 距离变化超过死区 -> scroll(amount)
```

### 11.4 不做事项

```text
不做建模
不做特征编辑
不做完整装配操作
不做所有视图方向快捷键
不做 SolidWorks API 集成
```

第一版只通过鼠标和键盘模拟控制 SolidWorks。

### 11.5 验收标准

```text
模型可以旋转
模型可以平移
模型可以缩放
可以缩放全部拟合
可以退出模式
退出后中键和 Shift 不会卡住
```

---

## 12. 阶段 6：测试、标定与部署

### 12.1 目标

完成项目可演示前的稳定性测试和现场部署准备。

### 12.2 已完成内容

```text
1. 补充现场标定说明（DEPLOYMENT_RUNBOOK §11）
2. 补充真实端到端测试清单（TEST_ACCEPTANCE_SPEC §10a）
3. 完善启动脚本 start_gesture.bat（增加模型文件检查）
4. 新增 dry-run / presentation / mouse / solidworks 启动脚本
5. 确认 dry-run 模式适合现场标定（显示 mode/gesture/stable/action/FPS/pinch/drag 状态）
6. 模型文件缺失时给出明确错误提示并退出
7. README 与 docs 和当前代码行为一致
8. 补充常见问题 FAQ
9. 不新增手势功能
10. 不破坏阶段 1–5 功能
```

### 12.3 测试任务

```text
运行所有 pytest 测试
运行 dry-run 端到端测试
运行 PPT 真实端到端测试
运行鼠标模式真实端到端测试
运行 SolidWorks 真实端到端测试
连续运行 60 分钟稳定性测试
```

### 12.4 标定任务

根据现场环境调整：

```text
摄像头位置
光照
pinch_threshold
swipe_threshold_x
mouse_smoothing
mouse_speed
scroll_threshold_y
solidworks_drag_sensitivity
solidworks_zoom_sensitivity
hand_lost_timeout
```

### 12.5 部署任务

```text
确认 hand_landmarker.task 本地存在（程序启动时自动检查）
确认无网络环境也能启动
确认 start_gesture.bat 可用
确认 start_gesture_dry_run.bat 可用
确认 --no-mouse 可用
确认 Ctrl+Alt+G / Ctrl+Alt+Q 可用
```

### 12.6 验收标准

```text
PPT、鼠标、SolidWorks 三个模式均可演示
安全机制全部通过
连续运行 1 小时无崩溃
无鼠标键或键盘键卡住
全部 pytest 通过
README 与 docs 和代码行为一致
模型文件缺失时有明确提示
参数标定说明完整
```

---

## 13. 推荐 Codex 执行顺序

给 Codex 分任务时，建议按下面顺序：

```text
Task 1：新增/整理文档，不改代码
Task 2：重构 ActionIntent 与 FakeDriver
Task 3：整理 gesture_config.py 参数
Task 4：重构状态机模式与 HOLD/cooldown
Task 5：修复 release_all 与异常退出
Task 6：实现 PPT 演示闭环
Task 7：实现鼠标模式增强
Task 8：实现 SolidWorks 最小闭环
Task 9：补充测试
Task 10：更新 README 和部署说明
```

不要一次性让 Codex 完成全部任务。

---

## 14. Codex 执行提示词模板

后续可以使用以下模板：

```text
请阅读以下文档后再修改代码：

docs/GESTURE_MAPPING_SPEC.md
docs/STATE_MACHINE_SPEC.md
docs/ACTION_INTENT_SPEC.md
docs/CONFIG_SPEC.md
docs/TEST_ACCEPTANCE_SPEC.md
docs/PROJECT_PLAN.md

本次只执行【填写当前任务名称】，不要实现其他阶段内容。

限制：
1. 不要自行新增手势。
2. 不要改变已定义的模式名称。
3. 不要绕过 ActionIntent 直接调用 PyAutoGUI。
4. 不要破坏 dry-run 模式。
5. 不要破坏 Ctrl+Alt+G / Ctrl+Alt+Q。
6. 所有退出路径必须 release_all。
7. 修改后补充或更新对应测试。
8. 保持 UTF-8 编码。
```

---

## 15. 风险与应对

### 15.1 手势误识别

风险：

```text
自然抬手被识别为 Open_Palm
Thumb_Up / Thumb_Down 受角度影响
PINCH 阈值因距离摄像头远近变化
```

应对：

```text
模式隔离
HOLD 确认
cooldown
阈值配置化
dry-run 调试
```

---

### 15.2 鼠标或按键卡住

风险：

```text
画笔左键未释放
SolidWorks 中键未释放
Shift 键未释放
```

应对：

```text
所有退出路径 release_all
手丢失 release_all
暂停 release_all
异常退出 release_all
release_all 幂等
```

---

### 15.3 现场无网络

风险：

```text
MediaPipe 模型首次运行需要下载
```

应对：

```text
模型文件随项目一起放置
启动前检查模型文件
无模型时给出明确提示
```

---

### 15.4 性能不足

风险：

```text
FPS 低
鼠标延迟明显
CPU 占用高
```

应对：

```text
降低摄像头分辨率
减少 debug 绘制
降低处理帧率
使用 MediaPipe VIDEO 模式
调整 smoothing 和 sensitivity
```

---

## 16. 最终完成定义

本轮项目修改完成的判定标准：

```text
1. 文档完整
2. 手势映射冻结
3. 状态机清晰
4. ActionIntent 解耦
5. 配置参数集中
6. PPT 模式可完整演示
7. 鼠标模式可基本使用
8. SolidWorks 模式可查看模型
9. 安全机制可靠
10. 测试和部署说明完整
```

---

## 17. 结论

本项目后续修改的核心不是“增加更多手势”，而是：

```text
先让状态机稳定
再让动作层安全
再让 PPT 闭环可用
再扩展鼠标和 SolidWorks
最后做测试、标定和部署
```

开发过程中必须避免功能堆叠，优先保证稳定、安全和可验收。
