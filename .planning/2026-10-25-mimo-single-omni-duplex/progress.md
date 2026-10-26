# Progress Log

## Session: 2026-10-25

### Current Status
- **Phase:** 1 complete - Architecture Discovery and Durable Planning
- **Started:** 2026-10-25
- **Scope:** analysis and planning; inference code unchanged
- **Next:** Phase 2 pending; environment/import validation, CPU baseline, isolated TTS smoke

### Actions Taken
- Read both installed and user-provided planning skill instructions.
- Resolved prior plan selection; no existing task plan or ambiguity reported.
- Inspected root directory, historical Doc listing, and initial Git state.
- Initialized named plan `2026-10-25-mimo-single-omni-duplex`.
- Drafted six-stage roadmap and preservation/session-recovery constraints.
- Read root README, repository/submodule conventions, and historical Doc index.
- Identified existing environment/GPU-validation caveats and overwrite-prone legacy scripts.
- Read historical service topology/configuration and external stage2 design/execution notes.
- Confirmed pinned submodule hashes and local CustomVoice asset presence.
- Located existing Qwen3-TTS implementation and relevant duplex/VAD/TTS test families.
- Read legacy architecture, known issues, change log, and original 2026-10-14 debug report.
- Inspected TTS pipeline/deployment/model configs and overlap/commit policy implementations.
- Separated acoustic turn detection from future semantic turn-decision work.
- Traced bridge submission/fences/output/abort and MiMo input/SSE construction.
- Read TTS streaming handler declarations; noted segmented streaming and pending cancellation verification.
- Probed default interpreter/module origins and metadata without importing/loading models.
- Confirmed clean submodule worktrees and inspected MiMo class registry/config.
- Verified TTS streaming semantics using official Qwen and vLLM primary sources.
- Located real speech documentation/splitter tests, omni environment executable,
  and automatic MiMo multimodal architecture conversion.
- Inspected omni metadata/import roots: serving environment targets older sibling
  sources; no installation or environment mutation performed.
- Confirmed MiMo multimodal conversion condition and HTTP TTS generator cleanup path.
- Created `AGENTS.md` session-recovery/ownership/preservation instructions.
- Created `Doc/stage3-mimo-single-omni/` README, architecture, implementation plan,
  decisions, and validation records; added a narrow README navigation entry.
- Expanded phase gates and decisions; no inference/source/submodule edits.
- Obtained filesystem approval and published five new documents to external Doc
  using no-clobber copying; recursive diff confirms exact match.
- Completed Phase 1 and left Phases 2-6 pending. No commit/push or service startup.

### Test Results
| Test | Expected | Actual | Status |
|------|----------|--------|--------|
| Initial Git diff/status | Identify existing modifications | Clean main tracking origin/main | PASS |
| Plan resolver ambiguity check | Safe task selection | No prior plan; initialized dedicated plan | PASS |
| `python -B` isolated file import/assertions | Test stdlib splitter without inference imports | 8 scenarios passed: buffer, decimal split, thousands, abbreviation, CJK, quote, empty flush, invalid mode | PASS |
| `python -B` documentation/model assertions | Paths, links, plan/recovery and CustomVoice JSON valid | 5 documents, 4 local links, plan triplet, recovery entry, 24kHz/1920/nine-speaker contract passed | PASS |
| `git diff --check` | No tracked whitespace errors | Exit 0 | PASS |
| Pinned `resolve-plan-dir.sh` | Recover this named plan | Returned exact named plan directory | PASS |
| `diff -qr Doc/stage3-mimo-single-omni /mnt/geminihzceph/user_whynotzhliu/Omni/Doc/stage3-mimo-single-omni` | External snapshot equals canonical knowledge | Exit 0, no differences | PASS |
| `python -B` new-file format assertions | Newline/whitespace/code fences valid | Nine new/planning files passed | PASS |
| Final Git scope review | Only planning/documentation changes | README navigation + new plan/AGENTS/knowledge; submodules unchanged | PASS |

### Errors
| Error | Resolution |
|-------|------------|
| External knowledge directory outside writable roots | Publication requires explicit escalated command; no external files changed |
| Two guessed TTS documentation paths absent (rg exit 2) | Locate actual files using rg --files before further reads |

### Verification Boundaries
- Splitter smoke used the stdlib-only source file directly. No fork package
  conftest, vLLM imports, GPU model, full pytest suite, or serving test ran.
- GPU checks/startup and environment changes are deferred to Phase 2.
- External knowledge publication completed with approval; no historical files overwritten.

### Files Changed
- `README.md`: two navigation lines.
- `AGENTS.md`: project continuity instructions.
- `.planning/.active_plan` and selected plan's task_plan.md/findings.md/progress.md.
- `Doc/stage3-mimo-single-omni/README.md`, architecture.md,
  implementation_plan.md, decisions.md, validation.md.
- External Doc: five newly published knowledge files only.

### 5-Question Reboot Check
| Question | Answer |
|----------|--------|
| Where am I? | Phase 1 complete, planning session finished |
| Where am I going? | Phase 2 environment/baseline/TTS feasibility, then Phases 3-6 |
| What's the goal? | MiMo-only reasoning + independent Qwen3-TTS + duplex acoustic/semantic turn control |
| What have I learned? | See findings.md and stage3 architecture; runtime/import/cancel/semantic gates remain |
| What have I done? | Analyzed historical/current code, created durable plan/knowledge, validated and published docs; no inference edits |

## Session 2: 2026-10-25, Phase 2 GPU-First

- **Status:** in_progress.
- User removed CPU baseline prerequisite and authorized GPU startup.
- Runtime entry recorded in AGENTS.md: source my_envs/env.sh, then activate omni.
- Recovered prior plan and preserved existing documentation/worktree.
- Checked GPUs: all eight H20 empty. Default sourced environment remains liu.
- env.sh read-only SSH/permission warnings recorded; requested normal initialization
  outside sandbox. No source/script secret contents logged.
- ss command missing; switch to Python socket probes.
- No GPU server started yet; preparing process-local current source imports.
- Recovery continuation: GPU inventory rechecked, all eight H20 still empty.
- Sandbox Python socket probe failed with PermissionError errno 1. Use escalated
  loopback/service commands; do not bypass socket restrictions.
- Updated knowledge with dated GPU-first direction while preserving initial plan.
- Current-source import attempt failed: missing FA2/FA3 CUDA native extensions.
  Current checkout has no .so files. Compared compiled sibling ced6857af against
  current HEAD: only requirements and MiMo Python changes, no CUDA/C++ changes.
- Preparing isolated runtime overlay; no install/source/weight changes.
- Runtime overlay creation PASS:
  workspace/logs/20261025T092450Z_mimo_single_phase2_79e5830c.
  Native binary hashes and source-diff whitelist saved in runtime_manifest.json.
- Added prepare_runtime.py, owned run_service.py and one-H20 CustomVoice overlay
  config under workspace/experiments/20261025_mimo_single_phase2/.
  Verification proceeds directly via GPU service startup (no CPU suite gate).
- TTS attempt 01 FAIL: stage0 GPU initialization imports
  vllm.third_party.flashmla.flash_mla_interface absent from Git checkout.
  Binary-only overlay insufficient; preserve run 79e5830c and create a new
  recursive generated-dependency overlay. TTS process exited code 1.
- Stopped owned MiMo attempt 01 during startup before retrying dependencies.
  Both first-run supervisor sessions ended; no successful model response yet.
- Recursive generated-dependency overlay prepared successfully in
  workspace/logs/20261025T100540Z_mimo_single_phase2_84dfb949.
- Started owned TTS attempt 02 (GPU4/8093) and MiMo attempt 02 (GPU0-3/8090).
- Added GPU smoke harness with no-clobber PCM/WAV, request/timing/metrics artifacts,
  before-first-audio and during-audio disconnect probes, recovery requests,
  MiMo SSE and auxiliary raw-audio transcription. Content gate remains separate.
- Attempt 02 progress: TTS talker/code2wav architectures resolved and mapped to
  physical GPU4. MiMo resolved MiMoV2OmniForCausalLM; TP4 workers entering NCCL.
  No model response yet. GPU harness awaiting readiness in
  smoke_20261025T101119Z_all; git diff --check PASS.
- Minor diagnostic failures: log tailed before MiMo launch file existed (startup
  race, file now exists); /proc/42336/io denied in sandbox, no need to repeat.
- MiMo now loading 65 shards (161.06 GiB), TTS stage0 torch.compile and autotune
  progressed. Optional DeepGEMM import warns missing GLIBCXX_3.4.31, MARLIN selected.
- Added check_evidence.py for matched Orchestrator/AsyncOmni abort IDs and running/
  waiting gauge evidence, explicitly keeping content/listening acceptance pending.
- TTS attempt 02 reached stage0 ready, MRV2/first-frame CUDA graphs captured,
  but default orchestrator 600s expired just before stage1 startup.
  Retry with explicit init/stage-init 1800s and process-local OMP threads=4.
- MiMo TP4 loaded all shards; per-rank model memory 41.57 GiB, weight load
  rank0 167.86s; multi-modal encoder profiling and torch.compile now running.
- Additional read-only discovery misses: guessed gpu_worker.py absent (use
  gpu_ar_worker.py/base.py); py-spy unavailable. No dependency installs performed.
- TTS attempt 02 ended code1 and GPU4 returned to zero. Attempt03 launched with
  init-timeout/stage-init-timeout=1800, OMP_NUM_THREADS=4, distinct log/cache names.
- Found existing local whisper-large-v3 (2.9 GiB safetensors/config/extractor);
  omni includes openai-whisper tokenizer resources. Added independent_asr.py for
  GPU5 offline transcription without download/model writes/reference prompting.
- Recovery: MiMo02 and TTS03 are serving. Five complete TTS samples passed HTTP200,
  mono PCM16/24kHz, multiple chunks, nonzero energy and transport EOF.
  Artifacts: run 84dfb949/smoke_20261025T101119Z_all.
  First-byte/RTF: Chinese cold 1.820s/.358; English .0275s/.089;
  numbers .0363s/.087; mixed .0329s/.087; long .0290s/.085.
- First 80ms TTS chunk is near-silent. During-audio cancellation harness failed
  its whole-wave silence assertion after cancelling on that first chunk.
  Preserve result; change trigger to effective PCM energy and measure separately
  first-byte versus first-energy latency. No audible-speech acceptance claimed.
- Before-audio client close reached AsyncOmni abort/SpeechE2E cancellation;
  recovery synthesis succeeded. Orchestrator abort confirmation not yet visible.
- Independent Whisper loaded on GPU5 but generation failed: local checkpoint
  lacks multilingual language/task generation-config mappings. Populate runtime
  config from bundled tokenizer, never write checkpoint or download dependencies.
- MiMo text smoke completed (session8398 exit0), content "I am ready to help.",
  no reasoning, SSE DONE, total .260s. Counting-request disconnect and new
  "recovered" request succeeded; stage metrics/backend evidence remains to review.
  Artifacts: run 84dfb949/smoke_20261025T104644Z_mimo-text.
- Updated GPU harness with 20ms/RMS .002 effective-energy trigger, separate arrival/
  audio-offset timestamps, cancellation-only/raw-audio-only modes and settled
  metrics snapshots. Independent ASR now uses in-memory bundled token mappings.
- Cancellation investigation: frontend abort counter increments but stage snapshots
  still show running/waiting after 6s; snapshot staleness versus real residual work
  unresolved. AsyncOmni.abort maps external IDs, while generate cancellation logs
  an internal ID. Trace caller next. Guessed omni_engine.py absent (rg exit2).
- External primary-source Whisper config lookup returned no usable contents;
  use installed HF implementation and bundled original tokenizer, no downloads.
- Independent Whisper GPU retry PASS (exit0): whisper_20261025T105722Z.
  Chinese/English/numeric-date/long content matches modulo punctuation and number
  normalization. Mixed Qwen TTS rendered/transcribed "Quantit S"; quality gate
  stays open, no reference prompting or checkpoint writes.
- MiMo raw-audio smoke PASS transport (exit0): smoke_20261025T110115Z_mimo-audio.
  Five HTTP200 responses, reasoning null, long exact; first audio 24.212s,
  subsequent .165/.235/.204/.287s. MiMo also transcribes Qwen TTS as "QuantitaS",
  corroborating pronunciation concern but not independent acceptance.
- Warm TTS five-sample rerun has identical PCM hashes to first run. First effective
  energy arrives .192-.200s (audio offset .08s), first bytes .026-.028s, RTF .085-.088.
  Cancellation tests still running in smoke_20261025T110131Z_tts.
- Trace confirms internal abort helper is used; initial external-ID hypothesis
  disproved. Engine abort should wait for correlated Orchestrator acknowledgment.
  Settled metrics file read raced writer (rg exit2); wait for process completion.
- TTS rerun exit0. During-effective-audio disconnect at .1935s after 2.08s PCM;
  before-audio disconnect .0233s. Both subsequent recoveries succeeded.
- Orchestrator acknowledgment logs exist for all four cancelled requests:
  original search missed capitalized "Aborted". Matched IDs now recovered.
  No abort timeout/failure. 6s/18s stage gauges remain at running0=1/waiting1=1;
  counters stable between snapshots, GPU idle. Empty scheduler stats can be stale.
- Plan supplementary /pause?mode=wait&clear_cache=false -> /resume proof on owned
  services; no force abort/cache reset and use bounded request timeout. This proves
  drain availability, not exact instantaneous cancellation latency.
- Supplementary drain probe returned404 for both services and resume routes;
  exit0 only archived result, NOT acceptance. Dev routers not enabled by default.
  Corrected harness to raise on non200; no force abort/cache modifications.
- Created dated Phase2 knowledge report and additive README/decision entries.
  Baseline and manifests subitems done; phase stays in_progress pending mixed
  content plus actual stage/connector idle and tail/rapid cancellation gates.
- Added archive_evidence.py for script/config/source digests and GPU result index;
  corrected an extra closing parenthesis before execution. No submodule edits.
- Sent Ctrl-C to owned TTS03/MiMo02 supervisors; waiting for graceful shutdown.
  All smoke/ASR/evidence sessions finished. Guessed instrumentator.py absent
  (rg exit2); discovered package path and development router registration.

### Phase 2 Session Close

- MiMo02 and TTS03 supervisors both exited0 at 2026-10-25T11:16:43Z.
  Final nvidia-smi: all eight H20 at0MiB/0% utilization; no owned serving sessions
  remain. Service exit artifacts preserved, no force kill.
- archive_evidence.py exit0:
  evidence_archive_20261025T112653Z.json records actual resolved source paths,
  script/model-config SHA, launch versions and all five cold/warm/ASR outcomes.
- External publication: approved cp -n added only
  /mnt/geminihzceph/user_whynotzhliu/Omni/Doc/stage3-mimo-single-omni/phase2_gpu_20261025.md.
  diff -q against canonical report exit0. Historical external files untouched.
- Final git diff --check exit0. Parent retains initial Phase1 files plus Phase2
  experiment tools/report; both submodules clean, gitlinks unchanged.
  No commit/push, installs, checkpoint changes or CPU suite run.
- Final drain non200 failure assertion was added after the recorded404 probe;
  not GPU-retested after services stopped. Do not claim that branch tested.
- Phase2 remains in_progress, not blocked or complete. Next work: isolated real
  scheduler/connector diagnostics, tail/rapid cancellation and mixed pronunciation.
  Successful baseline/ASR need not be repeated. Phase3 not started.

### Executed Command Index

All inference commands initialize `source /mnt/geminihzceph/user_whynotzhliu/my_envs/env.sh`
then `conda activate omni`. Service launch manifests contain full argv/environment;
the following paths are relative to the repository:

```bash
python -B workspace/experiments/20261025_mimo_single_phase2/gpu_smoke.py --run workspace/logs/20261025T100540Z_mimo_single_phase2_84dfb949 --mode mimo-text --wait 60
python -B workspace/experiments/20261025_mimo_single_phase2/gpu_smoke.py --run workspace/logs/20261025T100540Z_mimo_single_phase2_84dfb949 --mode tts --wait 60
python -B workspace/experiments/20261025_mimo_single_phase2/gpu_smoke.py --run workspace/logs/20261025T100540Z_mimo_single_phase2_84dfb949 --mode mimo-audio --samples workspace/logs/20261025T100540Z_mimo_single_phase2_84dfb949/smoke_20261025T101119Z_all --wait 60
CUDA_VISIBLE_DEVICES=5 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 python -B workspace/experiments/20261025_mimo_single_phase2/independent_asr.py --run workspace/logs/20261025T100540Z_mimo_single_phase2_84dfb949 --samples workspace/logs/20261025T100540Z_mimo_single_phase2_84dfb949/smoke_20261025T101119Z_all --model /mnt/geminihzceph/user_whynotzhliu/Omni/we_duplex_demo/L20_mac_demo_20260915/ttns_cls_step15000_online_deploy/models/whisper-large-v3 --wait 60
python -B workspace/experiments/20261025_mimo_single_phase2/gpu_smoke.py --run workspace/logs/20261025T100540Z_mimo_single_phase2_84dfb949 --mode drain --wait 60
python -B workspace/experiments/20261025_mimo_single_phase2/archive_evidence.py --run workspace/logs/20261025T100540Z_mimo_single_phase2_84dfb949
```

First four commands exited0 after fixes; drain exited0 while recording404
(not passed); archive exited0. Original all-mode exit1 and first Whisper exit1
are preserved separately. GPU service/API operations used explicit escalation.

## Session 3: User Preview Startup

- User requested live services for hands-on experience; keep owned services
  running at handoff rather than stopping them after verification.
- Recovered selected planning triplet, AGENTS and Phase2 knowledge. Parent dirty
  documentation/experiments preserved; vllm-omni clean, all eight GPUs free.
- Existing Qwen3-TTS Gradio demo supports same-origin streamed PCM playback and
  CustomVoice controls. Reuse it rather than adding a new integrated pipeline.
- Scope: restart independent TTS GPU4/API8093 plus Gradio loopback7866 and MiMo
  GPU0-3/API8090. Not a completed MiMo+TTS voice dialogue or VAD/duplex service.
- New exclusive run/logs; environment always env.sh then omni. No model install,
  checkpoint edits, historical run overwrite, public share or dev endpoints.
- Add UI supervision to existing run_service.py so its PID/log/exit ownership is
  recorded under the preview run. Check dependencies and ports before startup.
- Dependency probe: omni lacks gradio; httpx/fastapi/uvicorn available. No install.
  Ports8090/8093/7866 free. New runtime5f193640 created successfully.
- Started TTS preview01/GPU4 (session59799), MiMo preview01/GPU0-3 (session88240);
  waiting for readiness. Replaced planned Gradio with narrow aiohttp same-origin
  TTS试听页面 using existing aiohttp and PCM/WebAudio, no new model pipeline.
- This preview UI is an experiment convenience, not Phase3/4 completion.
- Continued recovery read skill, AGENTS, pinned plan triplet and Phase2 report;
  resolver returned the exact selected plan; git diff --stat only tracked README
  navigation (new planning/experiment files remain untracked).
- UI preview01 started: session90217, child PID/PGID113084, supervisor112145,
  loopback7866, no GPU. TTS session59799 remains initializing.
- MiMo preview01 session88240 exited1. Actual root cause: all four ranks have
 60.82/95.07GiB free, less than90% requested85.57GiB. Other tasks now occupy
 33188MiB on each of eight GPUs,100% utilization; foreign PIDs not visible in
  this container namespace. No retries at the same budget, no foreign signals.
- Node/npm exist, but Playwright/Chromium command/cache searches found nothing.
  Missing guessed cache paths produced ls exit2; record limitation and do not
  install tools. Preview HTTP/real GPU synthesis verification still required.
- TTS preview01 application startup complete at12:18:41Z. First urllib probe
  returned HTTP403 because it uses environment proxies; retry direct with
  aiohttp trust_env=False rather than changing server exposure.
- Added check_preview.py: exclusive new artifact directory, page/status/input
  errors and one real Chinese GPU PCM request. Hardened preview_server.py JSON
  object/parse validation and disconnected-health/backend-unavailable handling.
  Restart only owned UI to load changes; GPU TTS remains running. No CPU suite.
- UI preview01 stopped gracefully exit0; owned supervisor112145 was signaled,
  no GPU process stopped. UI preview02 started with session90459, child/PGID124947,
  supervisor124742. TTS preview01 session59799, child/PGID107820,
  supervisor107614 remains live onGPU4/API8093.
- check_preview.py session60193 exited0; artifact directory
  run5f193640/preview_check_20261025T125416Z. Page200, status200
  {tts:true,mimo:false}; empty/non-object/too-long/invalid-JSON400. Chinese
  PCM synthesis200,4 chunks,130560 bytes,2.72s, RMS.10167, first-byte.9092s,
  complete1.9289s. PCM/WAV/results preserved exclusively. No content ASR or
  full cancellation baseline rerun; browser play/stop/replay not verified.
- Python syntax checks for run_service.py/preview_server.py/check_preview.py PASS;
  Node vm.Script preview JavaScript syntax PASS; git diff --check exit0.
  Both submodule status checks empty; no gitlink changes/commit/push/install.
- Published canonical preview_20261025.md with live service ownership, endpoints,
  SSH forwarding, immutable artifact location, failure and verification boundaries.
  Preserve TTS/UI at user handoff. Phase2 still in_progress; Phases3-6 untouched.
- Approved no-clobber external publication added preview_20261025.md to the
  user-specified knowledge directory; diff -q exit0. Final direct loopback check
  page200 and {tts:true,mimo:false}; final diff --check exit0. Test/probe sessions
  completed; only requested TTS59799/UI90459 serving sessions remain live.

## Session 4: User Requested MiMo And TTS Restart

- User stopped other GPU tasks and requested model restart.
- Recovered skill, AGENTS, full selected plan triplet and dated Phase2/preview
  knowledge; pinned resolver returned exact task. git diff --stat only README.
- GPU0-3/5-7 empty, GPU4 only16821MiB existing TTS. Verified owned commands:
  TTS supervisor107614/child107820, UI supervisor124742/child124947.
- Scope: gracefully stop old owned TTS, prepare fresh run/runtime using existing
  helper, launch MiMoTP4/GPU0-3/API8090 plus TTSGPU4/API8093; retain UI7866.
  Minimal live request verification, no CPU suite, installs or code integration.
  Keep ready services running for user and preserve all previous artifacts.
- Old TTS session59799 exited0 at14:37:10Z, all eightGPUs then empty. No force kill.
  prepare_runtime.py exited0, new run
  workspace/logs/20261025T143656Z_mimo_single_phase2_a205c357.
- Started MiMo restart01 at14:40:44Z: session38811, child/PGID187389,
  supervisor187203, GPU0-3/API8090. TTS restart01 at14:40:50Z:
  session78763, child/PGID187446, supervisor187272, GPU4/API8093.
  Existing UI session90459/child124947 remains on7866/run5f193640.
- Launch manifests confirm omni Python, process-local current-source runtime,
  offline mode, OMP4 and zero foreign GPU allocations at startup. Submodule
  diff --stat empty. Waiting for API readiness; no successful inference claimed yet.
- Progress append initially failed exact-context matching (bullet prefix differed);
  corrected context and appended without overwriting prior records.
- Started minimal verification session58214: uses existing gpu_smoke.ready and
  check_preview.main, concurrent1800s health waits, one64-token content-only MiMo
  SSE with DONE/reasoning checks, then one GPU PCM preview request. Artifacts
  exclusively created in runa205c357. No full baseline/cancellation rerun.
- Initialization progress14:45Z: MiMoV2OmniForCausalLM resolved, frontend multimodal
  warmup complete, EngineCore launchingTP4. TTS talker architecture resolved;
  optional/version warnings retained. No memory conflict or fatal error observed.
  git diff --check --ignore-submodules=all exit0.
- 14:49Z: MiMoTP4 NCCL initialization passed and checkpoint shards loading,
  MARLIN selected; known optional DeepGEMM GLIBCXX warning retained. TTS both
  architectures resolved and stage0MRV2/SHM connector initializing onGPU4.
  No source/runtime dependency changes; startup still pending.
- 14:51-14:52Z: MiMo loaded65shards, rank0 weights161.38s/41.57GiB, now
  torch.compile. TTS stage0 running at14:51:11Z with CUDA/MTP/first-frame
  decoder graphs captured; stage1 process importing. No fatal startup errors.
- TTS application ready14:53:37Z; MiMo ready14:54:48Z. Verification session58214
  exited0. Artifacts: runa205c357/restart_check_20261025T144400Z_da5e17c9
  (request/SSE/result/summary) and preview_check_20261025T145451Z (PCM/WAV/results).
  MiMoready, DONE=true, reasoning empty,.2998s. Preview page/status200,
  {tts:true,mimo:true}; four input errors400; GPU PCM200,4chunks,130560bytes,
  2.72s,RMS.10167, first-byte.8669s, total1.1693s. PCM hash matches earlier sample.
- Inventory: GPU0-3 each89149MiB/0%, GPU4 16817MiB/0%, GPU5-7 empty.
  Owned model sessions38811/78763 and retained UI90459 remain running for user.
  Old TTS exited0; no installs/weights/source/submodule changes or commit/push.
- Created additive restart_20261025_1440.md knowledge snapshot. Phase2 remains
  in_progress; this restart does not imply MiMo-to-TTS/VAD/duplex integration.
- Approved cp -n published only the new restart snapshot to external Doc;
  diff -q exit0. Final diff --check exit0. Verification/helper sessions completed;
  requested MiMo38811/TTS78763/UI90459 sessions remain running at handoff.

## Session 5: Restore Mac Direct-IP Preview Access

- User reported localhost refusal and supplied historical direct-IP Chrome
  strategy. Recovered selected plan/knowledge; git diff --stat only README,
  untracked planning/experiments preserved. No model restart requested here.
- Sandbox hostname discovery previously failed Operation not permitted;
  approved hostname -I now succeeds. Current interface28.29.210.210 differs
  from historical28.29.210.139. At15:02Z port7865 free, both model health200,
  loopback7866 status200, direct-IP7866 connection refused.
- Verified live supervisor/child commands: UI124742/124947,
  MiMo187203/187389 and TTS187272/187446 match preserved ownership records.
- Scope before edits: add explicit UI-only host option with loopback default,
  preserve loopback models, parameterize GPU check URL. Stop only owned old UI;
  new exclusive UI attempt in runa205c357 will bind28.29.210.210:7865.
  Keep models and new UI running for user. No CPU suite prerequisite, installs,
  dev endpoints, checkpoint edits or historical artifacts replaced.
- Implemented preview --host (default127.0.0.1), supervisor --ui-host restricted
  to tts-ui, correct interface port probe, and GPU check --base-url with preserved
  default7866/signature compatibility. Syntax checks in omni PASS for all3 files.
  git diff --check exit0 (slow shared-filesystem traversal, no error).
- Reverified old UI child argv/PGID and supervisor role/attempt/run before SIGINT.
  UI session90459 exited0; models38811/78763 not signaled. Started new UI
  directip01 at15:11:36Z, session19541, child/PGID216007, supervisor215773,
  specific interface28.29.210.210:7865, CUDA_VISIBLE_DEVICES empty.
- check_preview.py --run workspace/logs/20261025T143656Z_mimo_single_phase2_a205c357
  --base-url http://28.29.210.210:7865 session62384 exited0. New artifact:
  preview_check_20261025T151216Z (PCM,WAV,resultsJSON), never overwrites old data.
  Page/status200, both backends true, four invalid inputs400; GPU synthesis200,
  4chunks,130560bytes,2.72s,RMS.10167,first-byte.02927s,total.26842s.
  SHA matches earlier preserved audio. No browser/Mac acceptance or new ASR,
  cancellation, duplex/VAD integration claimed. Phase2 stays in_progress.
- Added canonical direct_access_20261025_1512.md and README navigation; approved
  cp -n published only this new file to external user Doc. diff -q exit0.
  Final git diff --check --ignore-submodules=all exit0.
- Final check session32719 exited0: exact model/UI child argv still match launch
  records; /proc/net/tcp confirms7865=28.29.210.210,8090/8093=127.0.0.1, old7866
  no longer listening. Nonloopback --ui-host for model role rejected before any
  socket/log creation (expected argparse2, guard PASS); no synthetic run created.
  Direct-IP status200, both backend health true. All verification/helper sessions
  finished; requested MiMo38811/TTS78763/newUI19541 left running at handoff.

## Session 6: Investigate Mac IT-Gateway 502

- User challenged remote availability with IT-branded502 JSON. Explicitly
  corrected the scope of previous verification: local server success only,
  no Mac acceptance. Recovered pinned plan, findings/progress, current UI
  source and access record; git diff --stat still only README.
- No code/model/restart change yet. Diagnose live application response and
  network/interface evidence first. Record proxy/routing origin as unconfirmed,
  not a proven cause. Historical external IP may differ from local interface.
- Network-check session74914 exited0, artifact
  runa205c357/network_check_20261025T152830Z_dfcae602/results.json:
  original3 child commands match, UI7865 page200 text/html/aiohttp,
  status200 both true, loopback8090/8093health200. ip tool absent (no install),
  read existing /proc/net/route fallback; listen addresses unchanged.
- Proxy comparison session67941 exited0, artifact
  proxy_compare_20261025T152947Z_a8e22b24/results.json: server direct200,
  environment proxy403, not Mac502. No proxy URL/credentials logged or changed.
  External documentation lookup yielded no usable results; local deployment
  document and measured responses are the evidence, no external factual claims.
- User redirected to legacy02_running.md. Full read identifies actual8080
  allowed-port deployment versus default7865. Fresh Chrome profile required;
  retain current trust_env=False plus explicit loopback NO_PROXY/no_proxy.
  Port8080 probe session40734 exited0, wildcard free. No foreign processes.
- Before service changes: launch additional owned UI on28.29.210.210:8080
  with new attempt, verify page/status/error handling and actualGPU synthesis,
  then stop only owned old7865 UI. No code edits needed, no model restart,
  network-policy changes or browser-security bypass beyond documented origin.
- Started UI allowed8080_01 at15:36:26Z: session54807, child/PGID230994,
  supervisor230676,28.29.210.210:8080; explicit loopback NO_PROXY/no_proxy,
  empty CUDA_VISIBLE_DEVICES. No code edits needed.
- GPU preview check session14015 exited0, artifact
  preview_check_20261025T153655Z: page/status200, both health true,
  four invalid inputs400, ChinesePCM200,5chunks,130560bytes/2.72s,RMS.10167,
  first-byte.02882s,total.26875s; PCM hash matches previous preserved sample.
- Final ownership/listener check session51711 exited0. Verified new8080 UI
  and old7865 child/supervisor argv/PGID before signaling only old supervisor
  215773. Old UI session19541 exited0. Model PIDs187389/187446 unchanged.
  Listeners8080=currentIP,8090/8093=loopback; NO_PROXY/no_proxy verified.
  Models38811/78763 and newUI54807 retained; all diagnostic sessions completed.
- New additive knowledge allowed_port_20261025_1536.md records source deployment
  document,8080/current-IP/newChromeProfile strategy and unverified Mac boundary.
  Phase2 remains in_progress; no CPU suite, model restart, dependency install,
  network rules/proxy modification, source/submodule edits, commit or push.
- Approved cp -n published only new allowed_port_20261025_1536.md to external
  user Doc; diff -q exit0. git diff --check --ignore-submodules=all exit0.
  All probes/tests and oldUI sessions finished; MiMo38811/TTS78763/UI54807
  remain running at handoff. Client access still awaits actual Mac result.

## Session 7: Connect MiMo To Qwen3-TTS

- User confirms TTS preview is accessible and requests actual MiMo-to-TTS.
  Recovered selected plan/findings/progress and implementation decisions,
  inspected standalone UI/proxy/supervisor, MiMo SSE/input fixtures and pinned
  SpeechTextSplitter. Both submodules clean; parent tracked diff onlyREADME.
- Before edits: implement separate manual-turn integration application with
  text or WAV microphone input, content-only MiMo SSE, ordered segmented
  TTS PCM, bounded queues, exact spans and disconnect cancellation.
  Browser shows response text/plays generated audio; stop fences playback and
  requests. Preserve standalone /tts. Test on separate loopback port before
  switching only UI on8080. Do not restart GPU models or claim VAD/duplex.
- User-directed Phase3/4 integration slice now in_progress. Phase2 gates stay
  open; no baseline/ASR repeat or CPU suite prerequisite. Existing runner/
  playback-ledger composition proof remains a separate uncompleted gate.
- Added integration backend/server/chat page plus focused test_integration.py
  and immutable GPU check harness. Extended supervisor with mimo-tts-ui role
  only; model commands unchanged. Current source splitter imported directly.
  Client text/audio validation, content/tag filtering,4-segment queue, source
  spans, PCM/sample budgets, two active requests and disconnect cleanup present.
- JS vm.Script syntax PASS; git diff --check exit0. Original model/UI commands
  verified still live; no switch or GPU restart yet.
- First focused unittest run session66803:9 passed/1 failed, exit1.
  Failure only expected-string test removed space after abbreviationDr.;
  exact spans and3 segments were correct. Correct expectation explicitly,
  add incomplete-PCM error test and rerun. Aiohttp NotAppKeyWarning follows
  existing preview string-key pattern; no runtime failure or dependency change.
- Focused test rerun PASS11 tests/exit0. Isolated new UI started16:04:17Z,
  session97923, supervisor247464/child247720 onloopback7866.
- GPU check session92148 exited0; exclusive artifact
  integration_check_20261025T160624Z_af0ad2d5. Actual MiMo text answer:
  two+two=four,1.28sPCM; history recognized prior question,1.92sPCM;
  rawWAV questionthree+four answeredseven,1.92sPCM. Input generated separately
  for reproducibility, not an actual microphone capture. Recoverytext/PCM pass.
- Two real disconnects at text/audio triggered new application cancellation;
  MiMo/TTS contexts and tasks closed in isolated log. TTS true-stage idle still
  not proven; don't elevate HTTP cleanup to Phase2 cancellation completion.
- Controlled slowMiMo SSE + realGPU TTS: firstbyte.02587s before model_done4.006s.
  Short real replies finished text before firstaudio (expected, explicitly recorded).
  Browser binary search still found no runnable browser; add deterministic Node
  playback/history/stale-event checks, not screenshot/microphone acceptance.
- Deterministic Node frontend checks exit0: completed history, played-prefix
  interruption, late EOF isolation and invalidPCM. These do not validate
  actual browser/microphone rendering or playback.
- Real TTS cancel log at16:06:27 contains matched internal
  speech-94a63b5d027d49a6-ab203217 Orchestrator/AsyncOmni Aborted ACK,
  SpeechE2E statuscancelled28ms. Stronger than just HTTP close, but direct
  real-stage/connector idle gate remains unresolved.
- Explicitly drain abandoned per-request segment queue during finalization;
  no queue survives a completed/cancelled run. Retest narrow change before
  final UI deployment. Switch only old8080 UI after ownership check; stop
  isolated7866 UI after testing, retain both GPU models untouched.
- Final queue-cleanup retest PASS11 tests/exit0. Owned oldUI54807 and isolated
  UI97923 both exited0 after argv/PGID checks; only their supervisors signaled.
- Live integratedUI started16:14:22Z, session64792, supervisor256349,
  child/PGID256583,currentIP8080. Original MiMo/TTS PIDs unchanged.
- Final GPU verification session60884 exited0, artifact
  integration_check_20261025T161630Z_f12d5afb. Page and /tts200;
  two+two=four PCM1.28s/61440bytes,RMS.06546; historyPCM1.92s/92160bytes;
  audioquestionthree+four=sevenPCM1.92s/92160bytes,RMS.08308.
  Disconnect at text/audio and subsequent recovery pass. Slow injectedMiMo +
  actualGPU TTS firstPCM.02554s vs model_done4.00588s; effective-energy/browser
  audible onset not measured here. No new independentASR/content acceptance.
- Updated subitems honestly: narrow backend/protocol work and GPU manualturn
  complete; full Phase3 runner proof and Phase4 browser/quality/true-idle gates
  remain in_progress. Phase5 VAD/semantic/true-duplex not started.
- Final handoff checks at16:20Z exited0: exact child argv/PGID and supervisor
  role/attempt match manifests for MiMo187389/TTS187446/UI256583. Listeners
  only8080/currentIP and8090/8093loopback;7865/7866 absent.
  Home,/tts,/capture_worklet.js200 and health{mimo:true,tts:true}.
- Original speech GPU regression check_preview.py --base-url
  http://28.29.210.210:8080 exited0. New preview_check_20261025T162007Z:
  four invalid inputs400,PCM2.72s/130560bytes,RMS.10167,firstbyte.02809s,
  total.26814s, SHA matches preserved sample. No broad baseline/ASR rerun.
- Final parent git diff --check passed; both inference submodule worktrees
  clean. No new code changes during handoff checks. Publish only new design/live
  documents with approval and no-clobber semantics; preserve external README.
- Approved cp -n published only mimo_tts_design_20261025.md and
  mimo_tts_live_20261025.md to external user Doc/stage3-mimo-single-omni.
  Both diff -q checks passed; external README and historical records untouched.
  Final whitespace check passed. Verification sessions44515 and GPU preview
  check finished exit0; only requested model38811/TTS78763/UI64792 remain live.
  Manual-turn slice complete; broader Phase2/3/4 acceptance remains in_progress,
  Phase5 not started. No browser/mic acceptance, commit/push or install claimed.

## Session 8: Restore Existing VAD Voice Frontend
- User corrected manual-turn implementation; existing MiMo supports raw audio
  and prior architecture has server_vad/realtime_web. Acknowledge detour.
- Recovered pinned plan/findings/progress and Git scope. Read stage2 README and
  full plan_a, stage1 architecture, VAD configuration and running conventions.
- Before edits: preserve previous experiments and live models; trace and reuse
  existing frontend/VAD/ACK, add MiMo->independentTTS backend integration, test
  before8080 swap. No new manual recorder or claim of learned semantic VAD.
- Phase5 existing acoustic/frontend/cancel work now in_progress; broader gates
  remain open. No serving/model changes yet.
- Source tracing confirms actual DuplexStagePort is in contracts.py, not a
  stage_port.py file (initial guessed read failed). Outputs is a package, not
  outputs.py (guessed rg failed); discovered canonical paths before continuing.
- Design recorded in realtime_vad_design_20261025.md: real manager/runner
  composition, existing PCM/history helpers and frontend, narrow external
  virtual-stage lifecycle, completed-segment ACK marks and real Silero.
  No Qwen processor/prefill/embedding and no separate history implementation.
- Added realtime_backend.py, realtime_server.py, original-frontend MiMo profile
  and actual-runner focused tests. Supervisor adds mimo-realtime-ui role only.
  Node profile syntax and git whitespace checks passed. Isolated7866 started
  vadtest01, session36809/child284125; model and live8080 processes preserved.
- First runner tests session54656 exited1: cancel/prefix/recovery passed;
  failure recovery timed out, lazy VAD detector accessed before audio, and
  pre-ACK history assertion assumed an empty assistant row rather than no row.
  Diagnose existing lifecycle/terminal identity contracts before rerun.
- Diagnosis correction: detector is not lazy; test consumed initial open's
  auto-projected session.updated before the dispatched update completed.
  Drain initial ACK in setup. Pre-ACK history has no assistant row by design.
- Pipeline errors close response but do not complete model turn. Emit separate
  terminal after error, allowing actual runner to advance identity and release
  resources. Remove duplicate update at open and close WS on sender failures.
  Guessed append/output/events paths absent; rg inventory found canonical
  append_task.py/model_channel.py and turn_detection.py.
- Actual Silero startup loaded TorchSileroBackend at16:47:12Z. Verified
  isolated child284125/PGID284125/supervisor283689 and original model/UI argv.
  No model restart. Focused rerun session93734 running under env.sh/omni.
- Additional guessed checker/stage2/playback filenames absent. Use discovered
  check_gpu.py and rg file inventory; no historical files modified.
- Rerun93734:3 passed, error retry still timed out. Error handler clears
  active_request_id so subsequent terminal was filtered. Adapter projector now
  recognizes its failed request, projects terminal without response rebinding,
  marks it terminal and separately cleans external resources. No engine edits.
- Isolated vadtest01 supervisor283689 stopped gracefully; session36809 exit0.
- Third focused run83881:3 pass, failure retry still timeout. Stop incremental
  guesses; inspect failed session/model-state/event snapshot in single-case run.
  Isolated vadtest02 session83889/child296375 started; real GPU replay39048
  uses preserved input.wav, no manual audio commit, with new exclusive artifacts.
- GPU replay39048 preserved fail artifact realtime_check_20261025T165636Z_b7647d5f:
  real speech_started/stopped/auto-commit and2.72sPCM passed; checker expected
  output_text rather than existing output_audio_transcript event. Actual MiMo
  transcribed input: adapter omitted old bridge AUDIO_TURN_HINT. Restore that
  exact model-input hint without importing the bridge.
- Single-case50423 confirms turn_id advanced1, active_request None but stream
  binding still held. No-output failed terminal reports emitted_response=False,
  so standard finished-output stream release does not run. Error-only cleanup
  releases exact matching stream binding/resource; original runner untouched.
- Focused run75522 exited0: all4 actual manager/runner/ledger tests pass,
  including automatic VAD scorer, full ACK history, cancel partial prefix,
  stale output and error retry. Prior guessed fixes/failures preserved.
- Isolated vadtest02 exited0; vadtest03 session43077 starting. No8080/model
  change. Whitespace check passed. Real Silero/GPU replay still required.
- Review before deployment: per-connection host must run existing manager
  reaper_loop; add it and close WS on session.closed. Keep application admission
  slot reserved through model/manager cleanup, rather than releasing before awaits.
  Only host changed; reverify connection close/reconnect and runner tests.
- GPU replay47019 artifact realtime_check_20261025T170217Z_bba1e346:
  automatic voice question3+4 answered7 (1.92sPCM); ACK/history followup correct.
  New speech cancelled actual MiMo/TTS contexts on speech_started, then
  committed new speech; recovery generated refusal rather than7. Content gate
  failed, keep artifact. Investigate combined unanswered text/audio prompt.
  Both inference submodule worktrees clean, original GPU models unchanged.
- Resume: pinned skill/plan restored; tracked diff remains only README.
  GPU replay7416 exited1, artifact realtime_check_20261025T170932Z_f6ec9646.
  Actual prompt snapshots show final order audio, old city text, audio hint.
  Preserve failed evidence, correct MiMo chronological model-input rendering,
  add regression, rerun actual GPU before8080 swap. HostTests44760 still running.
  jq read failed127 (not installed); Node structured JSON redaction succeeded.
- HostTests44760 exited1: four runner tests pass; disconnect leaves connection
  registered past5s. aiohttp handler_cancellation can interrupt its finally awaits.
  Move finalization into a tracked shielded task and drain tasks at app cleanup.
  MiMo model-input now preserves distinct chronological user items and skips
  empty content only; no ledger mutation or Qwen inference/submodule change.
  Added actual-runner unheard-text -> voice ordering regression. Retest required.
- Retest26273: HostTests and four prior runner tests pass, added voice-order
  test rejected near-silent fixture with response_create_without_input.
  Replace near-zero amplitude fixture with effective speech amplitude.
  Verified vadtest04 supervisor/child argv and PGID before SIGINT; session66116
  exited0. Started vadtest05 session54329/child326225;8080/models unchanged.
  Node profile syntax, whitespace and Git status checks pass.
  One combined patch failed on a mismatched progress context; corrected exactly.
- GPU80414 exited1; artifact realtime_check_20261025T172114Z_927b90be.
  Automatic voice answer7, ACK/history, actual interruption/cancel and clean
  disconnect pass; recovery repeats prior history question instead of answer7.
  Chronological JSON now confirmed; no weakened assertion or8080 switch.
  Added bounded recovery_probe.py comparing saved input variants on real MiMo,
  no TTS restart/ASR/checkpoint edits. One rg guessed commands.py absent;
  canonical runner source located the actual response-create contract.
- Focused4371 exited0:6 tests PASS, including unheard-text->voice ordering
  and HTTP disconnect/reconnect. Whitespace PASS.
- Recovery probe56521 exited0;76ca351f four HTTP200 results:
  current_audio_only=7; chronological separate users=old history reply;
  explicit_latest=7; merged_chronological=7. Adopt chronological user merger
  without reordering media, extra latest-answer hints, empty assistant or
  ledger pruning. Update regression expectation for merged input.
- Final-merger focused35810 exited0: all6 actual runner/host tests PASS.
  Node VM original qwen3-turn -> MiMo profile contract PASS (model, server_vad,
  barge_in_on_speech and input append). Owned vadtest05 exited0.
  Isolated vadtest06 session16210/child334549 starting; GPU23061 waiting on
  ready page, no8080 switch. Both models remain original.
- GPU23061 exited1 before UI ready: artifact cb266532 has cases=[],
  startup wait180s exhausted because source/env initialization lagged launch.
  Not an inference/content result. Extend only ready wait to600s; real turn
  timeout and content gates unchanged. No UI/model retry required.
- GPU75841 exited0: realtime_check_20261025T172931Z_0fc2b2d2 PASS.
  Real Silero voice3+4->7, PCM1.92s/RMS.08308; ACK/history followup correct;
  speech_started cancels actual MiMo/TTS HTTP contexts, new auto-commit answers7,
  no old PCM after cancelled response, final ACK and disconnect tasks=0.
  Final runner35810 PASS6. Ready wait fix verified, original profile contract PASS.
  Record server-side narrow slice complete; broad Phase5/semantic/browser gates
  remain in_progress. Next: owned8080 UI swap only, no model restart/debug dump.
- First stop guard rejected ownership because argv NUL separators were treated
  as spaces; no signal sent. Structured argv/role/attempt/PGID verification
  then succeeded, old8080 manual UI64792 exited0. GPU models untouched.
  New live8080 UI84101 starting, final GPU12673 waiting for ready.
  Added additive realtime_vad_live knowledge and README navigation/current
  timestamp; preserve historical snapshots and failures.
- live8080 startup84101 exited1 at bind probe errno98 before log/child creation;
  tail correctly found no log. No foreign process signalled. Subsequent
  structured /proc TCP and UI argv inventory finds no8080 listener/connection,
  old UI exit0 confirmed. Transient socket reuse is plausible, not proven.
  Retry with new attempt live8080_02 after observed port release; checker12673
  still waiting for ready. No code/model change.
- New live8080_02 child343636/supervisor343381/session43259 created17:35:54Z.
  Final checker12673 awaits readiness. Both submodule git status completed0
  with no changes; whitespace PASS. Update live knowledge to exact02 manifest.
- Final8080 GPU12673 exited0: realtime_check_20261025T173356Z_b5683805 PASS.
  Auto voice3+4->7 PCM1.92s/RMS.08308, history correct, real speech cancel and
  recovery7/no stale output/ACK pass. Timestamp names checker start; actual
  voice tests completed17:37Z after UI ready. No Mac mic/listening claim.
- Verified isolated vadtest06 child/supervisor argv/role/attempt/PGID before
  SIGINT; session16210 exited0. Final read-only handoff check exited0:
  UI343636/supervisor343381 exact manifests/NO_PROXY/no_proxy/no debug dump,
  models187389/187446 unchanged,8080=currentIP,8090/8093=loopback,
  no7865/7866 listeners. Home/profile/app/capture/playback/tts/manual HTTP200,
  health{mimo:true,tts:true}. Mac user-agent status polling observed only;
  do not interpret it as actual microphone/playback acceptance.
- Mark server-side requested realtime VAD slice complete; broad Phase5,
  semantic/browser/idle/content/performance gates remain open. All verification
  and old/test UI sessions finished; requested models38811/78763/liveUI43259
  retained for user. No install/weights/submodule change/commit/push.
- Approved no-clobber publication copied only realtime_vad_design/live new
  files to external user Doc/stage3-mimo-single-omni; both diff -q checks0.
  Final whitespace check0. All one-shot verification helpers completed;
  only user-requested model38811/TTS78763/liveUI43259 sessions remain live.

## 2026-10-26: Diagnose Per-Turn Voice Drift
- Scope: answer user's voice-consistency question by tracing the current
  request/speaker/sampling path; no automatic code change or model restart.
- Restored selected plan, findings, progress and stage realtime records.
  Parent status: tracked README change plus existing untracked planning/docs/
  experiments; neither submodule reported dirty. Preserve all existing work.
- Read realtime/backend payload and Qwen3-TTS adapter/speech protocol.
  Confirmed source fixed vivian/Auto/seed42 and independent sentence requests;
  causal attribution and current deployed conditioning remain pending.
- Inspected preserved tts_restart01.log tail: successful speech HTTP200, but
  no speaker/sampling fields and timestamps on October25. Not fresh health
  or timbre verification. No tests, service changes or new audio artifacts yet.
- Traced CustomVoice prompt builder (spk_id embedding) and speech seed forwarding;
  seed reaches stage0 and tts_local_seed. Auto vs Chinese and blank instructions
  differ in conditioning, not selected speaker identity.
- ps -p187389,187446,343636 exited1 in sandbox with no rows; runtime ownership
  not yet established. Guessed configs/qwen3_tts.yaml read exited2 (missing);
  use manifest's actual qwen3_tts_h20.yaml next. No repeated guessed-path probe.
- Read actual H20/base deploy configs and historical startup defaults. Local
  checkpoint config confirms vivian3065 (slow shared-filesystem read completed0).
- Escalated ps exited1 (no historical PIDs); pgrep exited1 (no matching
  service); curl local8093/health exited7/HTTP000. hostname -I exited0 and
  identifies different host interfaces including28.29.218.180 rather than
  prior28.29.210.210. No inference that prior host services stopped.
- Additional guessed MRV2 worker/gpu path search exited2; used rg --files
  instead to locate actual worker modules. No inference code edits.
- External primary-source lookup returned no usable result; diagnosis rests
  on local request/adapter/prompt/seed/config paths, not web claims.
- Added voice_consistency_20261026.md and README navigation; selected plan
  next action now records user feedback and actual-host GPU comparisons.
  No phase gate closed. git diff --check passed0 before final doc additions;
  final documentation checks and additive publication follow.
- No interpreter/import probe or GPU synthesis was performed because no
  serving process was located on this different host. No CPU tests,
  installs, process stops, service restarts, commit or push.
- Final git diff --check exited0. Additional AR/generation runner seed-name
  search exited1 with no matches; not counted as runtime seed validation.
- Approved cp -n published only the new voice diagnosis to external Omni/Doc;
  diff -q exited0 and confirms identical snapshot. All one-shot checks ended.
  Diagnosis remains open: no fresh deployed GPU/audio consistency acceptance.

## 2026-10-26: User-Requested Full Service Startup
- User now requests service startup, superseding diagnosis-only scope.
  Reuse complete realtime_web/Silero/runner -> MiMo -> independent TTS path;
  preserve fixed vivian/Auto/seed42 and all older deployments/artifacts.
- planning-with-files selected the existing task directory. Read plan,
  findings/progress and realtime live/README plus launch/runtime/checker code.
- git status completed0: existing README changes and untracked planning/docs/
  experiments remain; neither submodule dirty. git diff --stat: README +2.
- nvidia-smi: all eight H20 cards idle (0MiB). env.sh then conda activate omni
  probe completed0: Python is omni/bin/python, default imports target sibling
  vllm-src/vllm-omni. Current host welm45-deepep-2 includes28.29.218.180;
  loopback8080/8090/8093 connect_ex111 (no service reached).
- Scope before runtime creation: existing prepare_runtime.py creates an
  exclusive timestamp/UUID source+binary overlay/manifest; run_service.py
  records owned processes and exclusive logs. MiMo GPUs0-3/8090, TTS GPU4/8093,
  UI no GPU/currentIP8080 with NO_PROXY/no_proxy. No inference edits,
  installations or old process stops. Validate fresh automatic voice,
  history and speech interruption before declaring startup ready.
- prepare_runtime session56267 exited0, new exclusive run:
  workspace/logs/20261026T060227Z_mimo_single_phase2_b8e9f10b.
  No relevant serving processes found (pgrep1, empty), source compatibility
  guard passed. Current-source/native-import/bind verification6820 running.
  Historical passing replay identifies preserved fixture at
  20261025T143656Z_mimo_single_phase2_a205c357/
  integration_check_20261025T161630Z_f12d5afb/input.wav; reuse read-only input,
  never reuse output directory.
- Current import/native/bind probe6820 exited0: omni interpreter,
  new run runtime/vllm and current vllm-omni roots, existing _C extension
  loaded, loopback8090/8093 and currentIP8080 bind PASS. Historical version
  warning retained; no compatibility failure at this checkpoint.
- Started existing supervisors, attempt startup01: MiMo session4160 child13046,
  TTS session85461 child13083, realtime UI session65741 child13059.
  Exclusive launch/log files in new run; actual readiness pending.
  Health watcher6916 runs without environment proxies, wait limit1800s.
- UI loaded actual TorchSileroBackend at06:07:58Z; HTTP200 by watcher30s.
  Models remain starting (not accepted by page health). MiMo architecture
  resolved and EngineCore15600 plus TP4 workers created; TTS talker resolved
  and stage process16999 created. Process inspection shows active dependency
  initialization, not service exit. Same optional/deprecation warnings retained.
- Launch manifests confirm supervisor12804/MiMo13046/session4160,
  supervisor12864/TTS13083/session85461 and supervisor12823/UI13059/session65741.
  First weight-load progress06:13:15Z:65 MiMo shards,161.06GiB checkpoint.
  Optional DeepGEMM GLIBCXX_3.4.31 import warning reproduced; existing MARLIN
  fallback selected and weight loading proceeds, no library/install change.
- MiMo completed65/65 shards at06:15:57Z, all ranks loaded41.57GiB by06:16:40Z.
  torch.compile completed51.75s at06:17:47Z. Shared-memory broadcast wait
  informational message occurred during compilation; no failure/restart.
- TTS stage0 EngineCore ready at06:17:26Z; stage1 process starting. Health
  watcher still waits for both complete model APIs; UI200 is not full readiness.
- Repeated startup requests recovered the same three supervisors; no duplicate
  launch. Watcher6916 exited0: MiMo HTTP200 at810s, ALL SERVICES READY.
  Logs confirm full TTS API ready06:19:24Z and MiMo06:20:43Z.
- Recovery checks: selected resolver returned the existing named plan; host
  PLAN_ID/PWF_PLAN_ROOT are unset (printenv exit1), so task-specific selectors
  were supplied to the read-only resolver. Parent README +2 and existing
  untracked files preserved; both submodule status checks empty/exit0.
- Approved hostname -I again confirms28.29.218.180. Published current URL and
  matching fresh Mac Chrome profile in commentary, not old IP or localhost.
  Next run existing GPU realtime checker with exclusive output directory;
  readiness does not count as voice/content/cancellation acceptance.

## 2026-10-26: New Session Recovery And Fresh Realtime Replay
- Scope before execution: read the complete selected triplet, active phase
  design/live/voice records and parent/submodule changes, then continue the
  pending startup01 GPU realtime checker. No new plan, inference edits,
  restart, install, checkpoint changes or session-store reads.
- Host PLAN_ID/PWF_PLAN_ROOT unset; task-specific read-only resolver returned
  .planning/2026-10-25-mimo-single-omni-duplex. Shared pointer unchanged.
- Git: README.md +2; existing untracked planning/AGENTS/stage3/experiments
  preserved. Staged diff empty; both duplex-stage2 submodules clean.
- Newest handoff is startup01/b8e9f10b, not the October25 deployment quoted
  in the plan head. Fresh hostname confirms current28.29.218.180.
- source env.sh then conda activate omni succeeded with approval. Executable
  omni/bin/python; default editable imports still target sibling sources.
  All three live /proc environments instead pin b8e9f10b/runtime plus this
  repository's vllm-omni; pinned module-origin probe resolves correctly.
- Live children13046/MiMo,13083/TTS,13059/UI match launch argv/cwd/Python,
  CUDA visibility0-3/4/empty and explicit NO_PROXY/no_proxy. Children have
  PPID1; supervisors12804/12864/12823 absent (ps exit1). No process stopped;
  future shutdown must verify current child/PGID, not signal old supervisors.
- Fresh readiness: MiMo8090 HTTP200, TTS8093 HTTP200 healthy, UI8080
  /api/status HTTP200 with mimo=true/tts=true. No inference acceptance yet.
- H20 inventory before replay: GPUs0-3 each89149MiB, GPU4 16817MiB,
  GPU5-7 empty; utilization0%. No new model allocation needed.
- Recovery errors: known sandbox env.sh read-only setup warnings and denied
  hostname resolved by approved normal setup/discovery. ss remains absent;
  use structured /proc TCP. Broad pgrep included tool-shell text; exact PID/
  argv inspection established ownership. Two progress append context failures
  changed nothing; reread wrapped final bullet and corrected exact context.
- Pending execution: existing check_realtime_gpu.py, current UI and preserved
  f12d5afb/input.wav, exclusive new timestamp/UUID output under ignored
  b8e9f10b. Keep vivian/Auto/seed42. Browser/listening/strict idle gates stay open.

## 2026-10-26: User-Requested Repository Checkpoint And Shutdown
- User considers basic MiMo+TTS integration ready to publish; requests commit/
  push to the existing repository, then explicitly authorizes stopping current
  project services. Continue publication; no further GPU replay/startup.
- The previous checker launch was interrupted by the user. Current exact
  Python-process inventory finds no checker; top-level b8e9f10b directory scan
  finds no new realtime_check result. No successful replay or exit code claimed.
- Scope before edits: commit only existing project implementation, focused
  tests, plan triplet/active pointer, AGENTS and stage3 knowledge. Update stale
  README wording and add current checkpoint plus version/config digest manifest.
  Keep model weights, raw audio/logs/caches, credential scripts and binaries
  outside Git. Neither submodule has changes or a new gitlink.
- Read-only task-pinned resolver returned the existing plan. Approved env.sh
  and github_env.sh initialization followed by GIT_TERMINAL_PROMPT=0
  git fetch origin exited0. HEAD...origin/main is0/0; normal push planned.
  Remote is Applauzzz/duplex-omni, current branch main. No force/rebase/reset.
- Precommit scan found no private-key/token/credential-URL patterns in scoped
  project files (rg exit1 means no matches). Node child_process git wrapper
  reported EPERM despite producing remote URL; direct git config succeeded.
- Fresh test command after env.sh + conda activate omni, CUDA visibility empty,
  PYTHONPATH=b8e9f10b/runtime:this-repo/vllm-omni:
  cd workspace/experiments/20261025_mimo_tts_integration;
  python -B -m unittest test_integration test_realtime -v.
  Result17/17 PASS, reported31.010s execution after slow imports (session31294).
  Interpreter omni/bin/python, vllm overlay and current vllm_omni verified.
  Known version mismatch/CPU CUDA_HOME/aiohttp deprecation warnings retained.
  Injected TTS failure traceback is an expected successful recovery test.
- node workspace/experiments/20261025_mimo_tts_integration/check_frontend.js
  exited0: history, played-prefix interruption, stale completion, invalid PCM.
  No new full CPU suite, GPU content replay or browser acceptance claimed.
- Owned shutdown: approved source env.sh then omni; Python verified all three
  child argv, cwd, PGID==PID and PYTHONPATH against startup01 manifests before
  sending SIGINT to UI13059, TTS13083 and MiMo13046 process groups.
  Shutdown command exited0; no force kill or unknown process signalled.
- Exclusive shutdown artifacts:
  workspace/logs/20261026T060227Z_mimo_single_phase2_b8e9f10b/
  shutdown_20261026T080615Z_c9f43147/request.json and result.json.
  Children are exited zombies under PID1, not running services; all eight H20
  at0MiB/0%, and structured /proc TCP/TCP6 check finds no8080/8090/8093 listener.
  Supervisor absence prevents collecting their normal *_exit.json; do not
  invent process exit codes. Shutdown evidence is independent of strict
  during-inference stage-idle acceptance.
- Documentation/manifest edits do not change inference behavior. Remaining
  voice consistency, browser, semantic/acoustic, strict idle and performance
  gates remain open. Staging, final checks, commit and push results follow.

## 2026-10-26: New Session Recovery And Publication
- User requested recovery of the existing plan triplet, inspection of Git
  changes, status summary, and publication of the current MiMo+TTS checkpoint.
- Host PLAN_ID/PWF_PLAN_ROOT unset; read-only resolver with the task-specific
  selectors returned the existing named plan. Read the complete task_plan.md,
  findings.md and progress.md, plus current stage knowledge and checkpoint.
  No plan initialization, session-store access or phase-gate change.
- Parent main tracks origin/main at 0/0 before publication; README.md has two
  navigation lines added. Untracked scope is only the existing plan/pointer,
  AGENTS.md, stage3 knowledge and two project experiment directories. Neither
  vllm-omni nor vllm-src has worktree changes or gitlink updates.
- Read-only scoped credential-pattern scan returned no hits; git diff --check
  exited 0. Initial attempt to read checkpoint JSON in the plan directory
  failed (wrong path); read the actual file in Doc/stage3-mimo-single-omni/.
- sha256sum of the five code/config files in checkpoint_20261026.json matches
  all recorded values. Parent HEAD is the manifest parent_base; local tracking
  origin/main is 0/0. Both submodule worktrees remain clean.
- Publication scope remains parent-owned code/tests/docs/plan only. No model
  restart, GPU replay, environment install or raw output publication.
- Staged exactly 45 scoped files; cached whitespace check passed and no
  submodule gitlink/symlink entries were introduced. Node frontend state check
  passed again. User provided github_env.sh as the Git initialization script.
- Remote verification failures: the first fetch with github_env.sh hung and
  was interrupted (exit 130); sandbox ls-remote failed DNS (exit 128); the
  escalated ls-remote with github_env.sh timed out after 25s (exit 124) without
  an advertised remote SHA. No push or successful remote refresh claimed yet.
- Created local checkpoint commit 98daa7aaec0420d1bd6c5666f328d58cdbae62d6
  (45 files); worktree clean, local main ahead of origin/main by one. Fresh
  frontend Node state check passed. Escalated DNS resolved github.com, but
  HTTPS curl connection timed out (exit 28). A second escalated ls-remote
  timed out after 30s (exit 124); ordinary push after github_env.sh timed
  out after 35s (exit 124). No remote publication verified.
- User suggested clearing proxy variables. An earlier SSH remote check was
  interrupted by the user; no successful SSH result was observed. Process
  inventory after interruption found no running Git/SSH command, only exited
  zombies under PID 1. After sourcing github_env.sh, no proxy variable names
  were set and Git http.proxy/https.proxy/URL rewrite checks were unset.
  Process-local unset of lower/uppercase HTTP(S)/ALL/FTP/NO_PROXY followed by
  ls-remote failed DNS inside sandbox (exit 128) and timed out after 15s
  outside sandbox (exit 124). Unsetting proxies did not restore GitHub access.
  Commit 98daa7a remains ahead by one; no remote push was verified.
- A final normal `git push origin main` after process-local proxy unset also
  timed out after 15s outside sandbox (exit 124), with no success message.
  Remote publication remains pending network access; no forced push, remote
  configuration changes, service startup or additional GPU validation.
