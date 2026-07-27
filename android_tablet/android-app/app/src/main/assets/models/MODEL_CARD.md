# SE-MobileFaceNet embedding model card

## Deployed artifact

- Asset: `se_mobilefacenet_emb256_fp32.tflite`
- SHA-256:
  `4593a73d01a55342fd0f857b881bbb8da9308134b1de0ed4db34f14566650ad5`
- Size: `4,441,048` bytes
- Input: float32 `[1,112,112,3]`
- Output: float32 `[1,256]`
- Color order: RGB
- Normalization: `(value - 127.5) / 128`
- Output handling: L2 normalization
- Alignment: InsightFace five-point template
- Pipeline version: 3

The binary artifact is intentionally excluded from Git because the pretrained
weight is restricted to non-commercial research use. Reproduce it locally with
`model-tools/convert_se_mobilefacenet.py` and verify the SHA-256 above before
building the Android app.

This is an embedding-only `basic_model`. Its final Keras layer is named
`embedding`; it does not contain the ArcFace training identity classifier
and does not output training-dataset logits.

## Pinned source

- Project: `leondgarse/Keras_insightface`
- Release: `v1.0.0`
- Architecture/training:
  `se_mobile_facenet`, MS1MV3, ArcFace, 256-dimensional embedding
- Source file:
  `TF11_se_mobilefacenet_pointwise_GDC_arc_emb256_dr0_sgd_no_alpha_bs512_ms1m_rand_0_bnm09_bne1e4_cos16_batch_float16_basic_agedb_30_epoch_50_0.973000.h5`
- Source URL:
  `https://github.com/leondgarse/Keras_insightface/releases/download/v1.0.0/TF11_se_mobilefacenet_pointwise_GDC_arc_emb256_dr0_sgd_no_alpha_bs512_ms1m_rand_0_bnm09_bne1e4_cos16_batch_float16_basic_agedb_30_epoch_50_0.973000.h5`
- Source size: `5,206,744` bytes
- Source SHA-256:
  `1482ccbfba3c9f3d453c4419cea78459b570f1856867d2c0270a7dd8a90be56d`

The reproducible conversion script is in `model-tools`. It forces float32
layer policies, asserts the embedding input/output shapes, and refuses a
classification model.

## Conversion validation

Ten different synthetic, front-facing face images were used only for
Keras/TFLite numerical parity:

- Image count: 10
- Minimum embedding cosine parity: `1.0`
- Mean embedding cosine parity: `1.0000000715`
- No NaN, Inf, zero vector, dimension mismatch, or logits output occurred.

These synthetic images prove conversion equivalence only. They are not an
accuracy benchmark and are not used to select the verification threshold.

## License boundary

- Repository code: MIT
- Pretrained model/training-data use: non-commercial research only
- Approved use here: internal technical prototype validation
- Commercial deployment: prohibited until the weight is replaced by a
  model with explicit commercial and redistribution permission
