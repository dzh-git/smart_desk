# Task 022: Remove speech_history.db — Migrate to Unified SQLite

## Project Overview

- **Goal:** Migrate SmartDesk from direct callback architecture to EventBus-driven decoupled architecture
- **Architecture:** Router → Service → Repository → SQLite, with in-process EventBus for decoupling
- **Tech Stack:** Python 3.11+, SQLAlchemy 2.0, SQLite

## Task Objective

Remove `speech_module/history_store.py` and the standalone `speech_history.db`. Translation history is now persisted via `TranslationRepository` using the unified `smart_desk.db` (migration A3). Update `SpeechModule` to no longer accept a `history_store` parameter. Clean up all references.

This is Task 22 of 26.

---

**Files:**
- Modify: `D:\learning\smart_desktop\smart-desk\speech_module\speech_module.py`
- Modify: `D:\learning\smart_desktop\smart-desk\speech_module\__init__.py`
- Modify: `D:\learning\smart_desktop\smart-desk\backend\routers\translation.py`
- Delete: `D:\learning\smart_desktop\smart-desk\speech_module\history_store.py`

- [ ] **Step 1: Update SpeechModule to remove history_store dependency**

In `speech_module/speech_module.py`, remove `history_store` from `__init__`:
```python
# BEFORE:
def __init__(self, max_workers=4, history_store=None, mt_engine=None):

# AFTER:
def __init__(self, max_workers=4, mt_engine=None):
```

Remove any `self.history_store` assignments and all calls to `history_store.upsert()` and `get_next_segment_id()`. These are now handled by `TranslationService` and `TranslationRepository`.

- [ ] **Step 2: Update speech_module __init__.py**

Remove `HistoryStore` from exports if present:
```python
# Remove: from .history_store import HistoryStore
```

- [ ] **Step 3: Update translation.py to not pass history_store**

In `backend/routers/translation.py`:
```python
# BEFORE:
from speech_module.history_store import HistoryStore
history_store = HistoryStore("speech_history.db")
speech = SpeechModule(max_workers=4, history_store=history_store, mt_engine=mt_engine)

# AFTER:
speech = SpeechModule(max_workers=4, mt_engine=mt_engine)
```

Remove the `history_store.close()` call in the old lifespan cleanup.

- [ ] **Step 4: Update main.py lifespan cleanup**

Remove any remaining `history_store.close()` calls.

- [ ] **Step 5: Delete history_store.py and speech_history.db**

```bash
rm D:\learning\smart_desktop\smart-desk\speech_module\history_store.py
rm D:\learning\smart_desktop\smart-desk\speech_history.db 2>/dev/null || true
```

- [ ] **Step 6: Verify speech module still works**

```bash
cd D:\learning\smart_desktop\smart-desk && python -c "from speech_module import SpeechModule; sm = SpeechModule(max_workers=1); print('SpeechModule OK')"
```
Expected: SpeechModule OK

- [ ] **Step 7: Run speech module tests**

```bash
cd D:\learning\smart_desktop\smart-desk && pytest speech_module/tests/ -v
```
Expected: All tests pass (may need test updates if tests reference history_store directly)
