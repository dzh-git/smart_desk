"""
Generate speech-latency-device-report.json — device and model configuration audit.

Task 128A: Reads current runtime environment and SpeechModule status to produce
a structured report that can answer:
  - Is the system running on CPU or CUDA?
  - Are models preloaded?
  - What hardware is available?

Usage:
    python -m backend.scripts.generate_device_report

Output:
    working/speech-latency-device-report.json
"""
from __future__ import annotations

import json
import os
import platform
import sys
from pathlib import Path

REPORT_PATH = Path(__file__).resolve().parent.parent.parent / "working" / "speech-latency-device-report.json"


def _get_cpu_info() -> str:
    """Retrieve CPU info across platforms."""
    try:
        if sys.platform == "win32":
            import subprocess
            result = subprocess.run(
                ["wmic", "cpu", "get", "Name"],
                capture_output=True, text=True, timeout=5,
            )
            lines = result.stdout.strip().splitlines()
            if len(lines) >= 2:
                return lines[1].strip()
            return platform.processor() or "unknown"
        elif sys.platform == "linux":
            import subprocess
            result = subprocess.run(
                ["cat", "/proc/cpuinfo"],
                capture_output=True, text=True, timeout=5,
            )
            for line in result.stdout.splitlines():
                if line.startswith("model name"):
                    return line.split(":", 1)[1].strip()
            return platform.processer() or "unknown"
        elif sys.platform == "darwin":
            import subprocess
            result = subprocess.run(
                ["sysctl", "-n", "machdep.cpu.brand_string"],
                capture_output=True, text=True, timeout=5,
            )
            return result.stdout.strip() or platform.processor() or "unknown"
        return platform.processor() or "unknown"
    except Exception:
        return "unknown"


def _probe_torch() -> dict:
    """Safely probe torch availability and CUDA."""
    info: dict = {
        "torch_available": False,
        "torch_cuda_available": False,
        "cuda_device_name": None,
        "cuda_device_count": 0,
    }
    try:
        import torch
        info["torch_available"] = True
        info["torch_version"] = torch.__version__
        info["torch_cuda_available"] = torch.cuda.is_available()
        if torch.cuda.is_available():
            info["cuda_device_count"] = torch.cuda.device_count()
            info["cuda_device_name"] = torch.cuda.get_device_name(0) if torch.cuda.device_count() > 0 else None
    except ImportError:
        pass
    except Exception:
        pass
    return info


def _probe_speech_module() -> dict:
    """Check SpeechModule / SpeechStreamService model status."""
    info: dict = {
        "streaming_asr_preloaded": "unknown",
        "offline_asr_preloaded": "unknown",
        "punctuation_preloaded": "unknown",
        "punctuation_fallback": "unknown",
        "device_in_use": "unknown",
    }
    try:
        from backend.services.speech_stream_service import stream_service
        status = stream_service.get_model_status()
        info["streaming_asr_preloaded"] = status.get("streaming_model", "unknown")
        info["offline_asr_preloaded"] = status.get("offline_model", "unknown")
        info["punctuation_preloaded"] = status.get("punctuation_model", "unknown")
        info["punctuation_fallback"] = status.get("punctuation_fallback", "unknown")
        # The stream_service singleton may have a loaded module
        if stream_service._speech_module is not None:
            info["speech_module_created"] = True
            info["speech_module_ready"] = stream_service._speech_module.ready
        else:
            info["speech_module_created"] = False
            info["speech_module_ready"] = False
    except Exception as exc:
        info["error_reading_speech_module"] = str(exc)

    # Device: all warmup functions default to device="cpu"
    # The speech module does not auto-detect CUDA.
    try:
        from backend.speech_module.stt_streaming import warmup_streaming
        info["streaming_default_device"] = "cpu (hardcoded in warmup_streaming)"
    except Exception:
        info["streaming_default_device"] = "unknown"

    info["device_in_use"] = "cpu (all warmup functions default to device='cpu')"
    return info


def _probe_translation_service() -> dict:
    """Check translation model service status."""
    info: dict = {
        "translation_model_enabled": False,
        "translation_service_preloaded": "unknown",
    }
    try:
        from backend.services.translation_model_service import is_translation_model_enabled
        info["translation_model_enabled"] = is_translation_model_enabled()
    except Exception:
        pass
    # Opus-MT model loading status
    try:
        from backend.services.translation_model_service import TranslationModelService
        svc = TranslationModelService.get_instance()
        info["translation_service_preloaded"] = svc.model is not None if hasattr(svc, "model") else "unknown"
    except Exception:
        info["translation_service_preloaded"] = "not_loaded"
    return info


def generate_report() -> dict:
    """Generate the full device and model configuration report."""
    report: dict = {
        "report_type": "speech-latency-device-report",
        "task": "128A",
        "generated_at": None,  # filled at end
        "python": {
            "version": sys.version,
            "executable": sys.executable,
        },
        "os": {
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
        },
        "cpu": {
            "info": _get_cpu_info(),
        },
        "torch": _probe_torch(),
        "speech_module": _probe_speech_module(),
        "translation_service": _probe_translation_service(),
        "conclusion": {
            "runs_on_cpu": True,
            "runs_on_cuda": False,
            "notes": [],
        },
    }

    # Build conclusion
    torch_info = report["torch"]
    sm_info = report["speech_module"]

    if torch_info.get("torch_available"):
        report["conclusion"]["torch_available"] = True
        if torch_info.get("torch_cuda_available"):
            report["conclusion"]["runs_on_cpu"] = False
            report["conclusion"]["runs_on_cuda"] = True
            report["conclusion"]["notes"].append(
                f"CUDA is available: {torch_info['cuda_device_name']} "
                f"(count={torch_info['cuda_device_count']}), but speech warmup "
                "functions hardcode device='cpu'."
            )
        else:
            report["conclusion"]["notes"].append("CUDA is NOT available (no GPU or no torch CUDA build).")
    else:
        report["conclusion"]["torch_available"] = False
        report["conclusion"]["notes"].append("torch is not installed in this environment.")

    # Summarize model loading state
    for key in ("streaming_asr_preloaded", "offline_asr_preloaded", "punctuation_preloaded"):
        val = sm_info.get(key, "unknown")
        report["conclusion"]["notes"].append(f"{key}: {val}")

    from datetime import datetime, timezone
    report["generated_at"] = datetime.now(timezone.utc).isoformat()

    return report


def main() -> None:
    report = generate_report()
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)
    print(f"Device report written to {REPORT_PATH}")
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
