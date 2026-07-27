#!/usr/bin/env python3
"""Run read-only static-image diagnostics against an enrolled Android template.

This tool is intentionally not a calibration tool. It reports normal and
fill-light scores separately and never changes the app threshold or templates.
"""

from __future__ import annotations

import argparse
import html
import json
import math
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import cv2
import numpy as np
import tensorflow as tf


CANONICAL_POINTS = np.array(
    [
        [38.2946, 51.6963],
        [73.5318, 51.5014],
        [56.0252, 71.7366],
        [41.5493, 92.3655],
        [70.7299, 92.2041],
    ],
    dtype=np.float32,
)
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
EXPECTED_MODEL_SHA256 = (
    "4593a73d01a55342fd0f857b881bbb8da9308134b1de0ed4db34f14566650ad5"
)


def sha256(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def l2_normalize(vector: np.ndarray) -> np.ndarray:
    vector = np.asarray(vector, dtype=np.float32)
    norm = float(np.linalg.norm(vector))
    if not math.isfinite(norm) or norm <= 0:
        raise ValueError("特征为零向量或包含非有限值")
    return vector / norm


def cosine(left: np.ndarray, right: np.ndarray) -> float:
    return float(np.dot(l2_normalize(left), l2_normalize(right)))


def read_registered_templates(
    adb: Path,
    serial: str,
    person_id: str,
) -> tuple[np.ndarray, np.ndarray, dict]:
    command = [
        str(adb),
        "-s",
        serial,
        "shell",
        "run-as",
        "com.smartdesk.tablet",
        "cat",
        "shared_prefs/face_identity_private.xml",
    ]
    result = subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    root = ET.fromstring(result.stdout)
    templates_node = next(
        (
            node
            for node in root.findall("string")
            if node.attrib.get("name") == "face_templates_v3"
        ),
        None,
    )
    if templates_node is None or templates_node.text is None:
        raise ValueError("设备中没有256维face_templates_v3模板")
    payload = json.loads(html.unescape(templates_node.text))
    person = next(
        (
            candidate
            for candidate in payload.get("persons", [])
            if candidate.get("personId") == person_id
        ),
        None,
    )
    if person is None:
        raise ValueError(f"设备中没有人员模板：{person_id}")
    if payload.get("modelHash") != EXPECTED_MODEL_SHA256:
        raise ValueError("设备模板绑定的模型SHA-256与当前测试模型不一致")
    normal = l2_normalize(np.asarray(person["normalEmbedding"], dtype=np.float32))
    fill = l2_normalize(
        np.asarray(person["fillLightEmbedding"], dtype=np.float32)
    )
    if normal.shape != (256,) or fill.shape != (256,):
        raise ValueError("设备模板不是256维embedding")
    metadata = {
        "personId": person_id,
        "modelVersion": payload.get("modelVersion"),
        "modelHash": payload.get("modelHash"),
        "pipelineVersion": payload.get("pipelineVersion"),
        "normalSampleCount": person.get("normalSampleCount"),
        "fillLightSampleCount": person.get("fillLightSampleCount"),
        "createdAt": person.get("createdAt"),
    }
    return normal, fill, metadata


def read_image(path: Path) -> np.ndarray:
    encoded = np.fromfile(path, dtype=np.uint8)
    image = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("图像解码失败")
    return image


def similarity_transform(
    source: np.ndarray,
    target: np.ndarray,
) -> np.ndarray:
    source_center = np.mean(source, axis=0)
    target_center = np.mean(target, axis=0)
    centered_source = source - source_center
    centered_target = target - target_center
    denominator = float(np.sum(centered_source * centered_source))
    if denominator <= 0:
        raise ValueError("人脸关键点重合，无法对齐")
    scale_cos = float(
        np.sum(
            centered_source[:, 0] * centered_target[:, 0]
            + centered_source[:, 1] * centered_target[:, 1]
        )
    )
    scale_sin = float(
        np.sum(
            centered_source[:, 0] * centered_target[:, 1]
            - centered_source[:, 1] * centered_target[:, 0]
        )
    )
    a = scale_cos / denominator
    b = scale_sin / denominator
    translate_x = (
        target_center[0] - a * source_center[0] + b * source_center[1]
    )
    translate_y = (
        target_center[1] - b * source_center[0] - a * source_center[1]
    )
    return np.array(
        [[a, -b, translate_x], [b, a, translate_y]],
        dtype=np.float32,
    )


def ordered_landmarks(face: np.ndarray) -> np.ndarray:
    # YuNet: right eye, left eye, nose, right mouth, left mouth.
    # The Android canonical template is positional from image-left to right.
    eyes = np.array([[face[4], face[5]], [face[6], face[7]]])
    mouth = np.array([[face[10], face[11]], [face[12], face[13]]])
    eyes = eyes[np.argsort(eyes[:, 0])]
    mouth = mouth[np.argsort(mouth[:, 0])]
    return np.array(
        [eyes[0], eyes[1], [face[8], face[9]], mouth[0], mouth[1]],
        dtype=np.float32,
    )


def align_largest_face(
    detector,
    image: np.ndarray,
) -> tuple[np.ndarray, int, float]:
    faces = None
    detection_image = image
    for scale in (1.0, 0.75, 0.5, 0.33, 0.25):
        if scale == 1.0:
            candidate = image
        else:
            candidate = cv2.resize(
                image,
                None,
                fx=scale,
                fy=scale,
                interpolation=cv2.INTER_AREA,
            )
        height, width = candidate.shape[:2]
        detector.setInputSize((width, height))
        _, candidate_faces = detector.detect(candidate)
        if candidate_faces is not None and len(candidate_faces) > 0:
            faces = candidate_faces
            detection_image = candidate
            break
    if faces is None:
        raise ValueError("未检测到人脸")
    largest = max(faces, key=lambda row: float(row[2] * row[3]))
    matrix = similarity_transform(
        ordered_landmarks(largest),
        CANONICAL_POINTS,
    )
    aligned = cv2.warpAffine(
        detection_image,
        matrix,
        (112, 112),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(0, 0, 0),
    )
    return aligned, len(faces), float(largest[14])


def quality_metrics(aligned_bgr: np.ndarray) -> tuple[float, float, bool]:
    rgb = cv2.cvtColor(aligned_bgr, cv2.COLOR_BGR2RGB).astype(np.int32)
    luminance = (
        77 * rgb[:, :, 0] + 150 * rgb[:, :, 1] + 29 * rgb[:, :, 2]
    ) >> 8
    center = luminance[16:-16, 16:-16]
    brightness = float(np.mean(center))
    sharpness_region = center[1:-1, 1:-1].astype(np.float64)
    laplacian = (
        4 * sharpness_region
        - center[1:-1, :-2]
        - center[1:-1, 2:]
        - center[:-2, 1:-1]
        - center[2:, 1:-1]
    )
    sharpness = float(np.var(laplacian))
    accepted = 55.0 <= brightness <= 210.0 and sharpness >= 40.0
    return brightness, sharpness, accepted


class EmbeddingModel:
    def __init__(self, model_path: Path):
        if sha256(model_path) != EXPECTED_MODEL_SHA256:
            raise ValueError("TFLite模型SHA-256不匹配")
        self.interpreter = tf.lite.Interpreter(model_path=str(model_path))
        self.interpreter.allocate_tensors()
        self.input = self.interpreter.get_input_details()[0]
        self.output = self.interpreter.get_output_details()[0]
        if tuple(self.input["shape"]) != (1, 112, 112, 3):
            raise ValueError(f"TFLite输入形状错误：{self.input['shape']}")
        if tuple(self.output["shape"]) != (1, 256):
            raise ValueError(f"TFLite输出形状错误：{self.output['shape']}")

    def embed(self, aligned_bgr: np.ndarray) -> np.ndarray:
        rgb = cv2.cvtColor(aligned_bgr, cv2.COLOR_BGR2RGB)
        batch = ((rgb.astype(np.float32) - 127.5) / 128.0)[None, ...]
        self.interpreter.set_tensor(self.input["index"], batch)
        self.interpreter.invoke()
        vector = self.interpreter.get_tensor(self.output["index"])[0]
        return l2_normalize(vector)


def collect_images(directory: Path) -> list[Path]:
    candidates = sorted(
        path
        for path in directory.iterdir()
        if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
    )
    unique = []
    seen_hashes = set()
    for path in candidates:
        digest = sha256(path)
        if digest not in seen_hashes:
            seen_hashes.add(digest)
            unique.append(path)
    return unique


def evaluate_group(
    label: str,
    paths: list[Path],
    detector,
    model: EmbeddingModel,
    normal_template: np.ndarray,
    fill_template: np.ndarray,
    aligned_dir: Path | None,
) -> list[dict]:
    results = []
    for path in paths:
        item = {"group": label, "file": path.name}
        try:
            image = read_image(path)
            aligned, face_count, detection_score = align_largest_face(
                detector,
                image,
            )
            brightness, sharpness, quality_accepted = quality_metrics(aligned)
            embedding = model.embed(aligned)
            item.update(
                {
                    "status": "OK",
                    "faceCount": face_count,
                    "detectionScore": detection_score,
                    "brightness": brightness,
                    "sharpness": sharpness,
                    "qualityAccepted": quality_accepted,
                    "scoreNormal": cosine(embedding, normal_template),
                    "scoreFillLight": cosine(embedding, fill_template),
                }
            )
            if aligned_dir is not None:
                destination = aligned_dir / label / f"{path.stem}.png"
                destination.parent.mkdir(parents=True, exist_ok=True)
                cv2.imencode(".png", aligned)[1].tofile(destination)
        except Exception as error:
            item.update({"status": "REJECTED", "reason": str(error)})
        results.append(item)
    return results


def summarize(results: list[dict]) -> dict:
    groups = {}
    for label in sorted({item["group"] for item in results}):
        items = [item for item in results if item["group"] == label]
        accepted = [
            item
            for item in items
            if item.get("status") == "OK" and item.get("qualityAccepted")
        ]
        group = {
            "total": len(items),
            "detected": sum(item.get("status") == "OK" for item in items),
            "qualityAccepted": len(accepted),
            "qualityRejected": sum(
                item.get("status") == "OK"
                and not item.get("qualityAccepted", False)
                for item in items
            ),
        }
        if accepted:
            for field in ("scoreNormal", "scoreFillLight"):
                values = [float(item[field]) for item in accepted]
                group[field] = {
                    "minimum": min(values),
                    "mean": sum(values) / len(values),
                    "maximum": max(values),
                }
        groups[label] = group
    genuine = groups.get("USER_GENUINE_PROXY", {})
    proxy = groups.get("WEB_PROXY_IMPOSTOR", {})
    if genuine.get("scoreNormal") and proxy.get("scoreNormal"):
        groups["exploratoryGap"] = {
            "normal": (
                genuine["scoreNormal"]["minimum"]
                - proxy["scoreNormal"]["maximum"]
            ),
            "fillLight": (
                genuine["scoreFillLight"]["minimum"]
                - proxy["scoreFillLight"]["maximum"]
            ),
            "calibrationUseProhibited": True,
        }
    return groups


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--adb", type=Path, required=True)
    parser.add_argument("--serial", required=True)
    parser.add_argument("--person-id", required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--detector", type=Path, required=True)
    parser.add_argument("--user-dir", type=Path, required=True)
    parser.add_argument("--control-dir", type=Path, required=True)
    parser.add_argument("--proxy-dir", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--aligned-dir", type=Path)
    args = parser.parse_args()

    normal, fill, template_metadata = read_registered_templates(
        args.adb,
        args.serial,
        args.person_id,
    )
    model = EmbeddingModel(args.model)
    detector = cv2.FaceDetectorYN.create(
        str(args.detector),
        "",
        (320, 320),
        0.75,
        0.3,
        5000,
    )
    user_results = evaluate_group(
        "USER_GENUINE_PROXY",
        collect_images(args.user_dir),
        detector,
        model,
        normal,
        fill,
        args.aligned_dir,
    )
    proxy_results = evaluate_group(
        "WEB_PROXY_IMPOSTOR",
        collect_images(args.proxy_dir),
        detector,
        model,
        normal,
        fill,
        args.aligned_dir,
    )
    control_results = evaluate_group(
        "DEVICE_QUALITY_CONTROL",
        collect_images(args.control_dir),
        detector,
        model,
        normal,
        fill,
        args.aligned_dir,
    )
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    results = user_results + proxy_results + control_results
    template_metadata["normalFillCosine"] = cosine(normal, fill)
    report = {
        "testType": "STATIC_IMAGE_PROXY_DIAGNOSTIC",
        "calibrationAllowed": False,
        "thresholdStatusMustRemain": "CALIBRATION_PENDING",
        "notes": [
            "静态图片不能替代CameraX实时5帧采集。",
            "任意图片同时输出normal和fillLight分数，不跨模板作正式接受判断。",
            "网络图片是照片/屏幕攻击代理，不用于估计FMR/FNMR。",
        ],
        "template": template_metadata,
        "detector": {
            "name": "OpenCV YuNet 2023mar",
            "source": (
                "https://github.com/opencv/opencv_zoo/tree/main/"
                "models/face_detection_yunet"
            ),
            "offlineAlignmentDifference": (
                "检测器不同于App的ML Kit，但使用相同的五点标准坐标、"
                "112x112 RGB归一化和TFLite embedding模型"
            ),
        },
        "proxyManifest": manifest,
        "summary": summarize(results),
        "results": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
