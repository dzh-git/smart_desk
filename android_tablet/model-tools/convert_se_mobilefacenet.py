#!/usr/bin/env python3
"""Convert the pinned Keras embedding model to a float32 TFLite model.

The script intentionally refuses classification/logit models.  It also
compares Keras and TFLite embeddings before writing the final artifact.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import tensorflow as tf


EXPECTED_SOURCE_SHA256 = (
    "1482ccbfba3c9f3d453c4419cea78459b570f1856867d2c0270a7dd8a90be56d"
)
EXPECTED_SOURCE_URL = (
    "https://github.com/leondgarse/Keras_insightface/releases/download/"
    "v1.0.0/TF11_se_mobilefacenet_pointwise_GDC_arc_emb256_dr0_sgd_no_alpha_"
    "bs512_ms1m_rand_0_bnm09_bne1e4_cos16_batch_float16_basic_agedb_30_"
    "epoch_50_0.973000.h5"
)
EXPECTED_SOURCE_SIZE = 5_206_744
EXPECTED_INPUT_SHAPE = (None, 112, 112, 3)
EXPECTED_OUTPUT_SHAPE = (None, 256)
MIN_PARITY_IMAGES = 10
MIN_COSINE_PARITY = 0.999


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def force_float32_policy(value):
    if isinstance(value, dict):
        if (
            value.get("class_name") == "Policy"
            and value.get("config", {}).get("name") == "mixed_float16"
        ):
            replacement = dict(value)
            replacement["config"] = {"name": "float32"}
            return replacement
        return {key: force_float32_policy(item) for key, item in value.items()}
    if isinstance(value, list):
        return [force_float32_policy(item) for item in value]
    return value


def load_embedding_model(source_path: Path) -> tf.keras.Model:
    if source_path.stat().st_size != EXPECTED_SOURCE_SIZE:
        raise ValueError("源权重文件大小与固定版本不一致")
    actual_hash = sha256(source_path)
    if actual_hash != EXPECTED_SOURCE_SHA256:
        raise ValueError(f"源权重SHA-256不匹配：{actual_hash}")

    source = tf.keras.models.load_model(source_path, compile=False)
    if tuple(source.input_shape) != EXPECTED_INPUT_SHAPE:
        raise ValueError(f"源模型输入错误：{source.input_shape}")
    if tuple(source.output_shape) != EXPECTED_OUTPUT_SHAPE:
        raise ValueError(
            "源模型必须输出256维embedding，禁止导出ArcFace分类logits："
            f"{source.output_shape}"
        )
    if source.layers[-1].name != "embedding":
        raise ValueError(f"源模型最终层不是embedding：{source.layers[-1].name}")

    config = force_float32_policy(source.get_config())
    embedding_model = tf.keras.Model.from_config(config)
    embedding_model.set_weights(source.get_weights())
    if tuple(embedding_model.output_shape) != EXPECTED_OUTPUT_SHAPE:
        raise ValueError("float32克隆模型输出维度改变")
    return embedding_model


def load_aligned_faces(directory: Path) -> list[np.ndarray]:
    image_paths = sorted(
        path
        for path in directory.iterdir()
        if path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}
    )
    if len(image_paths) < MIN_PARITY_IMAGES:
        raise ValueError(
            f"转换验证至少需要{MIN_PARITY_IMAGES}张112x112对齐人脸，"
            f"当前只有{len(image_paths)}张"
        )

    faces: list[np.ndarray] = []
    for path in image_paths:
        raw = tf.io.read_file(str(path))
        image = tf.io.decode_image(raw, channels=3, expand_animations=False)
        if tuple(image.shape) != (112, 112, 3):
            raise ValueError(f"{path.name}不是112x112 RGB图像：{image.shape}")
        normalized = (tf.cast(image, tf.float32) - 127.5) / 128.0
        faces.append(normalized.numpy())
    return faces


def cosine(left: np.ndarray, right: np.ndarray) -> float:
    denominator = np.linalg.norm(left) * np.linalg.norm(right)
    if denominator <= 0 or not np.isfinite(denominator):
        raise ValueError("模型产生零向量或非有限向量")
    return float(np.dot(left, right) / denominator)


def validate_tflite(
    keras_model: tf.keras.Model,
    tflite_bytes: bytes,
    faces: list[np.ndarray],
) -> list[float]:
    interpreter = tf.lite.Interpreter(model_content=tflite_bytes)
    interpreter.allocate_tensors()
    input_detail = interpreter.get_input_details()[0]
    output_detail = interpreter.get_output_details()[0]
    if tuple(input_detail["shape"]) != (1, 112, 112, 3):
        raise ValueError(f"TFLite输入错误：{input_detail['shape']}")
    if tuple(output_detail["shape"]) != (1, 256):
        raise ValueError(
            "TFLite必须输出[1,256] embedding，禁止使用分类logits："
            f"{output_detail['shape']}"
        )
    if input_detail["dtype"] != np.float32 or output_detail["dtype"] != np.float32:
        raise ValueError("TFLite输入和输出必须为float32")

    similarities: list[float] = []
    for face in faces:
        batch = face[np.newaxis, ...].astype(np.float32)
        keras_embedding = keras_model(batch, training=False).numpy()[0]
        interpreter.set_tensor(input_detail["index"], batch)
        interpreter.invoke()
        lite_embedding = interpreter.get_tensor(output_detail["index"])[0]
        if not np.all(np.isfinite(keras_embedding)):
            raise ValueError("Keras embedding包含NaN/Inf")
        if not np.all(np.isfinite(lite_embedding)):
            raise ValueError("TFLite embedding包含NaN/Inf")
        score = cosine(keras_embedding, lite_embedding)
        if score < MIN_COSINE_PARITY:
            raise ValueError(f"Keras/TFLite embedding偏差过大：{score:.6f}")
        similarities.append(score)
    return similarities


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--parity-images", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()

    model = load_embedding_model(args.source)
    faces = load_aligned_faces(args.parity_images)
    converter = tf.lite.TFLiteConverter.from_keras_model(model)
    converter.optimizations = []
    converter.target_spec.supported_ops = [
        tf.lite.OpsSet.TFLITE_BUILTINS,
    ]
    converter.target_spec.supported_types = [tf.float32]
    converter.inference_input_type = tf.float32
    converter.inference_output_type = tf.float32
    tflite_bytes = converter.convert()
    similarities = validate_tflite(model, tflite_bytes, faces)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(tflite_bytes)
    report = {
        "sourceFile": args.source.name,
        "sourceUrl": EXPECTED_SOURCE_URL,
        "sourceSize": args.source.stat().st_size,
        "sourceSha256": sha256(args.source),
        "outputFile": args.output.name,
        "outputSize": len(tflite_bytes),
        "outputSha256": hashlib.sha256(tflite_bytes).hexdigest(),
        "inputShape": [1, 112, 112, 3],
        "outputShape": [1, 256],
        "parityImageCount": len(faces),
        "minimumCosineParity": min(similarities),
        "meanCosineParity": float(np.mean(similarities)),
    }
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
