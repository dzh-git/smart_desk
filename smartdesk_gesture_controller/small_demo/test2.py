import cv2
import mediapipe as mp
import mediapipe.tasks
from mediapipe.tasks.python.vision import (
    HandLandmarker,
    HandLandmarkerOptions,
    RunningMode,
    drawing_utils,
    HandLandmarksConnections,
)
import pyautogui
import math
import time
import numpy as np
import os

from collections import deque

# 存储最近 20 个点的坐标
pts = deque(maxlen=20)

# --- 配置部分 (已优化) ---
pyautogui.FAILSAFE = False
SCREEN_W, SCREEN_H = pyautogui.size()
CAM_W, CAM_H = 640, 320

# 翻页挥动检测的冷却时间（秒）
WAVE_COOLDOWN = 1
# 翻页挥动触发的最小像素阈值
WAVE_THRESHOLD = 10

# 拖动模式激活冷却时间 (防止模式闪烁)
DRAG_COOLDOWN = 0.3  # 0.3秒的稳定时间

# 握拳退出模式的冷却时间 (防止连续触发 Esc)
FIST_EXIT_COOLDOWN = 1.0  # 增加冷却时间以确保 Esc 键触发准确

# 鼠标移动平滑系数
SMOOTHENING = 1
# 鼠标模式下的操作频率限制 (每秒20次)
MOUSE_FPS = 20
MOUSE_FRAME_INTERVAL = 1 / MOUSE_FPS

# --- 单指鼠标模式参数 ---
SINGLE_COOLDOWN = 0.25      # 单指模式激活稳定时间(防止抖动切换)
CLICK_COOLDOWN = 0.35       # 单击防抖(秒)

# --- 捏合点击参数（拇指4 + 食指8）---
PINCH_CLICK_DISTANCE = 35   # 像素阈值（30~45 可按需调整）

# --- 初始化 MediaPipe HandLandmarker (Task API) ---
_MODEL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hand_landmarker.task")
_landmarker_options = HandLandmarkerOptions(
    base_options=mediapipe.tasks.BaseOptions(model_asset_path=_MODEL_PATH),
    running_mode=RunningMode.IMAGE,
    num_hands=1,
    min_hand_detection_confidence=0.7,
    min_tracking_confidence=0.5,
)
landmarker = HandLandmarker.create_from_options(_landmarker_options)

# --- 全局状态变量 ---
prev_time = 0
prev_hand_x = None
cooldown_wave = 0
cooldown_fist = 0.0

# --- 鼠标/拖动模式状态 ---
is_left_mouse_down = False
drag_mode_start_time = 0.0
last_mouse_time = 0
plocX, plocY = 0, 0
clocX, clocY = 0, 0

# --- 单指鼠标模式状态 ---
is_single_mouse_mode = False
single_mode_start_time = 0.0
last_click_time = 0.0
prev_pinch_state = False  # 上一帧是否处于捏合状态


LANDMARK_SPEC = drawing_utils.DrawingSpec(
    color=(255, 0, 255),
    thickness=2,
    circle_radius=2
)


def get_landmarks_list(img_rgb, img_shape):
    """运行 HandLandmarker 并将归一化坐标转换为像素坐标列表"""
    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=img_rgb)
    result = landmarker.detect(mp_image)

    lm_list = []
    raw_landmarks = None
    if result.hand_landmarks:
        raw_landmarks = result.hand_landmarks
        hand_lms = result.hand_landmarks[0]
        h, w = img_shape[:2]
        for idx, lm in enumerate(hand_lms):
            cx, cy = int(lm.x * w), int(lm.y * h)
            lm_list.append([idx, cx, cy])
    return lm_list, raw_landmarks


def is_hand_open(lm_list):
    """判断手掌是否张开（所有手指伸直）。"""
    if len(lm_list) < 21:
        return False

    fingers_straight = []
    is_thumb_straight = lm_list[4][2] < lm_list[2][2]
    fingers_straight.append(is_thumb_straight)

    tips = [8, 12, 16, 20]
    roots = [5, 9, 13, 17]

    for i in range(4):
        fingers_straight.append(lm_list[tips[i]][2] < lm_list[roots[i]][2])

    return all(fingers_straight)


def get_finger_bent_status(lm_list):
    """获取食指、中指、无名指、小指的弯曲状态 (True=弯曲)"""
    if len(lm_list) < 21:
        return [False] * 4

    fingers_bent = []
    tips = [8, 12, 16, 20]
    roots = [5, 9, 13, 17]

    for i in range(4):
        fingers_bent.append(lm_list[tips[i]][2] > lm_list[roots[i]][2])
    return fingers_bent


def main():
    global prev_time, prev_hand_x
    global cooldown_wave, cooldown_fist
    global is_left_mouse_down, last_mouse_time, drag_mode_start_time
    global plocX, plocY, clocX, clocY

    global is_single_mouse_mode, single_mode_start_time
    global last_click_time, prev_pinch_state

    cap = cv2.VideoCapture(0)
    cap.set(3, CAM_W)
    cap.set(4, CAM_H)

    # <<< 新增：置顶状态标志 >>>
    window_set = False
    window_name = "Gesture Control System"

    print("系统已启动。当前支持："
          "1. 张开手掌挥动翻页； "
          "2. 双指拖动/画笔模式（握拳 Ctrl+P 退出）； "
          "3. 单指鼠标模式（用手掌中心移动鼠标，拇指+食指捏合=左键单击，握拳退出）。"
          "按 'q' 退出。")

    while True:
        success, img = cap.read()
        if not success:
            break

        # 1. 图像处理
        img = cv2.flip(img, 1)
        img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

        # 2. 手势检测 (Task API)
        lm_list, raw_hand_landmarks = get_landmarks_list(img_rgb, img.shape)

        status_text = "Status: No Hand Detected"
        current_time = time.time()

        x_map_start, x_map_end = 50, CAM_W - 50
        y_map_start, y_map_end = 50, CAM_H - 50

        # --- 核心逻辑 ---
        if len(lm_list) != 0:

            # 手掌中心（更稳）：用 0(腕) 和 9(中指掌指关节)的中点
            palm_x, palm_y = (lm_list[0][1] + lm_list[9][1]) // 2, (lm_list[0][2] + lm_list[9][2]) // 2
            cx, cy = palm_x, palm_y  # 统一用于UI绘制等

            fingers_bent = get_finger_bent_status(lm_list)

            is_index_straight = not fingers_bent[0]
            is_middle_straight = not fingers_bent[1]
            is_ring_bent = fingers_bent[2]
            is_pinky_bent = fingers_bent[3]

            is_fist = fingers_bent[0] and fingers_bent[1] and fingers_bent[2] and fingers_bent[3]

            is_drag_mode_gesture = (
                is_index_straight and
                is_middle_straight and
                is_ring_bent and
                is_pinky_bent
            )

            # --- 单指鼠标模式手势（食指直，其余弯） ---
            is_single_mode_gesture = (
                is_index_straight and
                (not is_middle_straight) and
                is_ring_bent and
                is_pinky_bent
            )

            # ----------------------------------------------------------
            # 模式激活状态追踪 (稳定判定) - 拖动模式
            # ----------------------------------------------------------
            if is_drag_mode_gesture:
                if drag_mode_start_time == 0.0:
                    drag_mode_start_time = current_time
                mode_is_stable = (current_time - drag_mode_start_time) > DRAG_COOLDOWN
            else:
                drag_mode_start_time = 0.0
                mode_is_stable = False

            # ----------------------------------------------------------
            # 模式激活状态追踪 (稳定判定) - 单指模式
            # ----------------------------------------------------------
            if is_single_mode_gesture:
                if single_mode_start_time == 0.0:
                    single_mode_start_time = current_time
                single_mode_is_stable = (current_time - single_mode_start_time) > SINGLE_COOLDOWN
            else:
                single_mode_start_time = 0.0
                single_mode_is_stable = False

            # ==========================================================
            # 功能 4: 虚拟触控板/拖动模式
            # ==========================================================
            if is_left_mouse_down or mode_is_stable:

                # --- 模式退出：握拳手势，触发 Ctrl+P + MouseUp ---
                if is_left_mouse_down and is_fist and (current_time - cooldown_fist > FIST_EXIT_COOLDOWN):

                    pyautogui.mouseUp(plocX, plocY, button='left')
                    pyautogui.hotkey('ctrl', 'p')

                    plocX, plocY = 0, 0
                    clocX, clocY = 0, 0

                    is_left_mouse_down = False
                    cooldown_fist = current_time
                    drag_mode_start_time = 0.0

                    print("[ACTION] DRAG MODE EXITED: FIST -> Mouse Up + Ctrl+P")
                    status_text = "Action: FIST EXIT - Pen Tool Off"

                else:
                    status_text = "Mode: DRAG/PEN ACTIVE"

                    if current_time - last_mouse_time > MOUSE_FRAME_INTERVAL:

                        x8, y8 = lm_list[8][1], lm_list[8][2]
                        x12, y12 = lm_list[12][1], lm_list[12][2]
                        avg_x = (x8 + x12) // 2
                        avg_y = (y8 + y12) // 2

                        x3 = np.interp(avg_x, (x_map_start, x_map_end), (0, SCREEN_W))
                        y3 = np.interp(avg_y, (y_map_start, y_map_end), (0, SCREEN_H))

                        clocX = plocX + (x3 - plocX) / SMOOTHENING
                        clocY = plocY + (y3 - plocY) / SMOOTHENING

                        pyautogui.moveTo(clocX, clocY)
                        plocX, plocY = clocX, clocY
                        last_mouse_time = current_time

                    if mode_is_stable and not is_left_mouse_down:
                        pyautogui.hotkey('ctrl', 'p')
                        pyautogui.mouseDown(clocX, clocY, button='left')
                        is_left_mouse_down = True
                        print("[ACTION] DRAG MODE ENTERED: Ctrl+P Pressed & Mouse Down")

                    cv2.rectangle(img, (x_map_start, y_map_start), (x_map_end, y_map_end), (0, 255, 255), 2)
                    prev_hand_x = None

                    # 画笔模式优先：退出单指模式，避免抢控制
                    if is_single_mouse_mode:
                        is_single_mouse_mode = False
                        single_mode_start_time = 0.0
                        prev_pinch_state = False
                        print("[ACTION] SINGLE MOUSE MODE EXITED: Drag/Pen Took Over")

            # ==========================================================
            # 非画笔模式逻辑
            # ==========================================================
            else:
                if is_left_mouse_down:
                    pyautogui.mouseUp(plocX, plocY, button='left')
                    is_left_mouse_down = False
                    print("[ACTION] DRAG MODE EXITED: Mouse Up (Fallthrough)")

                # ==========================================================
                # 单指鼠标操控模式（用手掌中心移动；捏合=左键单击）
                # ==========================================================
                if is_single_mouse_mode or single_mode_is_stable:

                    # 退出：握拳
                    if is_single_mouse_mode and is_fist:
                        is_single_mouse_mode = False
                        single_mode_start_time = 0.0
                        prev_pinch_state = False
                        status_text = "Action: SINGLE MOUSE EXIT (FIST)"
                        print("[ACTION] SINGLE MOUSE MODE EXITED: FIST")
                        prev_hand_x = None

                    else:
                        status_text = "Mode: SINGLE PALM MOUSE"
                        prev_hand_x = None  # 防止与挥动翻页冲突

                        # 进入模式（稳定后）
                        if single_mode_is_stable and not is_single_mouse_mode:
                            is_single_mouse_mode = True
                            plocX, plocY = 0, 0
                            clocX, clocY = 0, 0
                            last_mouse_time = 0
                            prev_pinch_state = False
                            print("[ACTION] SINGLE MOUSE MODE ENTERED")

                        # 鼠标移动：用手掌中心(更稳)做映射
                        if current_time - last_mouse_time > MOUSE_FRAME_INTERVAL:
                            x3 = np.interp(palm_x, (x_map_start, x_map_end), (0, SCREEN_W))
                            y3 = np.interp(palm_y, (y_map_start, y_map_end), (0, SCREEN_H))

                            clocX = plocX + (x3 - plocX) / SMOOTHENING
                            clocY = plocY + (y3 - plocY) / SMOOTHENING

                            pyautogui.moveTo(clocX, clocY)
                            plocX, plocY = clocX, clocY
                            last_mouse_time = current_time

                        # -------------------------------
                        # 捏合点击：拇指(4) + 食指(8)（逻辑不变）
                        # -------------------------------
                        x4, y4 = lm_list[4][1], lm_list[4][2]  # 拇指指尖
                        x8, y8 = lm_list[8][1], lm_list[8][2]  # 食指指尖
                        pinch_distance = math.hypot(x8 - x4, y8 - y4)
                        is_pinched = pinch_distance < PINCH_CLICK_DISTANCE

                        # 边沿触发：未捏合 -> 捏合
                        if (not prev_pinch_state) and is_pinched:
                            if current_time - last_click_time > CLICK_COOLDOWN:
                                pyautogui.click(button='left')
                                last_click_time = current_time
                                status_text = "Action: LEFT CLICK (PINCH)"
                                print("[ACTION] LEFT CLICK (PINCH)")

                        prev_pinch_state = is_pinched

                        # 可视化操控区域
                        cv2.rectangle(img, (x_map_start, y_map_start), (x_map_end, y_map_end), (255, 0, 255), 2)

                        # 可视化捏合距离（可注释掉）
                        cv2.line(img, (x4, y4), (x8, y8), (255, 0, 255), 2)
                        cv2.putText(img, f'Pinch: {int(pinch_distance)}', (10, 110),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 0, 255), 2)

                # ==========================================================
                # 原逻辑：翻页模式 (张开手掌)
                # ==========================================================
                else:
                    if is_single_mouse_mode:
                        is_single_mouse_mode = False
                        single_mode_start_time = 0.0
                        prev_pinch_state = False
                        print("[ACTION] SINGLE MOUSE MODE EXITED: Gesture Lost")

                    is_open_palm = is_hand_open(lm_list)

                    if is_open_palm:
                        status_text = "Mode: OPEN PALM (Slide Control)"

                        cv2.putText(img, "OPEN PALM", (cx - 80, cy + 80),
                                    cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)

                        if current_time - cooldown_wave > WAVE_COOLDOWN:
                            if prev_hand_x is not None:
                                diff_x = cx - prev_hand_x

                                if diff_x > WAVE_THRESHOLD:
                                    pyautogui.press('left')
                                    status_text = "Action: SLIDE PREV (LEFT) TRIGGERED"
                                    cooldown_wave = current_time
                                    print("Hand Center Moves LEFT (Slide PREV)")
                                    cv2.putText(img, "SLIDE PREV", (cx - 180, cy),
                                                cv2.FONT_HERSHEY_SIMPLEX, 3, (0, 255, 255), 5)

                                elif diff_x < -WAVE_THRESHOLD:
                                    pyautogui.press('right')
                                    status_text = "Action: SLIDE NEXT (RIGHT) TRIGGERED"
                                    cooldown_wave = current_time
                                    print("Hand Center Moves RIGHT (Slide NEXT)")
                                    cv2.putText(img, "SLIDE NEXT", (cx + 50, cy),
                                                cv2.FONT_HERSHEY_SIMPLEX, 3, (0, 255, 255), 5)

                            prev_hand_x = cx

                    else:
                        status_text = "Mode: Unrecognized / Hand Closed"
                        prev_hand_x = None

        # 如果没检测到手，重置状态
        else:
            if is_left_mouse_down:
                pyautogui.mouseUp(plocX, plocY, button='left')

                plocX, plocY = 0, 0
                clocX, clocY = 0, 0

                is_left_mouse_down = False
                drag_mode_start_time = 0.0
                print("[ACTION] DRAG MODE EXITED: Mouse Up (Hand Lost)")

            if is_single_mouse_mode:
                is_single_mouse_mode = False
                single_mode_start_time = 0.0
                prev_pinch_state = False
                print("[ACTION] SINGLE MOUSE MODE EXITED: Hand Lost")

            prev_hand_x = None

        # 3. UI 显示
        curr_fps_time = time.time()
        fps = 1 / (curr_fps_time - prev_time) if curr_fps_time - prev_time > 0 else 0
        prev_time = curr_fps_time

        cv2.putText(img, f'FPS: {int(fps)}', (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 0, 0), 2)
        cv2.putText(img, status_text, (10, 70),
                    cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)

        if raw_hand_landmarks:
            for hand_lms in raw_hand_landmarks:
                drawing_utils.draw_landmarks(
                    img,
                    hand_lms,
                    HandLandmarksConnections.HAND_CONNECTIONS,
                    landmark_drawing_spec=LANDMARK_SPEC,
                )

                # 只有在鼠标模式或拖拽模式下才记录轨迹
                if ('DRAG/PEN' in status_text) or ('SINGLE PALM MOUSE' in status_text) or mode_is_stable:
                    center = (cx, cy)
                    pts.appendleft(center)

                    for i in range(1, len(pts)):
                        if pts[i - 1] is None or pts[i] is None:
                            continue
                        thickness = int(np.sqrt(20 / float(i + 1)) * 2.5)
                        cv2.line(img, pts[i - 1], pts[i], (255, 255, 0), thickness)
                else:
                    pts.clear()

                if ('Slide Control' in status_text) or ('DRAG/PEN' in status_text) or ('SINGLE PALM MOUSE' in status_text):
                    cx2, cy2 = (lm_list[0][1] + lm_list[9][1]) // 2, (lm_list[0][2] + lm_list[9][2]) // 2
                    if 'DRAG/PEN' in status_text:
                        color = (0, 255, 255)
                    elif 'SINGLE PALM MOUSE' in status_text:
                        color = (255, 0, 255)
                    else:
                        color = (0, 165, 255)
                    cv2.circle(img, (cx2, cy2), 10, color, cv2.FILLED)

        cv2.imshow(window_name, img)

        # <<< 窗口置顶逻辑 (仅 Windows) >>>
        if os.name == 'nt' and not window_set:
            try:
                import win32gui
                import win32con

                hwnd = win32gui.FindWindow(None, window_name)

                if hwnd:
                    win32gui.SetWindowPos(hwnd, win32con.HWND_TOPMOST,
                                          0, 0, 0, 0,
                                          win32con.SWP_NOMOVE | win32con.SWP_NOSIZE)
                    print(f"[INFO] Windows 窗口 '{window_name}' 已成功置顶。")
                    window_set = True

            except ImportError:
                print("[WARN] 未安装 pywin32 库。请运行 pip install pywin32")
                window_set = True
            except Exception:
                pass

        if cv2.waitKey(1) & 0xFF == ord('q'):
            if is_left_mouse_down:
                pyautogui.mouseUp(plocX, plocY, button='left')
            break

    landmarker.close()
    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
