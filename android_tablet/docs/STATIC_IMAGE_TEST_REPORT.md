# 单人静态图片代理测试报告

测试日期：2026-07-24

测试性质：`STATIC_IMAGE_PROXY_DIAGNOSTIC`

注册人员：`seat-01`

标定状态：`CALIBRATION_PENDING`

## 结论

本轮使用相册按媒体时间倒序排列的前10张本人图片、10张Pexels不同身份肖像，
以及3张设备质量控制图进行离线诊断。本人样本包含5张当前相机自拍和5张App
注册/验证界面截图。

- 10张本人图片均检测成功并通过亮度、清晰度质量门槛。
- 10张网络陌生人图片均检测成功，其中8张通过质量门槛，2张因过暗被质量门槛
  拒绝。
- 3张设备质量控制图中，两张没有可用人脸并被拒绝；一张手机屏幕内的模糊人脸
  被检测到，但清晰度只有约23.28，低于40的门槛，因此被拒绝。
- 本人图片对 `normal` 模板的最低分为0.5615；合格网络陌生人最高分为0.2124。
- 本人图片对 `fillLight` 模板的最低分为0.5489；合格网络陌生人最高分为0.2163。
- 当前静态小样本在两个模板空间中分别形成约0.3490和0.3326的探索性间隔。
- 注册的 `normal` 与 `fillLight` 模板自身余弦相似度为0.9395，两个采集阶段没有
  出现明显身份漂移。

没有发现网络代理图片接近本人模板的明显高分误匹配。但这些结果不能用于设置
`PROVISIONAL` 阈值，也不能计算误接受率或误拒绝率。

## 本人图片结果

| 图片 | normal分数 | fillLight分数 | 质量 |
| --- | ---: | ---: | --- |
| `IMG_20260724_003036.jpg` | 0.7510 | 0.7544 | 通过 |
| `IMG_20260724_003039.jpg` | 0.8133 | 0.8119 | 通过 |
| `IMG_20260724_003043.jpg` | 0.8150 | 0.8143 | 通过 |
| `IMG_20260724_003049.jpg` | 0.8181 | 0.8156 | 通过 |
| `IMG_20260724_003052.jpg`（未戴眼镜） | 0.6741 | 0.6317 | 通过 |
| `Screenshot_...16-08-04...jpg` | 0.5615 | 0.5489 | 通过 |
| `Screenshot_...16-08-32...jpg` | 0.6711 | 0.6806 | 通过 |
| `Screenshot_...00-24-06...jpg` | 0.8554 | 0.8228 | 通过 |
| `Screenshot_...00-24-09...jpg` | 0.8713 | 0.8381 | 通过 |
| `Screenshot_...00-24-46...jpg` | 0.8644 | 0.8471 | 通过 |
| 最小值 | 0.5615 | 0.5489 | — |
| 平均值 | 0.7695 | 0.7565 | — |
| 最大值 | 0.8713 | 0.8471 | — |

最新5张相机自拍的 `normal` 分数范围为0.6741–0.8181，平均0.7743；
`fillLight` 分数范围为0.6317–0.8156，平均0.7656。未戴眼镜的自拍分数低于
4张戴眼镜自拍，说明当前戴眼镜注册模板对摘下眼镜后的外观变化较敏感，但该样本
仍明显高于本轮合格网络陌生人的最高分。

App截图包含界面缩放和JPEG压缩，不是当前注册阶段保存的112×112原图，因此这些
分数只适合观察相对分布。

## 网络代理陌生人结果

| Pexels图片 | 作者 | normal | fillLight | 质量 |
| --- | --- | ---: | ---: | --- |
| [12275727](https://www.pexels.com/photo/portrait-of-a-man-looking-at-the-camera-12275727/) | centaurus picture | 0.0154 | 0.0092 | 通过 |
| [14172203](https://www.pexels.com/photo/grayscale-photography-of-a-man-looking-at-the-camera-14172203/) | Анастасия Климец | 0.0403 | 0.0488 | 通过 |
| [17594387](https://www.pexels.com/photo/portrait-of-a-man-17594387/) | Sandro Tavares | 0.0292 | 0.0616 | 通过 |
| [18108800](https://www.pexels.com/photo/portrait-of-woman-18108800/) | Dynamic Wang | -0.0673 | -0.0453 | 通过 |
| [24589428](https://www.pexels.com/photo/portrait-of-woman-24589428/) | Jean Marc Bonnel | 0.0015 | 0.0245 | 通过 |
| [4095252](https://www.pexels.com/photo/confident-casual-black-man-looking-at-camera-4095252/) | Brett Sayles | 0.1293 | 0.0691 | 通过 |
| [5317540](https://www.pexels.com/photo/serious-asian-woman-looking-at-camera-5317540/) | Roberto Hund | 0.1154 | 0.0877 | 通过 |
| [6355945](https://www.pexels.com/photo/handsome-black-male-looking-at-camera-6355945/) | Muhammad-Taha Ibrahim | 0.1241 | 0.0922 | 过暗，拒绝 |
| [7533320](https://www.pexels.com/photo/confident-black-man-in-black-suit-looking-at-camera-7533320/) | SHVETS production | 0.0842 | 0.0717 | 过暗，拒绝 |
| [9716799](https://www.pexels.com/photo/asian-woman-looking-at-camera-9716799/) | Hieu Van | 0.2124 | 0.2163 | 通过 |

图片页面均标记为免费使用，作者和来源同时记录在
`model-tools/proxy-image-manifest.json`。本项目只把它们用于本地非商业原型测试，
原始下载图片位于被Git忽略的 `static-test-data`，不会打包进APK。

## 测试实现

离线工具执行以下流程：

```text
设备中只读提取seat-01的normal/fillLight模板
→ OpenCV YuNet检测五点
→ 使用与App相同的InsightFace五点标准坐标
→ 对齐到112×112
→ RGB及(pixel-127.5)/128
→ 同一个256维FP32 TFLite模型
→ L2归一化
→ 分别输出normal和fillLight余弦分数
```

离线检测器使用
[OpenCV YuNet](https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet)，
而App实时流程使用ML Kit。两种检测器的关键点可能有小幅差异，所以离线分数不能
直接当作App阈值。测试没有跨模板取最大值作正式接受判断。

可复现命令：

```powershell
D:\Ai_project\android_test\.model-cache\venv\Scripts\python.exe `
  model-tools\static_face_diagnostic.py `
  --adb D:\Android\Sdk\platform-tools\adb.exe `
  --serial eb224b07 `
  --person-id seat-01 `
  --model android-app\app\src\main\assets\models\se_mobilefacenet_emb256_fp32.tflite `
  --detector static-test-data\detector\face_detection_yunet_2023mar.onnx `
  --user-dir static-test-data\gallery-top10-20260724 `
  --control-dir static-test-data\device-control `
  --proxy-dir static-test-data\proxy `
  --manifest model-tools\proxy-image-manifest.json `
  --output STATIC_IMAGE_TEST_RESULTS.json
```

## 结果边界

本轮只证明：

- 新模型能够把当前10张本人图片与这10张网络肖像明显分开；
- 无脸、严重模糊和部分过暗图片会被检测或质量门槛拒绝；
- 当前模板、模型哈希和pipeline版本一致。

本轮不能证明：

- CameraX自然光5帧和补光5帧实时采集一定通过；
- 多人Top1/Top2分差在真实环境中稳定；
- 照片或屏幕翻拍攻击会被阻止；当前没有活体检测；
- 系统已经达到正式FMR/FNMR或安全等级。

App当前仍为：

```text
registeredCount = 1
thresholdStatus = CALIBRATION_PENDING
verificationLevel = NONE
```

后续有真人参与者时，仍需按 `CALIBRATION.md` 完成多人现场原型标定。
