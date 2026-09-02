# 人脸模型许可证发布门禁

## 当前结论

当前 `SE-MobileFaceNet / MS1MV3` 预训练权重仅允许非商业研究用途。
它只可用于内部原型、转换一致性验证和现场标定，不得被描述为可商业部署，
也不得随正式 APK 分发。

许可证边界：

- 上游 `Keras_insightface` 代码仓库标注为 MIT；
- 该 MIT 声明不改变预训练权重和训练数据的非商业研究限制；
- SmartDesk 主仓库当前没有根级开源许可证文件，因此不得自行推定其代码可对外
  再分发；正式发布还需项目所有者完成代码许可证审查；
- 当前允许范围仅为内部技术原型、数值转换验证和经授权的现场标定。

当前仓库有意保持以下状态：

- `face_model_config.json`：
  `licenseLevel=NON_COMMERCIAL_RESEARCH_PROTOTYPE`；
- `model-license-gate.json`：商业部署和再分发均为 `false`；
- 权重二进制不进入 Git；
- Debug 构建需要开发者在本地自行复现权重；
- Release 构建由 Gradle `checkModelLicenseGate` 强制阻断。

验证当前声明未被弱化：

```powershell
python scripts/check_model_license_gate.py --mode prototype
```

期望输出：

```text
MODEL_LICENSE_GATE_PROTOTYPE_OK: release remains blocked
```

验证正式发布仍被阻断：

```powershell
python scripts/check_model_license_gate.py --mode release
```

当前必须以退出码 `2` 和 `MODEL_LICENSE_GATE_BLOCKED` 失败。

## 解除门禁的必要条件

这不是普通代码审批。只有取得新权重的明确商业使用及再分发授权后，才可由
授权负责人执行以下全部操作：

1. 用获准权重替换本地模型，并重新验证输入、输出、数值一致性和现场准确率。
2. 更新模型版本、来源、SHA-256、模型卡和 `licenseLevel`。
3. 将 `weightLicense` 改为 `COMMERCIAL_APPROVED`。
4. 将商业部署和再分发批准改为 `true`。
5. 在 `approvalRecord` 中记录审批人、ISO 8601 时间和仓库内授权证据路径。
6. 重新完成75次人脸标定及全部真机验收。
7. 运行 `--mode release`、Android Release 构建及完整发布验收。

仅修改 JSON 布尔值不构成授权。授权证据与实际模型哈希必须一致；许可证审查
和现场验证仍属于 `HUMAN_VALIDATION_REQUIRED`。
