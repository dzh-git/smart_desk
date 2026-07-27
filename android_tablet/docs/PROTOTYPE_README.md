# SmartDesk Tablet Prototype

> 历史说明：本文对应冻结标签 `v0.8.0-face-prototype`。正式 Android 模块入口和
> 当前 Bridge 契约请以 `../README.md` 为准。

当前版本 `0.8.0` 用于 Redmi K60 上的非商业人脸身份验证可行性实验。

```text
CameraX前置摄像头
→ 中央圆圈AF/AE/AWB
→ ML Kit人脸检测（minFaceSize=0.3）
→ 五点对齐112×112
→ 400ms测光等待＋三帧亮度稳定检查
→ SE-MobileFaceNet 256维embedding
→ 自然光/屏幕补光分别采集5帧
→ 删除最不一致帧并聚合其余4帧
→ 同光照模板的人员级Top1/Top2判断
```

## 当前能力

- 同一平板最多保存9名人员。
- 每人原子保存 `normal`、`fillLight` 两个模板，不保存正式流程照片。
- 自然光只匹配 `normal`；自然光失败后开启补光并只匹配
  `fillLight`，不跨模板取最大值。
- 通过条件为：Top1达到阈值、Top1与Top2分差至少0.05、5帧中至少4帧
  指向同一Top1人员。
- 模型或pipeline变更会使旧模板失效。
- Debug诊断必须手动开启，数据仅保存在App私有目录，可清除。

没有原型标定阈值时，App只返回 `CALIBRATION_PENDING` 和匹配分数。
75次现场测试后可应用 `PROVISIONAL` 阈值，返回的 `VERIFIED` 仍标记为
`verificationLevel=PROTOTYPE`，不能解释为正式安全认证。

## 模型

- 输入：float32 `[1,112,112,3]` RGB
- 归一化：`(pixel-127.5)/128`
- 输出：float32 `[1,256]` embedding
- TFLite SHA-256：
  `4593a73d01a55342fd0f857b881bbb8da9308134b1de0ed4db34f14566650ad5`
- 运行时强制验证模型哈希、输入输出形状和有限非零输出。

部署的是 ArcFace 分类头之前的 SE-MobileFaceNet `basic_model`，不是训练身份
logits。转换脚本和固定源文件信息见 [model-tools](model-tools/README.md)，完整
模型卡见 App 的 `assets/models/MODEL_CARD.md`。

仓库代码采用MIT许可证，但MS1MV3预训练权重仅限非商业研究原型。商业部署必须
更换许可明确的权重。为避免在公开仓库中再次分发受限权重，TFLite二进制不纳入
Git；首次构建前需按 `model-tools/README.md` 下载固定源文件并完成转换，将输出
放到：

```text
android-app/app/src/main/assets/models/se_mobilefacenet_emb256_fp32.tflite
```

## 构建

环境：

- Android Studio：`D:\Program Files\Android\Android Studio`
- Android SDK：`D:\Android\Sdk`
- JDK：Android Studio JBR
- minSdk 23、targetSdk/compileSdk 36

在项目根目录执行：

```powershell
.\build-debug.ps1
```

APK输出：

```text
android-app\app\build\outputs\apk\debug\app-debug.apk
```

## 使用

1. 分别输入人员编号，完成至少2人的双光照注册；每人预计需要3–5秒。
2. 在标定前运行验证，只记录自然光和补光的Top1、Top2、分差及帧一致性。
3. 按 [CALIBRATION.md](CALIBRATION.md) 完成75次原型测试。
4. 只有分数形成合理间隔时才应用 `PROVISIONAL` 阈值。
5. 正式部署前仍需扩大陌生人样本、增加独立测试、活体检测、模板加密和商业
   模型许可。

实施问题的集中总结见 [IMPLEMENTATION_ISSUES.md](IMPLEMENTATION_ISSUES.md)，
单人图片代理测试见 [STATIC_IMAGE_TEST_REPORT.md](STATIC_IMAGE_TEST_REPORT.md)，
历史设备验收和详细日志见 [VALIDATION.md](VALIDATION.md)。
