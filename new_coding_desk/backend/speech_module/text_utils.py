"""Text normalization and CER/WER computation."""

from __future__ import annotations
import re
import unicodedata
from difflib import SequenceMatcher


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


def normalize_english_display(text: str) -> str:
    """Normalize model-provided English spacing without inventing words.

    SenseVoice already supplies English punctuation.  This helper deliberately
    avoids guessing where a malformed glued token should be split; it only
    removes whitespace before punctuation, collapses repeated whitespace and
    ensures punctuation is followed by one space when more text follows.
    """
    clean = unicodedata.normalize("NFKC", text or "")
    clean = re.sub(r"\s+", " ", clean).strip()
    clean = re.sub(r"\s+([,.;:!?])", r"\1", clean)
    clean = re.sub(r"([,.;:!?])(?=[A-Za-z0-9])", r"\1 ", clean)
    return clean


def normalize_english_sentence_final(text: str) -> str:
    """Normalize a sentence-final SenseVoice result for lyric display.

    SenseVoice supplies punctuation and true casing.  Only transport/control
    remnants and non-speech emoji are removed here; words, apostrophes and
    model-provided punctuation are intentionally preserved.
    """
    clean = re.sub(r"<\|[^|]+\|>", "", text or "")
    clean = re.sub(r"[\U0001F300-\U0001FAFF]", "", clean)
    clean = normalize_english_display(clean)
    clean = re.sub(r"([,.;:!?])\1+", r"\1", clean)
    return clean.strip()


# Zipformer is an online acoustic/word recognizer, not a punctuation or
# true-casing model.  Keep this deliberately conservative: it repairs the
# all-caps transport format and a small set of unambiguous English forms, but
# never guesses where glued words or commas should be.
_ENGLISH_PROPER_WORDS = frozenset({
    "american", "america", "britain", "british", "canada", "canadian",
    "chinese", "china", "english", "england", "france", "french",
    "germany", "german", "london", "thursday", "tuesday", "wednesday",
    "friday", "saturday", "sunday", "monday", "washington",
})
_ENGLISH_ACRONYMS = frozenset({"ai", "api", "asr", "cpu", "eu", "uk", "usa", "vad"})


def format_english_streaming_display(text: str, *, sentence_complete: bool = False) -> str:
    """Make Zipformer interim text readable without pretending it is final ASR.

    The local English streaming model emits upper-case word tokens and no
    punctuation.  Lowercasing is safe for ordinary words; sentence starts,
    pronoun ``I``, standard acronyms, and a short set of unambiguous names are
    restored.  A terminal period is introduced only after VAD has confirmed a
    sentence pause, never just because the interim grew longer.
    """
    clean = normalize_english_display(text).lower()
    if not clean:
        return ""

    def _restore_word(match: re.Match[str]) -> str:
        word = match.group(0)
        key = word.casefold()
        if key in _ENGLISH_ACRONYMS:
            return key.upper()
        if key in _ENGLISH_PROPER_WORDS:
            return key.capitalize()
        if key == "i" or key.startswith("i'"):
            return "I" + word[1:]
        return word

    clean = re.sub(r"[a-z]+(?:'[a-z]+)?", _restore_word, clean)
    # Capitalize only sentence starts already supported by punctuation. During
    # an unfinished stream this affects the first visible word only.
    clean = re.sub(
        r"(^|[.!?]\s+)([a-z])",
        lambda match: match.group(1) + match.group(2).upper(),
        clean,
    )
    if sentence_complete and clean[-1] not in ".!?":
        clean += "."
    return clean


def merge_english_display_with_history(previous: str, current: str) -> str:
    """Keep punctuation already shown when a Zipformer hypothesis grows.

    The online recognizer returns one cumulative punctuation-free hypothesis.
    After a VAD pause the UI has already shown a terminal period; this helper
    carries that boundary into the next cumulative hypothesis while appending
    only genuinely new whole words. If the recognizer revises the prefix, the
    latest hypothesis wins rather than duplicating or inventing text.
    """
    previous = format_english_streaming_display(previous)
    current = format_english_streaming_display(current)
    if not previous or not current:
        return current or previous

    def key(token: str) -> str:
        return re.sub(r"[^a-z0-9']", "", token.casefold())

    prev_tokens = previous.split()
    current_tokens = current.split()
    comparable_prev = [key(token) for token in prev_tokens]
    comparable_current = [key(token) for token in current_tokens]
    if len(comparable_current) < len(comparable_prev):
        return current
    prefix_len = len(comparable_prev)
    if comparable_current == comparable_prev:
        current_punctuation = sum(1 for char in current if char in ".!?;:,")
        previous_punctuation = sum(1 for char in previous if char in ".!?;:,")
        return current if current_punctuation > previous_punctuation else previous
    if comparable_current[:prefix_len] == comparable_prev:
        suffix = current_tokens[prefix_len:]
        return format_english_streaming_display(
            previous + (" " + " ".join(suffix) if suffix else ""),
        )
    return current


def merge_english_transcripts(previous: str, current: str) -> str:
    """Merge rolling English ASR snapshots at token boundaries.

    The rolling SenseVoice window may contain an overlap with the preceding
    snapshot.  Matching case-insensitively on complete whitespace-delimited
    tokens prevents both duplicated phrases and the character concatenation
    that previously produced strings such as ``thefirst``.
    """
    previous = normalize_english_display(previous)
    current = normalize_english_display(current)
    if not current:
        return previous
    if not previous:
        return current
    if current.casefold().startswith(previous.casefold()):
        return current

    prev_tokens = previous.split()
    current_tokens = current.split()
    comparable = lambda token: re.sub(r"[^a-z0-9']", "", token.casefold())
    prev_keys = [comparable(token) for token in prev_tokens]
    current_keys = [comparable(token) for token in current_tokens]
    limit = min(len(prev_tokens), len(current_tokens))
    overlap = 0
    for size in range(limit, 0, -1):
        if prev_keys[-size:] == current_keys[:size]:
            overlap = size
            break
    if overlap:
        return normalize_english_display(
            " ".join(prev_tokens + current_tokens[overlap:]),
        )
    # ASR may revise one or two words inside the overlap. Retain the stable
    # prefix when a sufficiently long nearby block still anchors both windows.
    matcher = SequenceMatcher(None, prev_keys, current_keys, autojunk=False)
    block = max(matcher.get_matching_blocks(), key=lambda item: item.size)
    if block.size >= 3 and block.b <= max(4, len(current_tokens) // 3):
        return normalize_english_display(" ".join(
            prev_tokens[:block.a] + current_tokens[block.b:],
        ))
    # Never append an unanchored full rolling window: that creates the severe
    # duplicated/glued subtitle failure this merger is designed to prevent.
    return current if len(current_tokens) >= len(prev_tokens) else previous


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
