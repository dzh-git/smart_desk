# Task 025: Final Cleanup — Remove Dead Code, Update Requirements

## Project Overview

- **Goal:** Migrate SmartDesk from direct callback architecture to EventBus-driven decoupled architecture
- **Architecture:** Router → Service → Repository → SQLite, with in-process EventBus for decoupling
- **Tech Stack:** Python 3.11+, FastAPI, SQLAlchemy 2.0, SQLite, Vue 3

## Task Objective

Final cleanup pass: remove unused imports, remove the now-deprecated `desk_coordinator.py` (or reduce to compatibility stub), update `requirements.txt`, verify the frontend builds with new API paths, ensure all docs references are consistent.

This is Task 25 of 26.

---

**Files:**
- Modify: `D:\learning\smart_desktop\smart-desk\backend\services\desk_coordinator.py` (reduce to stub)
- Modify: `D:\learning\smart_desktop\smart-desk\backend\requirements.txt`
- Modify: `D:\learning\smart_desktop\smart-desk\frontend\src\main.js`
- Verify: `D:\learning\smart_desktop\smart-desk\frontend\src\App.vue`

- [ ] **Step 1: Reduce desk_coordinator.py to compatibility stub**

Replace `desk_coordinator.py` content with a minimal stub that doesn't prevent imports:
```python
# backend/services/desk_coordinator.py
# DEPRECATED: Replaced by Service layer + EventBus bridge.
# Kept as compatibility stub during migration.

class DeskCoordinator:
    """Deprecated — use Service classes and EventBus directly."""
    def __init__(self):
        pass

# Compatibility singleton
desk = DeskCoordinator()
```

Remove all imports from `desk_coordinator` in other files. The only remaining reference should be in files that haven't been fully migrated yet.

- [ ] **Step 2: Remove desk_coordinator imports from all files**

Check all files for remaining imports:
```bash
cd D:\learning\smart_desktop\smart-desk && grep -rn "desk_coordinator\|from.*desk import\|import.*desk" backend/ --include="*.py"
```

For each found reference, migrate to use the appropriate Service or remove if unused.

- [ ] **Step 3: Update requirements.txt**

Verify `backend/requirements.txt` contains all needed packages:
```
fastapi>=0.109.0
uvicorn[standard]>=0.27.0
sqlalchemy>=2.0.0
pydantic>=2.0.0
python-multipart>=0.0.5
pyserial>=3.5
funasr>=1.0.0
modelscope>=1.10.0
soundfile>=0.12.0
scipy>=1.10.0
numpy>=1.24.0
transformers>=4.40.0
sentencepiece>=0.2.0
```

- [ ] **Step 4: Clean frontend — remove unused old API methods**

In `frontend/src/main.js` or wherever API methods were previously used, remove any imports or usages of old function names.

- [ ] **Step 5: Verify full frontend build**

```bash
cd D:\learning\smart_desktop\smart-desk\frontend && npx vite build
```
Expected: Build succeeds with no errors and no dead-code warnings about old API paths.

- [ ] **Step 6: Verify full backend startup**

```bash
cd D:\learning\smart_desktop\smart-desk && timeout 5 python -c "
from backend.main import app
print('Backend OK - routes:', len(app.routes))
" 2>&1
```
Expected: Backend OK

- [ ] **Step 7: Run complete test suite one final time**

```bash
cd D:\learning\smart_desktop\smart-desk && pytest tests/ -v --tb=short 2>&1
```
Expected: All tests pass

- [ ] **Step 8: Git diff review**

```bash
cd D:\learning\smart_desktop\smart-desk && git diff --stat
```
Review the summary of changed files to ensure completeness.
