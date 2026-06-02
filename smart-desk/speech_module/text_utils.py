"""Text normalization and CER/WER computation."""

from __future__ import annotations
import re
import unicodedata


def normalize_zh(text: str) -> str:
    """Chinese: remove punctuation/spaces, fullwidth→halfwidth, NFKC."""
    text = unicodedata.normalize("NFKC", text)
    # Fullwidth ASCII → halfwidth
    result = []
    for ch in text:
        code = ord(ch)
        if 0xFF01 <= code <= 0xFF5E:
            result.append(chr(code - 0xFEE0))
        elif 0x3000 == code:
            result.append(" ")
        else:
            result.append(ch)
    text = "".join(result)
    # Remove punctuation and whitespace (keep Chinese chars, letters, digits)
    text = re.sub(r"[^一-鿿㐀-䶿a-zA-Z0-9]", "", text)
    return text


def normalize_en(text: str) -> str:
    """English: lowercase, remove punctuation, collapse whitespace."""
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def normalize(text: str, lang: str) -> str:
    if lang == "zh":
        return normalize_zh(text)
    return normalize_en(text)


def edit_distance(a: str, b: str) -> int:
    """Levenshtein distance between two strings (character-level)."""
    if len(a) < len(b):
        a, b = b, a
    if len(b) == 0:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        curr = [i]
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            curr.append(min(
                curr[-1] + 1,
                prev[j] + 1,
                prev[j - 1] + cost,
            ))
        prev = curr
    return prev[-1]


def compute_cer(reference: str, hypothesis: str) -> dict:
    """Character Error Rate. Returns {cer, S, D, I, N}."""
    return _compute_error_rate(reference, hypothesis, char_level=True)


def compute_wer(reference: str, hypothesis: str) -> dict:
    """Word Error Rate. Returns {wer, S, D, I, N}."""
    return _compute_error_rate(reference, hypothesis, char_level=False)


def _compute_error_rate(ref: str, hyp: str, char_level: bool) -> dict:
    if not ref:
        key = "cer" if char_level else "wer"
        n = len(hyp) if char_level else (len(hyp.split()) if hyp.strip() else 0)
        return {key: 1.0 if n > 0 else 0.0, "S": 0, "D": 0, "I": n, "N": 0}

    if char_level:
        ref_seq = list(ref)
        hyp_seq = list(hyp)
    else:
        ref_seq = ref.split()
        hyp_seq = hyp.split()

    n = len(ref_seq)
    m = len(hyp_seq)
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        dp[i][0] = i
    for j in range(m + 1):
        dp[0][j] = j

    for i in range(1, n + 1):
        for j in range(1, m + 1):
            cost = 0 if ref_seq[i - 1] == hyp_seq[j - 1] else 1
            dp[i][j] = min(
                dp[i - 1][j] + 1,
                dp[i][j - 1] + 1,
                dp[i - 1][j - 1] + cost,
            )

    # Backtrace for S/D/I
    i, j = n, m
    s = d = ins = 0
    while i > 0 or j > 0:
        if i > 0 and j > 0 and dp[i][j] == dp[i - 1][j - 1] + (0 if ref_seq[i - 1] == hyp_seq[j - 1] else 1):
            if ref_seq[i - 1] != hyp_seq[j - 1]:
                s += 1
            i -= 1
            j -= 1
        elif i > 0 and dp[i][j] == dp[i - 1][j] + 1:
            d += 1
            i -= 1
        else:
            ins += 1
            j -= 1

    key = "cer" if char_level else "wer"
    return {key: (s + d + ins) / n, "S": s, "D": d, "I": ins, "N": n}


def common_prefix_len(a: str, b: str) -> int:
    """Number of leading characters matching between two strings."""
    n = min(len(a), len(b))
    for i in range(n):
        if a[i] != b[i]:
            return i
    return n


def detect_language(text: str) -> str:
    """Heuristic language detection: count CJK vs Latin characters.

    Returns 'zh' if CJK characters outnumber Latin letters, 'en' otherwise.
    """
    cjk = sum(1 for c in text if '一' <= c <= '鿿')
    latin = sum(1 for c in text if c.isascii() and c.isalpha())
    return "zh" if cjk > latin else "en"


def text_similarity(a: str, b: str) -> float:
    """Character-level similarity in [0, 1]. 1.0 = identical strings."""
    if not a and not b:
        return 1.0
    max_len = max(len(a), len(b))
    if max_len == 0:
        return 1.0
    return 1.0 - edit_distance(a, b) / max_len


def merge_texts(prev: str, chunk: str) -> str:
    """Merge incremental chunk text with previous text, removing overlap.

    Strategy:
      - If chunk starts with prev, use chunk (growth).
      - If prev is prefix of chunk, use chunk.
      - Otherwise find the longest suffix of prev that matches a prefix
        of chunk, and concatenate without the overlap.
      - Fallback: concatenate directly.
    """
    if not chunk:
        return prev
    if not prev:
        return chunk
    if chunk.startswith(prev):
        return chunk

    max_overlap = min(len(prev), len(chunk))
    for overlap_len in range(max_overlap, 0, -1):
        if prev[-overlap_len:] == chunk[:overlap_len]:
            return prev + chunk[overlap_len:]
    return prev + chunk
