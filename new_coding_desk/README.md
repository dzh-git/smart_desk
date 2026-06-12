# SmartDesk

SmartDesk is a local smart meeting-table demo. It includes a FastAPI backend,
a React/Vite frontend, SQLite persistence, realtime WebSocket synchronization,
local FunASR speech recognition, live captions, and optional local OPUS-MT
translation.

## Quick Start

Install backend dependencies:

```powershell
pip install -r requirements.txt
```

Install frontend dependencies:

```powershell
cd frontend
npm install
cd ..
```

Start the local demo:

```powershell
.\start.bat
```

Stop it:

```powershell
.\kill.bat
```

Default local URLs:

- frontend: `http://127.0.0.1:5173`
- backend: `http://127.0.0.1:8000`
- backend OpenAPI docs: `http://127.0.0.1:8000/docs`

## Useful Environment Variables

| Variable | Purpose |
|---|---|
| `ENABLE_DEMO_SEED=true` | Create demo data when the database is empty. |
| `ENABLE_DEMO_SEED_WHEN_NO_ACTIVE=true` | Create demo data when no active meeting exists. |
| `ENABLE_DEMO_SEAT_API=true` | Enable development-only seat occupy/vacate APIs. |
| `VITE_ENABLE_DEMO_CONTROLS=true` | Show frontend demo controls. |
| `ENABLE_TRANSLATION_MODEL=true` | Enable real OPUS-MT zh-en final translation. |
| `TRANSLATION_MODEL_PATH=...` | Override local translation model path. |
| `RUN_TRANSLATION_SMOKE=true` | Enable translation model smoke tests. |

## Main Folders

| Path | Purpose |
|---|---|
| `backend/` | FastAPI app, routers, services, repositories, models, WebSocket handlers. |
| `backend/speech_module/` | Current speech implementation: FunASR integration, punctuation, captions. |
| `frontend/` | React + Vite + TypeScript UI. |
| `docs/` | Current contracts, architecture, runbook, workflow, and ADR history. |
| `tests/` | Backend tests and speech fixtures. |
| `models/` | Local model weights and caches. Not tracked by git. |
| `.hf_cache/` | HuggingFace cache. Not tracked by git. |
| `真实语音数据集/` | Real Chinese speech sample dataset. Preserved for evaluation. |

## Documentation Map

| Document | Purpose |
|---|---|
| `docs/API_SPEC.md` | Current HTTP API contract and environment variables. |
| `docs/WEBSOCKET_PROTOCOL.md` | Meeting broadcast and speech uplink WebSocket contracts. |
| `docs/EVENT_BUS_SPEC.md` | Backend event names, publishers, and client handling rules. |
| `docs/DATABASE_SCHEMA.md` | SQLite tables and repository ownership. |
| `docs/system_architecture.md` | High-level runtime architecture and subsystem responsibilities. |
| `docs/DEMO_RUNBOOK.md` | Manual and automated demo validation steps. |
| `docs/DEFERRED_ISSUES.md` | Known non-blocking limitations. |
| `docs/AGENT_WORKFLOW.md` | Main-agent review and Claude Code implementation workflow. |
| `docs/FRONTEND_CONTROL_SPEC.md` | Freeze the current frontend control contract and deferred scope. |
| `docs/FRONTEND_INTERACTION_SPEC.md` | Describe the current frontend interaction, clearly distinguishing between what has already been implemented, what must be achieved in the next round, and deferred features. |
| `docs/FRONTEND_STATE_SPEC.md` | It distinguishes between facts already achieved, goals that must be accomplished in the next round, and deferred features. |
| `docs/adr/` | Historical architecture decision records. |
| `working/FRONTEND_FLOW.md` | the frontend implements a meeting system with list and room pages, where chairman and seat roles have different UI logic, WebSocket events drive real-time member and media status updates, and subtitle display supports ASR interim/final/translation results, though several management actions (muting, transferring chairman, kicking) and subtitle language settings remain unimplemented.. |
| `working/FRONTEND_CURRENT_STATE.md` | Record the current front-end facts and distinguish them from the next round's goals and deferred functions |


## Validation

Backend:

```powershell
pytest -q
```

Frontend:

```powershell
cd frontend
npm run typecheck
npm run lint
npm test -- --run
npm run build
npm run e2e:speech
```

## Current Speech Contract

- Speech uplink: `/ws/speech/{meeting_id}?seat=N`
- Meeting broadcast: `/ws/{meeting_id}?seat=N`
- Audio: PCM16 little-endian, 16 kHz, mono
- Interim events: `translation_interim`, not persisted, not translated
- Final events: `translation_final`, persisted in `translation_records`
- Auto-final: backend RMS endpoint detection
- Manual fallback: `end_hint`
- Optional translation: enabled by `ENABLE_TRANSLATION_MODEL=true`

## Notes

- Runtime databases, logs, and caches are disposable local artifacts.
- Model directories and real speech datasets must be preserved.