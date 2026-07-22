"""Prepare a small, reproducible bilingual latency dataset from Google FLEURS.

The script downloads only the FLEURS validation metadata and archives for
Mandarin Chinese and US English, extracts a deterministic subset, then builds
30-60 second sessions separated by short silences.  The resulting manifest is
designed for real-time PCM/WebSocket replay rather than model training.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import tarfile
import urllib.request
import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf


FLEURS_REVISION = "main"
FLEURS_BASE_URL = (
    "https://huggingface.co/datasets/google/fleurs/resolve/"
    f"{FLEURS_REVISION}/data"
)
FLEURS_LICENSE = "CC-BY-4.0"
LANGUAGES = {
    "zh": {"config": "cmn_hans_cn", "name": "Mandarin Chinese"},
    "en": {"config": "en_us", "name": "US English"},
}
SAMPLE_RATE = 16_000
SILENCE_SECONDS = 0.7


@dataclass(frozen=True)
class FleursRow:
    sentence_id: str
    filename: str
    transcription: str
    normalized_transcription: str
    num_samples: int
    gender: str

    @property
    def duration_seconds(self) -> float:
        return self.num_samples / SAMPLE_RATE


def _download(url: str, destination: Path) -> None:
    if destination.exists() and destination.stat().st_size > 0:
        print(f"  reuse {destination.name} ({destination.stat().st_size / 1e6:.1f} MB)")
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(destination.suffix + ".part")
    request = urllib.request.Request(url, headers={"User-Agent": "smartdesk-dataset-preparer/1.0"})
    print(f"  download {url}")
    with urllib.request.urlopen(request, timeout=120) as response, partial.open("wb") as output:
        total = int(response.headers.get("Content-Length", "0"))
        copied = 0
        while True:
            block = response.read(1024 * 1024)
            if not block:
                break
            output.write(block)
            copied += len(block)
            if total and copied % (25 * 1024 * 1024) < len(block):
                print(f"    {copied / 1e6:.0f}/{total / 1e6:.0f} MB")
    partial.replace(destination)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_rows(tsv_path: Path) -> list[FleursRow]:
    rows: list[FleursRow] = []
    with tsv_path.open("r", encoding="utf-8", newline="") as stream:
        reader = csv.reader(stream, delimiter="\t")
        for values in reader:
            if len(values) < 7:
                continue
            rows.append(
                FleursRow(
                    sentence_id=values[0],
                    filename=values[1],
                    transcription=values[2],
                    normalized_transcription=values[3],
                    num_samples=int(values[5]),
                    gender=values[6].lower(),
                )
            )
    return rows


def _select_rows(rows: list[FleursRow], count: int) -> list[FleursRow]:
    eligible = [row for row in rows if 4.0 <= row.duration_seconds <= 18.0]
    eligible.sort(key=lambda row: (row.duration_seconds, row.filename))
    if len(eligible) < count:
        raise RuntimeError(f"Only {len(eligible)} eligible FLEURS rows; requested {count}")

    chosen: list[FleursRow] = []
    used_sentences: set[str] = set()

    def take_spread(candidates: list[FleursRow], quota: int) -> None:
        if not candidates or quota <= 0:
            return
        target = len(chosen) + quota
        for position in range(quota * 3):
            index = min(len(candidates) - 1, position * len(candidates) // (quota * 3))
            row = candidates[index]
            if row.sentence_id in used_sentences:
                continue
            chosen.append(row)
            used_sentences.add(row.sentence_id)
            if len(chosen) >= target:
                return

    # Balance male/female clips and spread each group across the duration range.
    female = [row for row in eligible if row.gender == "female"]
    male = [row for row in eligible if row.gender == "male"]
    take_spread(female, count // 2)
    female_count = len(chosen)
    take_spread(male, count - female_count)
    if len(chosen) < count:
        take_spread(eligible, count - len(chosen))
    if len(chosen) == count:
        return sorted(chosen, key=lambda item: item.filename)
    raise RuntimeError(f"Could not select {count} distinct sentences")


def _extract_selected(archive: Path, selected: list[FleursRow], output_dir: Path) -> None:
    wanted = {row.filename for row in selected}
    found: set[str] = set()
    output_dir.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "r:gz") as source:
        for member in source:
            filename = Path(member.name).name
            if filename not in wanted or not member.isfile():
                continue
            destination = output_dir / filename
            extracted = source.extractfile(member)
            if extracted is None:
                continue
            with extracted, destination.open("wb") as output:
                shutil.copyfileobj(extracted, output)
            found.add(filename)
    missing = sorted(wanted - found)
    if missing:
        raise RuntimeError(f"Archive {archive.name} is missing selected files: {missing[:3]}")


def _validate_wave(path: Path) -> tuple[int, int, int]:
    with wave.open(str(path), "rb") as stream:
        channels = stream.getnchannels()
        width = stream.getsampwidth()
        rate = stream.getframerate()
        frames = stream.getnframes()
    if (channels, width, rate) != (1, 2, SAMPLE_RATE):
        raise RuntimeError(
            f"Unsupported source format for {path.name}: "
            f"channels={channels}, width={width}, rate={rate}"
        )
    return rate, frames, width


def _normalize_source_waves(paths: list[Path]) -> None:
    """Convert upstream float WAV files to the application's PCM16 contract."""

    for path in paths:
        data, rate = sf.read(str(path), dtype="float32", always_2d=True)
        if rate != SAMPLE_RATE:
            raise RuntimeError(f"Unexpected sample rate for {path.name}: {rate}")
        if data.shape[1] > 1:
            data = np.mean(data, axis=1, keepdims=True)
        temporary = path.with_suffix(".pcm16.wav")
        sf.write(
            str(temporary),
            data[:, 0],
            SAMPLE_RATE,
            subtype="PCM_16",
            format="WAV",
        )
        temporary.replace(path)


def _build_sessions(
    language: str,
    rows: list[FleursRow],
    audio_dir: Path,
    sessions_dir: Path,
    clips_per_session: int,
) -> list[dict]:
    sessions_dir.mkdir(parents=True, exist_ok=True)
    silence_frames = int(SAMPLE_RATE * SILENCE_SECONDS)
    silence = b"\x00\x00" * silence_frames
    sessions: list[dict] = []

    for session_index, start in enumerate(range(0, len(rows), clips_per_session), 1):
        group = rows[start : start + clips_per_session]
        if len(group) < 2:
            break
        output_path = sessions_dir / f"{language}_session_{session_index:02d}.wav"
        segments: list[dict] = []
        current_frame = 0
        with wave.open(str(output_path), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(SAMPLE_RATE)
            for clip_index, row in enumerate(group):
                clip_path = audio_dir / row.filename
                _, frame_count, _ = _validate_wave(clip_path)
                with wave.open(str(clip_path), "rb") as source:
                    pcm = source.readframes(frame_count)
                start_second = current_frame / SAMPLE_RATE
                output.writeframesraw(pcm)
                current_frame += frame_count
                segments.append(
                    {
                        "audio": clip_path.as_posix(),
                        "start_seconds": round(start_second, 3),
                        "end_seconds": round(current_frame / SAMPLE_RATE, 3),
                        "transcript": row.transcription,
                        "normalized_transcript": row.normalized_transcription,
                        "gender": row.gender,
                    }
                )
                if clip_index != len(group) - 1:
                    output.writeframesraw(silence)
                    current_frame += silence_frames

        sessions.append(
            {
                "audio": output_path.as_posix(),
                "language": language,
                "requested_language_modes": [language, "auto"],
                "duration_seconds": round(current_frame / SAMPLE_RATE, 3),
                "sample_rate": SAMPLE_RATE,
                "transcript": ("" if language == "zh" else " ").join(
                    row.transcription for row in group
                ),
                "normalized_transcript": ("" if language == "zh" else " ").join(
                    row.normalized_transcription for row in group
                ),
                "segments": segments,
                "scenario": "FLEURS validation clips joined with 0.7 seconds of silence",
            }
        )
    return sessions


def prepare(output_dir: Path, samples_per_language: int, clips_per_session: int) -> Path:
    output_dir = output_dir.resolve()
    manifest_path = output_dir / "manifest.json"
    if manifest_path.exists():
        existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        session_paths = [output_dir / item["audio"] for item in existing.get("sessions", [])]
        if session_paths and all(path.is_file() for path in session_paths):
            print(f"Dataset already prepared: {manifest_path}")
            from backend.scripts.prepare_speech_latency_stress_sessions import augment

            return augment(output_dir)
    downloads_dir = output_dir / ".downloads"
    all_sessions: list[dict] = []
    source_files: list[dict] = []

    for language, info in LANGUAGES.items():
        config = info["config"]
        print(f"[{language}] {info['name']} ({config})")
        tsv_path = downloads_dir / f"{config}-dev.tsv"
        archive_path = downloads_dir / f"{config}-dev.tar.gz"
        _download(f"{FLEURS_BASE_URL}/{config}/dev.tsv", tsv_path)
        rows = _select_rows(_read_rows(tsv_path), samples_per_language)
        _download(f"{FLEURS_BASE_URL}/{config}/audio/dev.tar.gz", archive_path)

        language_audio_dir = output_dir / "audio" / language
        _extract_selected(archive_path, rows, language_audio_dir)
        _normalize_source_waves([language_audio_dir / row.filename for row in rows])
        sessions = _build_sessions(
            language,
            rows,
            language_audio_dir,
            output_dir / "sessions",
            clips_per_session,
        )
        all_sessions.extend(sessions)
        source_files.extend(
            {
                "language": language,
                "filename": row.filename,
                "duration_seconds": round(row.duration_seconds, 3),
                "gender": row.gender,
                "transcript": row.transcription,
                "normalized_transcript": row.normalized_transcription,
            }
            for row in rows
        )
        archive_path.unlink(missing_ok=True)

    # Store paths relative to the dataset root so the dataset remains movable.
    for session in all_sessions:
        session["audio"] = Path(session["audio"]).relative_to(output_dir).as_posix()
        for segment in session["segments"]:
            segment["audio"] = Path(segment["audio"]).relative_to(output_dir).as_posix()

    manifest = {
        "dataset": "google/fleurs",
        "revision": FLEURS_REVISION,
        "split": "validation (upstream dev)",
        "license": FLEURS_LICENSE,
        "source": "https://huggingface.co/datasets/google/fleurs",
        "paper": "https://arxiv.org/abs/2205.12446",
        "sample_rate": SAMPLE_RATE,
        "silence_between_clips_seconds": SILENCE_SECONDS,
        "session_count": len(all_sessions),
        "sessions": all_sessions,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "utterances.json").write_text(
        json.dumps(source_files, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output_dir / "SOURCE.md").write_text(
        "# Dataset source\n\n"
        "This latency subset is derived from Google FLEURS (`cmn_hans_cn` and "
        "`en_us`, upstream `dev` split). FLEURS is distributed under CC BY 4.0.\n\n"
        "- Dataset: https://huggingface.co/datasets/google/fleurs\n"
        "- Paper: https://arxiv.org/abs/2205.12446\n"
        "- License: https://creativecommons.org/licenses/by/4.0/\n\n"
        "The audio is unmodified except that selected clips are also concatenated "
        "with 0.7 seconds of digital silence for real-time streaming tests.\n",
        encoding="utf-8",
    )
    checksums = [
        f"{_sha256(path)}  {path.relative_to(output_dir).as_posix()}"
        for path in sorted((output_dir / "sessions").glob("*.wav"))
    ]
    (output_dir / "SHA256SUMS.txt").write_text("\n".join(checksums) + "\n", encoding="utf-8")
    print(f"Prepared {len(all_sessions)} sessions at {output_dir}")
    from backend.scripts.prepare_speech_latency_stress_sessions import augment

    return augment(output_dir)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("working/speech_latency_dataset/fleurs_zh_en"),
    )
    parser.add_argument("--samples-per-language", type=int, default=15)
    parser.add_argument("--clips-per-session", type=int, default=5)
    args = parser.parse_args()
    if args.samples_per_language < 2 or args.clips_per_session < 2:
        parser.error("sample and clip counts must both be at least 2")
    prepare(args.output, args.samples_per_language, args.clips_per_session)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
