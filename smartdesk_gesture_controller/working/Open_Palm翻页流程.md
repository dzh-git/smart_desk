Open_Palm 手势控制 PPT 翻页 —— 全流程说明
====================================================

适用模式：presentation（PPT 演示模式）
触发手势：Open_Palm（张开手掌，五指分开）
动作效果：手掌向右挥 → 下一页；向左挥 → 上一页


一、流程总览（从摄像头到按键）

摄像头帧
  → MediaPipe 检测手部关键点
  → GestureRecognizer 分类手势（raw_gesture）
  → GestureIntentTracker 稳定确认（stable_gesture）
  → 创建翻页尝试（Attempt，ARMED 状态）
  → 跟踪手掌轨迹（TRACKING 状态）
  → 位移达标，提交事件（ControlEvent）
  → GestureState 处理事件，生成动作意图（ActionIntent）
  → 冷却检查（cooldown）
  → ActionLayer 执行 pyautogui.press("right") / press("left")
  → PPT 接收方向键，翻页


二、各阶段详细说明

1. 手势分类（每帧）
   - MediaPipe 检测到手后，GestureRecognizer 输出 raw_gesture
   - 可能值：Open_Palm / Closed_Fist / Pointing_Up / Victory / ILoveYou / None
   - 同时输出 confidence（0.0~1.0）和 source（recognizer / rule）

2. 稳定确认（多帧去抖）
   - GestureIntentTracker._update_candidate() 维护一个滑动窗口
   - 窗口大小：gesture_enter_window_frames（默认 5 帧）
   - 在窗口内，同一手势出现次数 >= gesture_enter_frames（默认 4 帧）
     且 recognizer 结果的 confidence >= gesture_enter_confidence（默认 0.65）
   - 满足条件后，stable_gesture 更新为 "Open_Palm"
   - 在此之前，raw_gesture 抖动不会影响翻页逻辑

3. 创建翻页尝试（ARMED）
   - 条件：模式为 presentation，stable_gesture == "Open_Palm"
           当前没有活跃的 Attempt / Session / Zoom
   - 调用 _begin_attempt(INTENT_PAGE_SWIPE, ...)
   - 记录 start_position（当前 palm_xy 归一化坐标）
   - Attempt 状态：AP_ARMED

4. 轨迹跟踪（ARMED → TRACKING）
   - 每帧更新 palm_xy（经过低通平滑）
   - 一旦轨迹有更新，状态从 ARMED 变为 TRACKING
   - 轨迹记录在 attempt.trajectory 列表中

5. 提交检查（TRACKING → COMMITTED）
   同时满足以下条件时提交：
   a. 水平位移 |dx| >= swipe_threshold_x（默认 0.22，归一化坐标）
   b. 垂直位移 |dy| < swipe_threshold_y_limit（默认 0.15，防止上下抖动）
   c. 挥手持续时间 dt >= min_motion_duration（默认 0.05 秒）
   d. 方向一致性：最近 direction_consistency_frames 帧的方向必须一致
   e. 位移方向：dx > 0 → page_swipe_right（下一页）
                    dx < 0 → page_swipe_left（上一页）

6. 事件发射
   - 提交后发出 ControlEvent：
     { type: "page_swipe_right", attempt_id, dx, dy, position, reason: "committed" }
     或 { type: "page_swipe_left", ... }

7. 状态机处理（GestureState）
   - GestureState._handle_events() 收到 ControlEvent
   - 调用 _on_page_swipe_right(now) 或 _on_page_swipe_left(now)
   - 先检查冷却：_cooldown_ok(COOLDOWN_PAGE_TURN, now)
   - 冷却通过后，生成 ActionIntent：
     [ActionIntent.press("right")]  或  [ActionIntent.press("left")]
   - 设置冷却截止时间：_set_cooldown(COOLDOWN_PAGE_TURN, page_turn_cooldown, now)

8. 动作执行（ActionLayer）
   - gesture_actions.py 的 execute() 收到 ActionIntent 列表
   - 对 press 类型：调用 pyautogui.press(key)
   - pyautogui.press("right") → 模拟按下右方向键 → PPT 下一页
   - pyautogui.press("left") → 模拟按下左方向键 → PPT 上一页
   - 每次 press 是"按下即释放"，等价于一次短按

9. 尝试释放（RELEASED）
   - 提交后，当手掌位置回到起点附近（|dx| < threshold * 0.5）
     或超时，Attempt 进入 RELEASED，然后清空
   - 下次挥手会创建新的 Attempt


三、关键参数（在 gesture_config.py 中配置）

swipe_threshold_x       水平位移阈值（默认 0.22）
swipe_threshold_y_limit 垂直位移上限（默认 0.15）
min_motion_duration    最短挥手时间（默认 0.05 秒）
direction_consistency_frames  方向一致所需帧数（默认 3）
page_turn_cooldown    翻页冷却时间（默认 0.8 秒，防止一次挥手翻多页）
gesture_enter_window_frames  稳定确认窗口（默认 5 帧）
gesture_enter_frames   窗口内所需最少帧数（默认 4 帧）
gesture_enter_confidence    recognizer 置信度阈值（默认 0.65）
landmark_smoothing      手掌坐标低通平滑系数（默认 0.3）


四、调试要点

- 翻页不触发？
  1. 确认模式是 presentation（日志 mode 字段）
  2. 确认 stable_gesture 是否为 "Open_Palm"
  3. 确认 intent_state 是否从 armed → tracking → committed
  4. 检查 palm_x 变化是否超过 swipe_threshold_x
  5. 检查 generated_events 中是否有 page_swipe_right/left

- 一次挥手翻多页？
  → 调大 page_turn_cooldown（默认 0.8，可适当加大到 1.0~1.5）

- 挥手不灵敏？
  → 调小 swipe_threshold_x（默认 0.22，可降到 0.15~0.18）
  → 调小 min_motion_duration

- 误触发（不挥手也翻页）？
  → 调大 swipe_threshold_x
  → 调大 direction_consistency_frames
