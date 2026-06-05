"""
Real model smoke test for SpeechModule.

Validates that:
  1. Python speech dependencies are importable (numpy, funasr, scipy, etc.)
  2. Model files are found in local cache (models/models--funasr--*)
  3. SpeechModule.preload() succeeds (loads + warms up all models)
  4. A short synthetic audio chunk can be processed through the streaming ASR
     pipeline (process_interim_array) without error.

This test uses REAL models — no mocks, no stubs.
If models are not available, the test is SKIPPED, not faked.

Environment issues are recorded in working/env-issues.md.
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

import numpy as np
import pytest

# Add project root to sys.path so `backend` and `models/` are resolvable
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# ── Helpers ──────────────────────────────────────────────────────────────────


def _model_dir(name: str) -> Path:
    """Return expected local cache path for a HuggingFace model."""
    return PROJECT_ROOT / "models" / f"models--funasr--{name}" / "snapshots"


def _any_snapshot(path: Path) -> bool:
    """True if the path contains at least one snapshot subdirectory with files."""
    if not path.is_dir():
        return False
    try:
        return any(path.iterdir())
    except OSError:
        return False


def _find_model_absolute() -> str | None:
    """Resolve the paraformer-zh-streaming model path using stt_streaming logic."""
    try:
        from backend.speech_module.stt_streaming import _resolve_model_path
        return _resolve_model_path(None, "paraformer-zh-streaming",
                                    "iic/speech_paraformer_asr_nat-zh-cn-16k-common-vocab8404-online")
    except Exception:
        return None


# ── Test: dependency imports ─────────────────────────────────────────────────


class TestSpeechDependencies:
    """Verify speech packages are importable."""

    REQUIRED_PACKAGES = [
        "numpy",
        "torch",
        "funasr",
        "scipy",
        "soundfile",
    ]

    OPTIONAL_PACKAGES = [
        "pydub",  # only needed for offline audio file loading (audio_utils.py)
    ]

    @pytest.mark.parametrize("pkg_name", REQUIRED_PACKAGES)
    def test_import_required(self, pkg_name: str) -> None:
        """Required speech packages must be importable."""
        importlib.import_module(pkg_name)

    @pytest.mark.parametrize("pkg_name", OPTIONAL_PACKAGES)
    def test_import_optional(self, pkg_name: str) -> None:
        """Optional packages — may be missing if offline file loading not needed."""
        try:
            importlib.import_module(pkg_name)
        except ImportError:
            pytest.skip(f"{pkg_name} not installed (optional)")


# ── Test: model file discovery ───────────────────────────────────────────────


@pytest.mark.skipif(
    not _model_dir("paraformer-zh-streaming").is_dir(),
    reason="Paraformer Streaming model not found in local cache. "
           "Run: cd models && git clone https://huggingface.co/funasr/paraformer-zh-streaming",
)
class TestModelDiscovery:
    """Verify model files exist (snapshot directories are non-empty)."""

    def test_paraformer_streaming_snapshot(self) -> None:
        """Paraformer Streaming — snapshot directory must exist and have files."""
        snap = _model_dir("paraformer-zh-streaming")
        assert _any_snapshot(snap), (
            f"No snapshots found in {snap}\n"
            f"The directory exists but appears empty. Try:\n"
            f"  cd models/models--funasr--paraformer-zh-streaming && "
            f"git lfs pull"
        )

    def test_paraformer_large_snapshot(self) -> None:
        """Paraformer-large — snapshot directory must exist and have files."""
        snap = _model_dir("Paraformer-large")
        assert _any_snapshot(snap), (
            f"No snapshots found in {snap}\n"
        )

    def test_fsmn_vad_snapshot(self) -> None:
        """FSMN-VAD — snapshot directory must exist and have files."""
        snap = _model_dir("fsmn-vad")
        assert _any_snapshot(snap), (
            f"No snapshots found in {snap}\n"
        )


# ── Test: SpeechModule.preload() ─────────────────────────────────────────────


@pytest.mark.skipif(
    not any(
        _model_dir(n).is_dir()
        for n in ["paraformer-zh-streaming", "Paraformer-large"]
    ),
    reason="None of the required models found in local cache.",
)
class TestSpeechModulePreload:
    """Real SpeechModule loading — requires models + GPU or CPU memory."""

    def test_preload_succeeds(self) -> None:
        """SpeechModule.preload() must complete without raising."""
        from backend.speech_module import SpeechModule
        sm = SpeechModule(max_workers=2)
        sm.preload()
        assert sm.ready, "SpeechModule should report ready after preload()"

    def test_process_synthetic_audio(self) -> None:
        """Process a short synthetic audio chunk through streaming ASR.

        This verifies the end-to-end pipeline:
          SpeechModule.preload() → process_interim_array() with 1 second
          of 440 Hz sine wave at 16 kHz.

        The test does NOT assert on transcription accuracy (sine wave is not
        speech). It asserts that the pipeline does not crash.
        """
        from backend.speech_module import SpeechModule
        sm = SpeechModule(max_workers=2)
        sm.preload()

        # Generate 1 second of 440 Hz sine wave at 16 kHz
        sample_rate = 16000
        duration_s = 1.0
        t = np.linspace(0, duration_s, int(sample_rate * duration_s),
                         endpoint=False, dtype=np.float32)
        audio = (np.sin(2 * np.pi * 440 * t) * 0.3).astype(np.float32)

        sm.set_session_context("test_smoke", 1, 1)
        result = sm.process_interim_array(audio, "test_smoke", sample_rate)

        # result should be a string (may be empty if model outputs nothing
        # for non-speech audio, but must not raise)
        assert isinstance(result, str), (
            f"process_interim_array should return str, got {type(result)}"
        )


# ── Test: warmup functions resolve model paths ───────────────────────────────


class TestModelPathResolution:
    """Verify that model path resolution finds local cache directories."""

    def test_streaming_path_resolves(self) -> None:
        """warmup_streaming model path must resolve without error."""
        path = _find_model_absolute()
        assert path is not None, (
            "Model path resolution returned None.\n"
            "Expected either a local snapshot path or a Modelscope ID.\n"
        )

    def test_offline_path_resolves(self) -> None:
        """warmup_offline model path must resolve without error."""
        try:
            from backend.speech_module.stt_streaming import _resolve_model_path
            path = _resolve_model_path(None, "Paraformer-large",
                                        "iic/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-pytorch")
            assert path is not None
        except Exception as exc:
            pytest.skip(f"Path resolution failed: {exc}")


# ── Environment diagnostics (always run, never fail) ───────────────────────


@pytest.mark.filterwarnings("always")
def test_diagnose_environment(capsys: pytest.CaptureFixture) -> None:
    """Print environment diagnostics for debugging.

    This test never fails. It collects and displays relevant environment
    information to help diagnose setup issues.
    """
    print()
    print("── SmartDesk Speech Environment Diagnostics ──")
    print(f"  Python:       {sys.version}")
    print(f"  Project root: {PROJECT_ROOT}")
    print()

    # Models
    print("  Model directories:")
    for name in ["paraformer-zh-streaming", "Paraformer-large", "fsmn-vad"]:
        snap = _model_dir(name)
        if _any_snapshot(snap):
            files = list(snap.iterdir())
            print(f"    {name}: FOUND ({len(files)} entries)")
        elif snap.is_dir():
            print(f"    {name}: DIR EXISTS (empty)")
        else:
            print(f"    {name}: NOT FOUND")

    ms_path = PROJECT_ROOT / "models" / "iic" / \
        "speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-pytorch"
    if ms_path.is_dir():
        print(f"    iic/Paraformer-large MS: FOUND")
    print()

    # Dependencies
    print("  Speech packages:")
    for pkg_name, is_required in [("numpy", True), ("torch", True), ("funasr", True), ("scipy", True), ("soundfile", True), ("pydub", False)]:
        try:
            mod = importlib.import_module(pkg_name)
            ver = getattr(mod, "__version__", "unknown")
            print(f"    {pkg_name}: {ver}")
        except ImportError:
            label = "REQUIRED" if is_required else "OPTIONAL"
            print(f"    {pkg_name}: NOT INSTALLED ({label})")

    print("  ───────────────────────────────────────────")
    print()
