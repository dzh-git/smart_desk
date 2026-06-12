# SmartDesk Agent Workflow

This project uses a main-agent review workflow with Claude Code as the
implementation agent.

## Roles

Main agent:

- owns planning, scope control, and acceptance decisions;
- reviews task reports and code/test results before the next task starts;
- writes or approves interface contracts before implementation;
- keeps task prompts narrow and decision-complete.

Claude Code:

- implements the assigned task directly;
- does not delegate to other agents;
- reads only the allowed inputs listed in the prompt;
- modifies only the allowed files listed in the prompt;
- runs the required tests;
- reports changes, test results, blockers, and deferred issues.

## Prompt Requirements

Each Claude Code prompt must include:

- task goal;
- allowed read paths;
- allowed write paths;
- forbidden paths;
- explicit reminder that root `speech_module/` is old reference code and must
  not be modified unless the task explicitly permits it;
- required verification commands;
- expected feedback format;
- rules for deferred, non-blocking issues.

## Documentation Rules

- Generated task reports and project docs should be English-only unless Chinese
  is explicitly required.
- Do not treat Windows PowerShell mojibake as proof that a UTF-8 file is
  corrupted. Verify with UTF-8-aware tooling if needed.
- `docs/adr/` contains historical architecture decisions and is not a live
  implementation checklist.
- Current contracts are in `API_SPEC.md`, `WEBSOCKET_PROTOCOL.md`,
  `EVENT_BUS_SPEC.md`, `DATABASE_SCHEMA.md`, and `system_architecture.md`.

## Review Gate

A task is accepted only when:

- required tests passed or documented non-blocking failures were explicitly
  accepted by the main agent;
- no forbidden files were modified;
- runtime behavior matches the current contracts;
- new deferred issues are recorded in `docs/DEFERRED_ISSUES.md`;
- reports are clear enough for the next task to start without reading old plan
  history.

## Cleanup Rule

Old `working/plan/task-*` directories are temporary execution records. They are
not long-term project documentation. Stable knowledge must be moved into
`docs/` or `README.md`.
