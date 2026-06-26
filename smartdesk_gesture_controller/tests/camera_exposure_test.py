# .venv\Scripts\python -m tests.camera_exposure_test
import cv2

import time

CAMERA_INDEX = 0
EXPOSURE = -5
WIDTH = 640
HEIGHT = 480
# 强制使用 DirectShow
cap = cv2.VideoCapture(CAMERA_INDEX, cv2.CAP_DSHOW)
if not cap.isOpened():
    raise RuntimeError("Cannot open camera")
cap.set(cv2.CAP_PROP_FRAME_WIDTH, WIDTH)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, HEIGHT)
ret1 = cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0) # Windows DirectShow
ret2 = cap.set(cv2.CAP_PROP_EXPOSURE, EXPOSURE)
time.sleep(1)
actual_auto = cap.get(cv2.CAP_PROP_AUTO_EXPOSURE)
actual_exp = cap.get(cv2.CAP_PROP_EXPOSURE)
actual_fps_cfg = cap.get(cv2.CAP_PROP_FPS)


# 提高亮度 (值域 0~60，有效)
cap.set(cv2.CAP_PROP_BRIGHTNESS, 0) 
current_brightness = cap.get(cv2.CAP_PROP_BRIGHTNESS)
print(f"Current Brightness: {current_brightness}")

# 尝试提高 Gain (值域  0~100)
cap.set(cv2.CAP_PROP_GAIN, 100) 
current_gain = cap.get(cv2.CAP_PROP_GAIN)
print(f"Current Gain: {current_gain}")

import numpy as np
def gamma_correction(image, gamma=0.5):
    # 建立查找表 (LUT)
    invGamma = 1.0 / gamma
    table = np.array([((i / 255.0) ** invGamma) * 255 for i in np.arange(0, 256)]).astype("uint8")
    # 应用查找表
    return cv2.LUT(image, table)
# gamma < 1 会让画面变亮 (0.5 提亮效果明显，0.8 提亮较柔和)
# bright_frame = gamma_correction(frame, gamma=0.5)
gamma=1
print(f"gamma Gain: {gamma}")


frame_count = 0
fps_timer = time.time()

while True:

    t0 = time.perf_counter()

    ret, frame = cap.read()

    read_ms = (time.perf_counter() - t0) * 1000

    if not ret:
        print("Frame grab failed")
        break

    frame_count += 1

    elapsed = time.time() - fps_timer

    if elapsed >= 5:

        real_fps = frame_count / elapsed

        print(
            f"[5s stats] "
            f"Real FPS={real_fps:.2f} "
            f"read_time={read_ms:.1f}ms "
            f"AUTO={actual_auto} "
            f"EXP={actual_exp}"
        )

        frame_count = 0
        fps_timer = time.time()

    frame = gamma_correction(frame, gamma=gamma)

    cv2.putText(
        frame,
        f"gamma={gamma}",
        (20, 40),
        cv2.FONT_HERSHEY_SIMPLEX,
        1,
        (0, 255, 0),
        2,
    )


    cv2.imshow("Camera Exposure Test", frame)

    key = cv2.waitKey(1)

    if key == 27:
        break

cap.release()
cv2.destroyAllWindows()