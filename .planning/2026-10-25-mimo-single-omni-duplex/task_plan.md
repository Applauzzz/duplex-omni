# Task Plan: MiMo Single Omni Duplex

## Goal
Build an interruptible duplex inference service with MiMo as the only
multimodal understanding/reasoning model, a VAD/semantic turn state machine,
and Qwen3-TTS CustomVoice as the initial independent speech renderer.
Phase 1 discovery is complete. Phase 2 GPU feasibility is now authorized.

## Next Step
October29 Judge/BREAK observability correction: preserve mandatory VASD_SEM,
change VASD_BREAK's constrained one-token surface from `需要/不需要` to `有/无`
while retaining distinct `VASD_BREAK` telemetry and `<b>/</b>` policy commands.
Repair the browser timeline so a returned `Judge -> *` transition inserts the
missing Judge segment when the preceding visible state is Silence, and append a
separate transition-log row for every parallel VASD_BREAK result. Verify with
focused provider/page tests and one real MiMo playback-active probe, then roll
only the owned 8080 SVAD process; preserve MiMo 8090 and external TTS 8100.

October29 focused state-machine acceptance: the recovered dirty `feature/SVAD`
implementation now has focused proof for parallel `vasd_sem` admission and
playback-conditional `vasd_break`, semantic non-break admission without
cancellation, default interrupted-output discard, and config-enabled retention
with the verified one-token marker `⏸` plus explicit next-turn MiMo guidance.
Five unique related test entry points pass; no broad safety-fixture suite was
run. Core implementation/config changes pre-existed this Session and were
preserved; this Session added end-to-end coverage and durable records. Next run
the same policy against real MiMo/TTS/browser playback and representative noise,
speech and barge-in audio before closing Phase 5. Do not overwrite the existing
Stage 4/SVAD user changes or initialize another plan.

October26 repository checkpoint: user accepts the basic MiMo+TTS integration
for publication to origin/main and requests stopping current project services.
Preserve the existing narrower completed slices and open wider gates; do not
claim all phases complete. Fresh focused tests17/17 and Node state checks pass.
Current startup01 children13046/13083/13059 were stopped with verified SIGINT;
all eight GPUs are at0MiB and8080/8090/8093 have no listeners.
The publication outcome is recorded in progress.md; after publication continue
voice consistency, browser, strict idle, acoustic/semantic and performance
work when requested. See checkpoint_20261026.md/json. No new GPU replay
result was accepted after the user interrupted the previous recovery.
Historical handoffs follow:

October26 user listening feedback: per-turn timbre changes. Source fixes
vivian/Auto/seed42 but cross-text speaker consistency is not accepted.
Locate the actual deployed host before fresh GPU audio comparisons; this
session's host includes28.29.218.180, not recorded28.29.210.210. Compare same
text repeats/different answers and isolated language/style changes before
changing runtime behavior. See voice_consistency_20261026.md. No service or
inference code changed during diagnosis. Previous handoff is preserved below:

Existing realtime_web/Silero/runner integration now passes six focused tests
and real GPU voice/history/barge-in recovery on8080 (artifactb5683805).
Live UI343636/supervisor343381/session43259; original model services unchanged,
isolated7866 exited0. Recover this deployment instead of rebuilding demos.
Next accept user's browser/microphone experience, then separately develop
semantic policy, strict real-stage idle, broad acoustic false positives and
performance gates. Preserve models/results. Use env.sh then omni.

## Current Phase
Phase 5A/5C existing VAD/frontend integration (in_progress), user correction.
Phase2/3/4 remaining acceptance gates stay open; learned semantic5B pending.
Basic integration checkpoint accepted for publication by user; runtime stopped
by user request. Publication does not close the broader acceptance gates.

## Phases

### Phase 1: Architecture Discovery and Durable Planning
- [x] Restore/check existing plans and Git worktree
- [x] Read historical and repository documentation
- [x] Trace Qwen duplex, MiMo-Qwen cascade, and standalone MiMo paths
- [x] Inspect local Qwen3-TTS model, dependencies, and existing tests
- [x] Publish architecture findings, staged plan, and session recovery rules
- **Status:** complete

### Phase 2: GPU Baseline and Qwen3-TTS Feasibility
- [x] Run isolated MiMo/TTS GPU smoke tests (no CPU baseline gate)
- [x] Record model/environment/resource versions and immutable artifacts
- [ ] Confirm public TTS generation/streaming/cancellation limits
- [ ] Close mixed proper-noun content and true stage-idle/connector gates
- **Status:** in_progress

### Phase 3: Independent TTS Backend and Session Boundary Proof
- [x] Implement a narrow backend and ordered PCM output contract
- [x] Test segmentation, errors, cancellation, and bounded queues
- [x] Prove existing session runner/ledger composition using mock external stages
- **Status:** in_progress

### Phase 4: MiMo Voice Response Pipeline
- [x] Connect MiMo text deltas to TTS without Qwen Omni reasoning
- [x] Validate a complete audio-in/text-and-audio-out turn (GPU WAV fixture)
- [x] Preserve existing services and protocol compatibility
- **Status:** in_progress
- Remaining phase acceptance: actual browser/microphone, real-stage idle,
  mixed-quality and existing session/ledger composition, not merely subitems.

### User-Requested Manual-Turn Slice
- [x] Text/audio input to content-only MiMo SSE and segmented TTS
- [x] Local protocol and deterministic frontend-state tests
- [x] Real GPU text, audio, history, cancellation/recovery and slow-SSE proof
- [x] Deploy dialogue at8080; preserve /tts and original GPU models
- **Status:** complete
- Broader Phase2/3/4/5 gates remain explicitly open above.

### User-Requested Existing Realtime VAD Slice
- [x] Restore original frontend and actual runner/VAD/playback ledger
- [x] Pass focused tests and real GPU voice/history/barge-in recovery
- [x] Deploy and reverify8080, preserve /tts and GPU model services
- [x] Retire isolated test UI and record failures/decisions/current ownership
- **Status:** complete
- Server fixture/protocol scope only. Actual browser and broader Phase5
  acoustic/semantic/performance acceptance remain open.

### Phase 5: Duplex VAD State Machine and Interruption
- [ ] Separate acoustic evidence from semantic turn decisions
- [ ] Test state transitions, false positives, stale output, and barge-in
- [x] Reuse continuous input capture while output is synthesized/played
- [x] Pass recorded-speech auto VAD commit, ACK/history and barge-in GPU replay
- [x] Pass actual runner/host failure, stale-output, partial-ACK and reconnect tests
- [ ] Independently pass 5A acoustic, 5B semantic, and 5C playback/cancel gates
- **Status:** in_progress
- Immediate scope: reuse realtime_web and existing Silero/server_vad rather
  than presenting manual WAV submission as the requested voice experience.

### Phase 6: End-to-End Regression and Performance
- [ ] Replay deterministic fixtures and real duplex sessions
- [ ] Measure latency, cancellation, memory, and long-session stability
- [ ] Record release decisions and operational knowledge
- **Status:** pending

## Decisions Made
| Decision | Rationale |
|----------|-----------|
| Reuse one named plan | New sessions recover this task without overwriting unrelated work |
| Discovery only this session | User explicitly requested analysis and an execution plan |
| Track canonical planning files in this repository | Git can version plans, evidence, and failure records together |
| Preserve external historical documentation | Add new knowledge rather than rewriting experiments |
| Prefer existing Qwen3-TTS runtime | Existing talker/code2wav/PCM/splitter tests reduce integration scope |
| Use segmented HTTP PCM initially | Explicit lifecycle; do not equate segmented synthesis with continuous TTS KV |
| Prove DuplexStagePort composition before choosing refactors | Reuse history/fences without assuming virtual-stage compatibility |
| Separate acoustic and semantic acceptance | Existing VAD/whitelist cannot prove semantic endpointing |
| Exact full-segment ACK history first | Avoid inventing word timestamps for partial playback |
| Phase 2 GPU-first; no CPU prerequisite | User explicitly directed GPU service validation |
| Source user env.sh then activate omni | env.sh defaults to liu; existing inference binaries are in omni |
| Use process-local PYTHONPATH for current submodules | Do not redirect old editable installs or mutate checkpoint folders |
| Explicit UI interface binding for user-requested Mac direct access | Keep model APIs loopback; default UI remains loopback; use current server IP and historical port7865 |
| User-directed manual-turn integration before closing all Phase2 diagnostics | Deliver MiMo-to-TTS hands-on use while keeping unresolved acceptance gates explicit |
| Gate Judge admission with `vasd_sem`; use `vasd_break` only during active TTS playback | Semantic speech must pass even when it is not an interruption, while noise must not enter the turn; break intent is relevant only to cancellation |
| Make interrupted assistant retention configurable and mark retained partial output with one token | Preserve the current discard default while allowing later turns to refer to the exact interruption point without automatically continuing the old answer |
| Limit this state-machine change to at most five focused test entry points | User explicitly requested a compact suite; prioritize end-to-end WebSocket behavior and directly affected state/provider tests |

## Phase Deliverables and Acceptance

Detailed implementations, alternatives and tests:
`Doc/stage3-mimo-single-omni/implementation_plan.md`,
`decisions.md`, and `validation.md`.

| Phase | Deliverable | Independent gate |
|-------|-------------|------------------|
| 1 | Architecture, plan, recovery entry, knowledge snapshot | Paths/records reviewed, Git preserved, no inference edits |
| 2 | Environment/import manifest and TTS/MiMo smoke report | Current source baseline, valid content/PCM, true backend cancel |
| 3 | TTS adapter and mock session composition | Ordered exact spans, bounded queue, stale output/error tests |
| 4 | MiMo-only manual-turn text/audio service | No Qwen Omni dependencies; slow SSE audio-before-DONE and cancellation |
| 5 | Acoustic/semantic policy and playback history | Three subgates pass; input live while speaking; no old-fence pollution |
| 6 | Real duplex/regression/performance release report | Browser/fixture/fault matrix, measured local latency/resources/content |

## Open Implementation Gates
- Select isolated environment without redirecting the historical serving environment.
- Validate current checkpoint/audio runtime and actual TTS multi-stage cancellation.
- Confirm virtual-stage/finalization compatibility with existing session runner.
- Measure semantic MiMo decision quality/latency before enabling semantic mode.
- Choose local voice and performance targets from measured baseline.

## Errors Encountered
| Error / constraint | Attempt | Resolution |
|--------------------|---------|------------|
| External knowledge directory is outside writable roots | 0 | Approval obtained; no-clobber publication succeeded and diff verified |
| TTS docs queried at guessed paths were absent | 1 | Discover actual paths with rg --files; no guessed-path retry |
| env.sh sandbox read-only permission/SSH initialization warnings | 1 | Requested escalation for normal user-specified setup; model environment initialization still needs omni activation |
| ss utility unavailable | 1 | Use Python socket probes and process command inspection |
| Socket creation prohibited in sandbox (PermissionError errno 1) | 1 | Run loopback probes and GPU service operations with explicit escalation |
| Current vllm-src has no CUDA extension binaries; flash attention import fails | 1 | Verified diff against compiled sibling has no C++/CUDA changes; prepare exclusive runtime overlay with current Python source and existing binaries |
| Vendored DeepGEMM file queried before discovery was absent | 1 | Use file inventory; compiled sibling contains vendored dependency, current Git does not |
| TTS GPU stage imports missing generated flashmla Python interface | 1 | Recursively merge current tracked dependencies with missing donor-generated files in a NEW runtime directory; stop first-run processes |
| TTS sequential cold startup exceeded default orchestrator 600s | 2 | Stage0 graph capture succeeded; use explicit init-timeout/stage-init-timeout 1800s and process-local OMP_NUM_THREADS=4 on next attempt |
| Optional DeepGEMM lacks GLIBCXX_3.4.31 in system libstdc++ | 2 | Currently fallback continues; record selected backend and only change runtime libraries if inference actually fails |
| During-audio smoke cancels on near-silent first chunk and fails silence assertion | 1 | Preserve original artifacts; detect effective energy before cancelling and do not require complete-wave energy for partial cancellation |
| Offline Whisper lacks multilingual generation config mappings | 1 | Load language/task IDs from bundled tokenizer into in-memory config; no checkpoint edits |
| TTS stage snapshots nonzero after cancel and ordinary completion | 1 | Orchestrator ACK/counters/recovery pass, snapshots may be stale; direct real-state gate remains open |
| Wait/resume probes HTTP404 | 1 | Dev endpoints not enabled; record not passed, use isolated diagnostic access next |
| Mixed Qwen TTS content differs in Whisper and MiMo ASR | 1 | Preserve original PCM/reference, pronunciation/listening diagnosis required |
| Gradio missing in omni | 1 | Use installed aiohttp for a narrow TTS preview; no dependency install |
| MiMo preview01 cannot reserve 90% GPU memory | 1 | Other tasks now occupy about32GiB on all GPUs; failed attempt exited1, no foreign processes stopped or automatic retry |
| Browser automation not found in inspected executable/cache paths | 1 | Record missing Playwright/Chromium; validate HTTP and actual GPU proxy without claiming browser acceptance |
| Initial default-proxy urllib preview probe HTTP403 | 1 | Direct aiohttp trust_env=False page/status/GPU synthesis passed; no public exposure changes |
| Mac localhost access refused; UI only bound server loopback7866 | 1 | User expects direct-IP7865; verify current interface and adjust only UI binding, keeping GPU models running |
| hostname -I denied in sandbox | 1 | Approved escalated interface discovery succeeded: current server IP28.29.210.210, not historical28.29.210.139 |
| Mac direct-IP7865 access returns IT-branded502 JSON | 1 | Server-local checks pass; legacy deployment explicitly uses allowed8080. Start UI8080 and require Mac verification; exact gateway cause remains unproven |
| Exact-span test removed abbreviation whitespace in its expected string | 1 | Actual splitter/spans were correct; replace broad string normalization with explicit expected segments and rerun |
| Manual-turn frontend bypassed existing VAD/realtime workflow | 1 | User corrected scope; reread stage1/2, reuse existing frontend/VAD and integrate independent TTS behind it |
| Initial actual-runner tests: retry timeout, lazy VAD access and pre-ACK history assumption | 1 | Trace terminal-request reuse and detector initialization; fix adapter/tests before live switch |
| Qwen media-first pending history mixes latest audio with old text | 1 | MiMo chronological user merger verified via saved-input GPU variants and full replay |
| Disconnect cancels HTTP finalization and strands admission slot | 1 | Shielded tracked cleanup; host close/reconnect test passes |
| Nearly silent regression fixture rejected without input | 1 | Use effective-amplitude PCM in focused test |
| UI readiness exceeds180s before speech tests | 1 | Extend startup readiness wait600s; turn/content gates unchanged |

## Session Rules
- PLAN_ID: `2026-10-25-mimo-single-omni-duplex`.
- PWF_PLAN_ROOT: `/mnt/geminihzceph/user_whynotzhliu/Omni/duplex-omni`.
- Recover the selected task_plan.md, findings.md, progress.md first, then inspect Git.
- Do not consult agent session stores unless the user explicitly requests it.
- Record design, validation commands/results, failures, and artifacts at each stage.
- Never overwrite prior run directories or task records without confirmation.
- Phase 1 restriction on starting inference applied only to the planning session;
  GPU startup is now authorized. No automatic dependency installation or commits.
- Environment entry: `source /mnt/geminihzceph/user_whynotzhliu/my_envs/env.sh`.
- Canonical knowledge: `Doc/stage3-mimo-single-omni/`; external publication is additive.
