"""
STT pipeline test — compare VAD segmentation + SenseVoiceSmall output against ground truth.
Usage: python test_stt.py
"""
import os, sys, time, json, re, math
import numpy as np
import soundfile as sf

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from routers.translation import _get_stt_model, _transcribe_sensevoice, preload_models

# ── Config ──
SAMPLE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '语音测试样本')
WAV_DIR = os.path.join(SAMPLE_DIR, 'wav')

TEST_CASES = [
    {
        'name': '测试声音',
        'audio': os.path.join(WAV_DIR, '测试声音.wav'),
        'text': os.path.join(SAMPLE_DIR, '测试声音文本.txt'),
        'priority': 1,
    },
    {
        'name': '测试声音2',
        'audio': os.path.join(WAV_DIR, '测试声音2.wav'),
        'text': os.path.join(SAMPLE_DIR, '测试声音文本2.txt'),
        'priority': 1,
    },
    {
        'name': '测试声音_pro',
        'audio': os.path.join(WAV_DIR, '测试声音_pro.wav'),
        'text': os.path.join(SAMPLE_DIR, '测试声音文本_pro.txt'),
        'priority': 2,
    },
]


def load_ground_truth(path):
    """Load ground truth text — one line = one utterance segment."""
    with open(path, 'r', encoding='utf-8') as f:
        lines = [l.strip() for l in f.readlines() if l.strip()]
    return lines


def energy_vad(audio, sr, min_silence_ms=500, silence_thresh_db=-35, min_speech_ms=200,
               pre_pad_ms=100, post_pad_ms=100):
    """
    Energy-based VAD. Returns list of (start_sample, end_sample) segments.
    Similar logic to vad-web but energy-based instead of neural.

    Parameters:
        min_silence_ms: silence gap to split utterances (key tuning param)
        silence_thresh_db: dB below peak to consider as silence
        min_speech_ms: minimum speech segment duration
    """
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    audio = audio.astype(np.float32)

    # RMS energy in sliding windows
    frame_ms = 30
    frame_samples = int(sr * frame_ms / 1000)
    hop_samples = frame_samples // 3  # 10ms hop

    n_frames = max(1, (len(audio) - frame_samples) // hop_samples + 1)
    rms = np.zeros(n_frames)
    for i in range(n_frames):
        start = i * hop_samples
        chunk = audio[start:start + frame_samples]
        rms[i] = np.sqrt(np.mean(chunk ** 2)) + 1e-10

    rms_db = 20 * np.log10(rms / np.max(rms) + 1e-10)

    # Binary speech/silence mask
    is_speech = rms_db > silence_thresh_db

    min_silence_frames = int(min_silence_ms / 10)  # 10ms per frame
    min_speech_frames = max(1, int(min_speech_ms / 10))

    # Merge short gaps within speech
    segments = []
    in_speech = False
    speech_start = 0
    silence_count = 0

    for i in range(len(is_speech)):
        if is_speech[i]:
            silence_count = 0
            if not in_speech:
                speech_start = i * hop_samples
                in_speech = True
        else:
            if in_speech:
                silence_count += 1
                if silence_count >= min_silence_frames:
                    speech_end = (i - min_silence_frames) * hop_samples + frame_samples
                    segments.append((speech_start, speech_end))
                    in_speech = False

    if in_speech:
        segments.append((speech_start, len(audio)))

    # Filter short segments and add padding
    result = []
    for start, end in segments:
        dur_ms = (end - start) / sr * 1000
        if dur_ms < min_speech_ms:
            continue
        pad_s = int(pre_pad_ms / 1000 * sr)
        pad_e = int(post_pad_ms / 1000 * sr)
        result.append((max(0, start - pad_s), min(len(audio), end + pad_e)))

    return result


def run_stt(audio_path, segments=None):
    """Run STT on audio or audio segments. Returns transcribed text."""
    if segments is None:
        return _transcribe_sensevoice(audio_path)

    results = []
    full_audio, sr = sf.read(audio_path, dtype='float32')

    for i, (start, end) in enumerate(segments):
        seg = full_audio[start:end]
        # Write segment to temp file
        import tempfile
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp:
            sf.write(tmp.name, seg, sr)
            text = _transcribe_sensevoice(tmp.name)
            if text:
                results.append(text)
            try:
                os.unlink(tmp.name)
            except:
                pass

    return results


def normalize_text(text):
    """Remove punctuation, extra spaces for comparison."""
    # Remove all punctuation except Chinese characters, letters, digits
    text = re.sub(r'[，。！？、；：""''「」『』【】（）\s,.!?;:\"\'\(\)\[\]]+', '', text)
    # Remove SenseVoice tags
    text = re.sub(r'<\|[^|]+\|>', '', text)
    return text.strip()


def levenshtein_ratio(s1, s2):
    """Character-level similarity ratio."""
    if not s1 and not s2:
        return 1.0
    if not s1 or not s2:
        return 0.0

    m, n = len(s1), len(s2)
    dp = [[0] * (n + 1) for _ in range(m + 1)]
    for i in range(m + 1):
        dp[i][0] = i
    for j in range(n + 1):
        dp[0][j] = j

    for i in range(1, m + 1):
        for j in range(1, n + 1):
            cost = 0 if s1[i-1] == s2[j-1] else 1
            dp[i][j] = min(dp[i-1][j] + 1, dp[i][j-1] + 1, dp[i-1][j-1] + cost)

    return 1 - dp[m][n] / max(m, n)


def evaluate_segmentation(transcribed_segments, ground_truth_lines):
    """
    Evaluate how well VAD segmentation matches ground truth.
    Returns alignment score and detailed comparison.
    """
    n_trans = len(transcribed_segments)
    n_gt = len(ground_truth_lines)

    # Normalize all texts
    trans_norm = [normalize_text(t) for t in transcribed_segments]
    gt_norm = [normalize_text(t) for t in ground_truth_lines]

    # Simple alignment: merge all trans to one string, compare char-level
    trans_full = ''.join(trans_norm)
    gt_full = ''.join(gt_norm)

    char_sim = levenshtein_ratio(trans_full, gt_full)

    # Segment count match
    count_ratio = min(n_trans, n_gt) / max(n_trans, n_gt) if max(n_trans, n_gt) > 0 else 1.0

    return {
        'trans_segments': n_trans,
        'gt_segments': n_gt,
        'count_ratio': count_ratio,
        'char_similarity': char_sim,
        'trans_full': trans_full,
        'gt_full': gt_full,
        'details': list(zip(transcribed_segments, trans_norm)),
    }


def test_vad_params(audio_path, gt_lines):
    """Test multiple VAD parameter combinations."""
    audio, sr = sf.read(audio_path, dtype='float32')

    # Parameter grid
    silence_gaps = [300, 500, 700, 900, 1200, 1500]  # ms
    silence_thresholds = [-40, -35, -30, -25]  # dB

    results = []
    for gap in silence_gaps:
        for thresh in silence_thresholds:
            segs = energy_vad(audio, sr, min_silence_ms=gap, silence_thresh_db=thresh,
                            min_speech_ms=200, pre_pad_ms=200, post_pad_ms=100)

            result = {
                'gap_ms': gap,
                'thresh_db': thresh,
                'n_segments': len(segs),
                'segments': [(s/sr, e/sr) for s, e in segs],
            }

            # Compute segment duration stats
            if segs:
                durs = [(e - s) / sr * 1000 for s, e in segs]
                result['dur_min'] = min(durs)
                result['dur_max'] = max(durs)
                result['dur_mean'] = np.mean(durs)
            else:
                result['dur_min'] = result['dur_max'] = result['dur_mean'] = 0

            results.append(result)

    return results


# ── Main ──

def main():
    print("=" * 70)
    print("STT Pipeline Test — VAD + SenseVoiceSmall")
    print("=" * 70)

    # Preload model
    print("\n[1] Loading STT model...")
    _get_stt_model()
    print("    Model ready.")

    for tc in TEST_CASES:
        if not os.path.exists(tc['audio']):
            print(f"\n[SKIP] {tc['name']}: audio not found")
            continue

        print(f"\n{'='*70}")
        print(f"[{tc['name']}] Priority={tc['priority']}")
        print(f"{'='*70}")

        # Load ground truth
        gt_lines = load_ground_truth(tc['text'])
        print(f"Ground truth: {len(gt_lines)} segments")
        for i, line in enumerate(gt_lines[:5]):
            print(f"  [{i}] {line[:60]}{'...' if len(line) > 60 else ''}")
        if len(gt_lines) > 5:
            print(f"  ... ({len(gt_lines)} total)")

        # Load audio
        audio, sr = sf.read(tc['audio'], dtype='float32')
        print(f"Audio: {len(audio)/sr:.1f}s, {sr}Hz")

        # 1. Test full audio STT (no VAD)
        print(f"\n--- Full audio STT (no VAD) ---")
        full_start = time.time()
        full_text = run_stt(tc['audio'])
        full_elapsed = time.time() - full_start
        print(f"  Time: {full_elapsed:.1f}s")
        print(f"  Output: {full_text[:120]}{'...' if len(full_text) > 120 else ''}")

        # Compare with ground truth
        full_norm = normalize_text(full_text)
        gt_full = ''.join([normalize_text(l) for l in gt_lines])
        full_sim = levenshtein_ratio(full_norm, gt_full)
        print(f"  Full-audio char similarity: {full_sim:.3f}")

        # 2. Test VAD parameter sweep
        print(f"\n--- VAD parameter sweep ---")
        vad_results = test_vad_params(tc['audio'], gt_lines)

        # Score each config by segment count match
        best = None
        for r in vad_results:
            count_diff = abs(r['n_segments'] - len(gt_lines))
            score = -count_diff  # closer to 0 is better
            if best is None or score > best['score']:
                best = {**r, 'score': score}

        print(f"  Target segments: {len(gt_lines)}")
        print(f"  Best VAD config: gap={best['gap_ms']}ms, thresh={best['thresh_db']}dB")
        print(f"  Best segment count: {best['n_segments']}")
        print(f"  Duration range: {best['dur_min']:.0f}-{best['dur_max']:.0f}ms (mean {best['dur_mean']:.0f}ms)")

        # Show all configs sorted by score
        sorted_results = sorted(vad_results, key=lambda r: abs(r['n_segments'] - len(gt_lines)))
        print(f"\n  Top 5 VAD configs (by segment count match):")
        print(f"  {'gap_ms':>7} {'thresh':>7} {'n_seg':>6} {'dur_mean':>8} {'count_err':>10}")
        print(f"  {'-'*45}")
        for r in sorted_results[:5]:
            err = abs(r['n_segments'] - len(gt_lines))
            print(f"  {r['gap_ms']:>7} {r['thresh_db']:>7} {r['n_segments']:>6} {r['dur_mean']:>7.0f}ms {err:>10}")

        # 3. Run STT with best VAD segmentation and evaluate
        print(f"\n--- STT with best VAD (gap={best['gap_ms']}ms) ---")
        best_segs = energy_vad(audio, sr,
                               min_silence_ms=best['gap_ms'],
                               silence_thresh_db=best['thresh_db'],
                               min_speech_ms=200,
                               pre_pad_ms=200, post_pad_ms=100)

        stt_results = run_stt(tc['audio'], best_segs)
        print(f"  Transcribed {len(stt_results)} segments:")
        for i, txt in enumerate(stt_results):
            gt_i = gt_lines[i] if i < len(gt_lines) else '(none)'
            sim = levenshtein_ratio(normalize_text(txt), normalize_text(gt_i))
            print(f"  [{i}] STT: {txt[:60]}{'...' if len(txt) > 60 else ''}")
            print(f"      GT:  {gt_i[:60]}{'...' if len(gt_i) > 60 else ''}")
            print(f"      sim: {sim:.3f}")

        # 4. Also test with a few different gap values
        print(f"\n--- Multi-gap comparison ---")
        for gap in [500, 700, 900, 1200]:
            segs = energy_vad(audio, sr, min_silence_ms=gap, silence_thresh_db=-35,
                            min_speech_ms=200, pre_pad_ms=200, post_pad_ms=100)
            results = run_stt(tc['audio'], segs)
            merged = ''.join([normalize_text(t) for t in results])
            sim = levenshtein_ratio(merged, gt_full)
            print(f"  gap={gap}ms: {len(segs)} segs, {len(results)} transcribed, char_sim={sim:.3f}")

        if tc['priority'] == 1:
            # 5. Detailed analysis for priority cases
            print(f"\n--- Detailed segment timing ---")
            # Test with 700ms gap (typical default)
            segs = energy_vad(audio, sr, min_silence_ms=700, silence_thresh_db=-35,
                            min_speech_ms=200, pre_pad_ms=200, post_pad_ms=100)
            print(f"  Segments with 700ms gap:")
            for i, (s, e) in enumerate(segs):
                dur = (e - s) / sr
                print(f"  [{i}] {s/sr:.2f}s - {e/sr:.2f}s ({dur:.1f}s)")


if __name__ == '__main__':
    main()
