# Changelog

## 2.2.0 — Quality gate + durable task history
- Added `quality.py`, a project-aware verification layer.
- The coding agent now checks changed files and cross-file consistency after edits.
- Python syntax is checked with `compileall`; JavaScript files are checked with `node --check` when Node.js is available.
- Existing Python tests are run when a recognizable test suite exists and pytest is available.
- Failed checks are fed back to the agent for up to two repair attempts before the result is reported.
- Package lifecycle commands (`npm`, `pnpm`, `yarn`) are not automatically executed.
- Added persistent task records in MongoDB: goal, mode, status, current step, changed files, summary, and quality results.
- Added authenticated project task history (`GET /api/projects/<pid>/tasks`) and task detail (`GET /api/tasks/<tid>`) endpoints.
- Added unit tests for verification-plan selection and `UPGRADE_ROADMAP.md` for the next stages.

## Important
This release is a foundation, not a claim of unlimited or flawless autonomy. The in-memory job queue and current lightweight code runner still need a production-grade isolation and persistence redesign.

## 2.3.0 — bounded task planning
- Added `orchestration.py` to validate and normalize structured plans from the model, with a deterministic fallback when planning output is invalid or the planning API is unavailable.
- For write/debug/optimize tasks, the agent now requests a bounded plan before editing, adds acceptance criteria and risks to its working instructions, and persists the plan/subtasks/phase with the task record.
- Task history/detail APIs now expose plan, acceptance criteria, subtasks, and phase.
- Planning can be disabled with `TASK_PLANNING=0`; default is enabled.
- Added unit tests for malformed plans, output bounds, and rendering.
