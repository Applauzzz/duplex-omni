# Project Continuity

## Active Task

- Project: streaming, interruptible duplex Omni inference.
- Active plan ID: `2026-10-25-mimo-single-omni-duplex`.
- Project root: `/mnt/geminihzceph/user_whynotzhliu/Omni/duplex-omni`.
- Goal: MiMo-only multimodal understanding/reasoning, Qwen3-TTS CustomVoice
  speech rendering, and acoustic/semantic turn policy.
- Current implementation scope and status are recorded in the selected plan,
  not inferred from this file or historical documents.

## Start Every Session

1. Resolve the selected plan with planning-with-files. Honor host `PLAN_ID`
   and `PWF_PLAN_ROOT`; stop ambiguous selection rather than choosing another task.
2. Read that directory's `task_plan.md`, `findings.md`, and `progress.md`.
   For this task they live in `.planning/2026-10-25-mimo-single-omni-duplex/`.
3. Inspect parent and relevant submodule Git status/diff before editing.
4. Read `Doc/stage3-mimo-single-omni/README.md` and the active phase's
   implementation/decision records. Continue the recorded next action.
5. Verify interpreter and import roots before tests or service startup.
   The historical `omni` environment currently targets sibling sources.

## Runtime Environment

- Always initialize with `source /mnt/geminihzceph/user_whynotzhliu/my_envs/env.sh`.
- The script defaults to `liu`; inference currently uses `conda activate omni`
  after initialization. Pin current submodules through process-local PYTHONPATH
  rather than silently changing editable installs.
- Phase 2 is GPU-first per user direction. Do not require CPU regression work
  before starting GPU service validation.

Do not create a competing root plan or consult agent session transcripts unless
the user explicitly asks. The shared `.planning/.active_plan` pointer does not
pin concurrent hosts; use a task-specific host pin or a separate worktree.

## Ownership

- Parent repository: application policy, service adapters, deployment, tests,
  experiments, and knowledge documents.
- `vllm-omni`: model/stage protocols, scheduler/orchestrator extension mechanisms.
- `vllm-src`: low-level model support, weight loading, and execution kernels.
- Prefer current helpers/contracts. Do not move engine-coupled session code
  mechanically or import the Qwen-specific bridge as a MiMo-only backend.
- Preserve the Qwen-only and MiMo-Qwen paths as regression baselines.

## Verification And Records

- Split work into independently testable phases with explicit acceptance gates.
- Before changes, record the implementation scope and important design choices.
- After code changes, run focused tests; broaden coverage for shared behavior.
- Record actual commands, interpreter/import roots, results, skips, failures,
  resolution attempts, artifact locations, and remaining gaps in `progress.md`.
- Update phase status only when its acceptance gate is met.
- Keep discoveries in `findings.md`; keep decisions in the stage knowledge base.
- Historical test counts, nonempty audio, or health checks are not fresh acceptance.

## Preservation

- Never overwrite existing experiment outputs or task records without confirmation.
- Each new run uses an exclusively created timestamped run directory. Store raw
  logs/audio outside Git and retain a tracked summary/config/version manifest.
- Do not run overwrite-prone legacy validation/start scripts unchanged for new runs.
- Do not reset, clean, switch dirty branches, or remove unrelated user changes.
- Do not modify checkpoint folders or silently reinstall a serving environment.
- Check GPU/port ownership before starting services; stop only owned processes.
- Canonical new knowledge lives in `Doc/stage3-mimo-single-omni/` in this Git repo.
  Also publish additive snapshots to `/mnt/geminihzceph/user_whynotzhliu/Omni/Doc/`
  with the required filesystem approval. Never replace historical documentation.
