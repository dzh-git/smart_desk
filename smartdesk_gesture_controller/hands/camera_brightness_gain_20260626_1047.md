# 摄像头亮度/增益参数可调化

## 目标
在摄像头设置部分添加亮度和增益的代码，并将可调参数放到 `gesture_config.py` 中。

## 修改内容

### gesture_config.py
在 Camera 配置区新增：

```python
camera_brightness: int = 60         # CAP_PROP_BRIGHTNESS (range 0~60 on this camera)
camera_gain: int = 100              # CAP_PROP_GAIN (range 0~100 on this camera)
```

### gesture_controller.py `_open_camera()`
在曝光设置之后、读取回显之前，加入：

```python
# Adjust brightness and gain (driver-dependent ranges).
cap.set(cv2.CAP_PROP_BRIGHTNESS, self.config.camera_brightness)
cap.set(cv2.CAP_PROP_GAIN, self.config.camera_gain)
```

并读取回显：

```python
actual_brightness = cap.get(cv2.CAP_PROP_BRIGHTNESS)
actual_gain = cap.get(cv2.CAP_PROP_GAIN)
```

日志格式同步扩展，输出请求值和实际值：

```
camera exposure: requested auto=%s exp=%s brightness=%s gain=%s | actual auto=%s exp=%s brightness=%s gain=%s fps=%s
```

## 结论
亮度、增益已参数化并集中到 `gesture_config.py`，默认值为亮度 60、增益 100，与示例代码一致。
