"""Download the four local models required by bilingual speech translation.

Downloads are rooted under the project directory so a non-ASCII Windows user
profile is never part of the runtime model path.
"""
from __future__ import annotations

import argparse
import shutil
import tarfile
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MODELS_ROOT = PROJECT_ROOT / "models"
CACHE_ROOT = MODELS_ROOT / ".cache"
ENGLISH_STREAMING_ARCHIVE = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/"
    "sherpa-onnx-streaming-zipformer-en-2023-06-26.tar.bz2"
)
ENGLISH_STREAMING_DIR = "sherpa-onnx-streaming-zipformer-en-2023-06-26"
ENGLISH_STREAMING_FILES = (
    "encoder-epoch-99-avg-1-chunk-16-left-128.int8.onnx",
    "decoder-epoch-99-avg-1-chunk-16-left-128.int8.onnx",
    "joiner-epoch-99-avg-1-chunk-16-left-128.int8.onnx",
    "tokens.txt",
)


def _has_weights(path: Path) -> bool:
    return path.is_dir() and any(
        (path / name).is_file()
        for name in ("model.pt", "model.safetensors", "pytorch_model.bin")
    )


def _prepare_huggingface(repo_id: str, target: Path, force: bool) -> None:
    if _has_weights(target) and not force:
        print(f"[OK] {target.name} already exists")
        return
    from huggingface_hub import snapshot_download

    target.mkdir(parents=True, exist_ok=True)
    snapshot_download(
        repo_id=repo_id,
        local_dir=str(target),
        cache_dir=str(CACHE_ROOT / "huggingface"),
    )
    if not _has_weights(target):
        raise RuntimeError(f"Downloaded model has no recognized weights: {target}")
    print(f"[OK] {repo_id} -> {target}")


def _prepare_modelscope(repo_id: str, target: Path, force: bool) -> None:
    if _has_weights(target) and not force:
        print(f"[OK] {target.name} already exists")
        return
    from modelscope.hub.snapshot_download import snapshot_download

    cached = Path(snapshot_download(
        repo_id,
        cache_dir=str(CACHE_ROOT / "modelscope"),
    ))
    target.mkdir(parents=True, exist_ok=True)
    shutil.copytree(cached, target, dirs_exist_ok=True)
    if not _has_weights(target):
        raise RuntimeError(f"Downloaded model has no recognized weights: {target}")
    print(f"[OK] {repo_id} -> {target}")


def _has_english_streaming_model(path: Path) -> bool:
    return path.is_dir() and all((path / name).is_file() for name in ENGLISH_STREAMING_FILES)


def _prepare_english_streaming(target: Path, force: bool) -> None:
    """Download/extract the official Sherpa Zipformer archive idempotently."""
    if _has_english_streaming_model(target) and not force:
        print(f"[OK] {target.name} already exists")
        return
    CACHE_ROOT.mkdir(parents=True, exist_ok=True)
    archive = CACHE_ROOT / f"{ENGLISH_STREAMING_DIR}.tar.bz2"
    if force or not archive.is_file():
        print(f"[DOWNLOAD] {ENGLISH_STREAMING_ARCHIVE}")
        urllib.request.urlretrieve(ENGLISH_STREAMING_ARCHIVE, archive)
    extract_root = CACHE_ROOT / f"{ENGLISH_STREAMING_DIR}.extract"
    if extract_root.exists():
        shutil.rmtree(extract_root)
    extract_root.mkdir(parents=True)
    with tarfile.open(archive, "r:bz2") as tar:
        root = extract_root.resolve()
        for member in tar.getmembers():
            destination = (extract_root / member.name).resolve()
            if destination != root and root not in destination.parents:
                raise RuntimeError(f"Unsafe archive member: {member.name}")
        tar.extractall(extract_root)
    unpacked = extract_root / ENGLISH_STREAMING_DIR
    if not _has_english_streaming_model(unpacked):
        raise RuntimeError(f"Zipformer archive is incomplete: {unpacked}")
    if target.exists():
        shutil.rmtree(target)
    shutil.move(str(unpacked), str(target))
    shutil.rmtree(extract_root, ignore_errors=True)
    print(f"[OK] English streaming Zipformer -> {target}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare SmartDesk bilingual models")
    parser.add_argument("--force", action="store_true", help="refresh existing snapshots")
    args = parser.parse_args()

    MODELS_ROOT.mkdir(parents=True, exist_ok=True)
    CACHE_ROOT.mkdir(parents=True, exist_ok=True)
    _prepare_modelscope(
        "iic/SenseVoiceSmall", MODELS_ROOT / "SenseVoiceSmall", args.force,
    )
    _prepare_modelscope(
        "iic/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-pytorch",
        MODELS_ROOT / "iic" / "speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-pytorch",
        args.force,
    )
    _prepare_huggingface(
        "Helsinki-NLP/opus-mt-zh-en", MODELS_ROOT / "opus-mt-zh-en", args.force,
    )
    _prepare_huggingface(
        "Helsinki-NLP/opus-mt-en-zh", MODELS_ROOT / "opus-mt-en-zh", args.force,
    )
    _prepare_english_streaming(
        MODELS_ROOT / ENGLISH_STREAMING_DIR, args.force,
    )
    print("All bilingual speech translation models are ready.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
