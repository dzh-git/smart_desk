# SE-MobileFaceNet model conversion

The Android app uses only the 256-dimensional embedding model. It must never
ship an ArcFace training classification head or identity logits.

Pinned source:

- Repository: `leondgarse/Keras_insightface`
- Release: `v1.0.0`
- File:
  `TF11_se_mobilefacenet_pointwise_GDC_arc_emb256_dr0_sgd_no_alpha_bs512_ms1m_rand_0_bnm09_bne1e4_cos16_batch_float16_basic_agedb_30_epoch_50_0.973000.h5`
- Source URL:
  `https://github.com/leondgarse/Keras_insightface/releases/download/v1.0.0/TF11_se_mobilefacenet_pointwise_GDC_arc_emb256_dr0_sgd_no_alpha_bs512_ms1m_rand_0_bnm09_bne1e4_cos16_batch_float16_basic_agedb_30_epoch_50_0.973000.h5`
- Size: `5,206,744` bytes
- SHA-256:
  `1482ccbfba3c9f3d453c4419cea78459b570f1856867d2c0270a7dd8a90be56d`

The conversion script rejects an unexpected source hash, non-112 RGB input,
non-256 output, or a final layer other than `embedding`. It requires at least
ten real 112x112 aligned face images and verifies each Keras/TFLite embedding
pair before writing the final TFLite artifact.

Example:

```powershell
python convert_se_mobilefacenet.py `
  --source <downloaded-basic-model.h5> `
  --parity-images <directory-with-at-least-10-aligned-faces> `
  --output ..\android-app\app\src\main\assets\models\se_mobilefacenet_emb256_fp32.tflite `
  --report conversion-report.local.json
```

Confirm the generated file SHA-256 is
`4593a73d01a55342fd0f857b881bbb8da9308134b1de0ed4db34f14566650ad5`
before building. The generated model and local parity images are ignored by
Git.

The repository code is MIT licensed. The pretrained weights and their
MS1MV3 training data are restricted to non-commercial research use. This
artifact is for prototype validation only.
