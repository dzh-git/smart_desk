"""speech_module — production speech recognition and translation.

Provides SpeechModule facade. Internal modules (HistoryStore, SentenceMerger,
punctuation, VAD, STT backends) are implementation details not part of the
public API contract.

Usage:
    from speech_module import SpeechModule
    import speech_module.text_utils as tu

    sm = SpeechModule(history_store=HistoryStore("history.db"))
    sm.preload()
    text = sm.transcribe("audio.wav")
"""

from .speech_module import SpeechModule

__all__ = ["SpeechModule"]
