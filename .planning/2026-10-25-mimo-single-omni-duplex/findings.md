# Findings & Decisions

## Realtime Runner Integration Recovery
- Recovery prompt snapshots from vadtest04 confirm Qwen final media-first
  formatting moves latest audio ahead of the unanswered old city text.
  MiMo requires its own chronological model-input view; session ledger and
  ACK-driven retention remain unchanged. Latest real replay f6ec9646 failed
  recovery content (refusal) while automatic VAD, first answer and history passed.
- jq is unavailable; use installed Node JSON parsing to redact audio snapshots.
- Recovery probe76ca351f: current audio only answers7; distinct consecutive
  user messages with history repeat old history reply; explicit-latest hint
  and chronological merged user input both answer7. Choose chronological
  merger without prompt intervention or lost history. No model defect proven.
- Shielded tracked HTTP handler cleanup fixes disconnect/reconnect slot leaks.
  All six actual-runner/host tests pass after effective-amplitude fixture fix.
- Actual runner emits session.created plus an automatic session.updated at open.
  Tests must drain these before testing a later update ACK; detector is not lazy.
- Data-plane model errors fail the protocol response but do not complete the
  model turn. A separate end_of_turn output completes identity/resources.
- Before playback ACK, assistant text can be absent from history entirely.
  Do not assert that the last row is an empty assistant placeholder.
- Existing Silero provider resolved TorchSileroBackend successfully at startup.
  Recorded-speech/GPU integration now passes on isolated7866 and live8080;
  broader acoustic and actual browser acceptance remains open.
- Live8080 GPU artifactb5683805 passes auto voice7, ACK/history and speech
  interruption/recovery7 with no stale PCM. UI343636/supervisor343381;
  models187389/187446 unchanged,7865/7866 no listeners. No debug prompt dump
  enabled on live UI. Browser access log is not microphone/playback acceptance.

## Requirements
- Long-term maintenance of streaming, interruptible, duplex Omni inference.
- Current paths reported by user: Qwen Omni duplex, MiMo-Qwen cascade, standalone MiMo.
- Target: MiMo-only multimodal reasoning with VAD state machine and initial Qwen3-TTS.
- TTS model: `/mnt/geminihzceph/user_whynotzhliu/modelbase/Omni/Qwen3-TTS-12Hz-1.7B-CustomVoice`.
- Read and extend `/mnt/geminihzceph/user_whynotzhliu/Omni/Doc`.
- Independently verifiable stages, decisions, necessary tests, complete failure logs,
  stage status updates, session recovery, and no silent result overwrite.

## Research Findings
- 2026-10-25: no existing plan selected by either installed resolver.
- Initial `git diff --stat` empty; `git status --short --branch` reports
  `main...origin/main` and no tracked/untracked changes before initialization.
- Repository contains `README.md`, `Doc/`, `workspace/`, `vllm-src/`, `vllm-omni/`.
- External historical Doc contains Qwen duplex/service/config documents,
  a 2026-10-14 interruption audio debugging report, legacy notes, and stage2 notes.

## Technical Decisions
| Decision | Rationale |
|----------|-----------|
| Use isolated `.planning/2026-10-25-mimo-single-omni-duplex/` | Protect future parallel tasks and support explicit recovery |
| Keep planning canonical in Git; publish knowledge additively to external Doc | External Doc is outside repository and writable roots |

## Repository README Evidence
- README describes the 2026-10-22 consolidated tree, not a fresh installed/GPU-validated deployment.
- Duplex currently means concurrent input reception and interruptible turn-based output,
  not continuously incremented audio KV inference.
- Stage2 MiMo generates body text via SSE; Qwen thinker still provides real prompt
  embeddings and multimodal hidden states to native Qwen talker/code2wav.
- Bridge requires async chunks plus local SharedMemoryConnector; no MiMo IDs/hidden
  cross the model boundary. Text is retokenized with the Qwen tokenizer.
- Existing session ledger uses playback ACK, not receipt of all transcript/audio,
  to decide assistant history after interruption.
- Historical CPU count (500) and five speech samples are not current baseline results.
- Fork ownership: application strategy/config/tests in parent; engine/stage mechanisms
  in vllm-omni; low-level model kernels/loading in vllm-src. Current state machine
  and bridge remain engine-coupled and should not be mechanically moved.
- README explicitly warns current validation scripts overwrite turn files and speech
  transcription results. Future experiments need new run directories before use.
- Stage2 hardware history: MiMo TP4 GPUs 0-3 and three Qwen stages GPUs 4-6;
  model `MiMo-V2.6-Flash-RL`, served alias `mimo-v2.6-flash`.
- Submodules track fork branch duplex-stage2; parent gitlinks pin actual versions.

## Historical Evidence and New Code Inventory
- External stage2 README/plan_a were read. Standalone MiMo TP4/TP8 smoke was
  recorded on 2026-10-19; FP8 fused-QKV shard failures were fixed by backporting
  mimo_v2.py/mimo_v2_mtp.py. Those historical tests must not be rerun unnecessarily.
- Historical MiMo-V2.6-Flash-RL is not the separate `mimo_audio` model/pipeline.
- Current parent-pinned submodules:
  - vllm-omni `6a841874ef56cf0590c5f5c24889a4ca65e6ac15`.
  - vllm-src `ba860768a965efadcf059089c04862c46e568242`.
- Existing tree already includes Qwen3-TTS talker/code2wav, pipeline, deploy config,
  HTTP/WebSocket tests, streaming chunk tests, and CustomVoice E2E tests.
  Prefer investigating this implementation before choosing a new TTS runtime.
- Local CustomVoice folder contains model.safetensors (3,833,402,552 bytes),
  configuration, generation configuration, text tokenizer, and speech_tokenizer.
- Older 2026-09-29 architecture report says realtime and async_chunk conflict.
  Later consolidated README and stage2 implementation use both. Treat the old
  restriction as version-specific history, not the current architecture.
- Historical plan text includes old paths/environment and dangerous global kill
  suggestions. It is evidence only; current preservation/resource rules prevail.

## Source-Level TTS and Turn Policy Facts
- `qwen3_tts/pipeline.py` defines independent talker -> code2wav stages and
  does not declare a duplex plugin. It is not a drop-in Qwen Omni duplex deployment.
- `deploy/qwen3_tts.yaml`: async_chunk true, MRV2 default, both stages devices "0",
  GPU memory utilization 0.3 each, initial codec chunk 1 frame, steady 25,
  decoder left context 72. Defaults claim H100 verification, not local H20 acceptance.
- Local model config: custom_voice / 1b7, 16 code groups, nine named speakers;
  speech tokenizer produces 24 kHz PCM and 1,920 samples per codec frame (12.5 fps).
- `overlap_policy.py` uses explicit actions, acoustic VAD/duration/RMS, and a
  short acknowledgement transcript whitelist. It is not a learned semantic VAD.
- `commit_policy.py` consumes immutable session/playback/speech snapshots; useful
  pattern for a separately testable policy/state reducer.
- Legacy interruption bug: empty assistant prompt turns caused empty thinker output
  and unconditional talker audio; fixed prompt view omits empty assistant entries.
- Legacy residual: partial unaligned playback can commit zero assistant text and
  make the next model prompt look like unanswered accumulated user questions.
  Preserve this as a regression scenario, not an excuse to alter existing policies.
- Historical debug report actually records 599 passed, 1 skipped, 1 error
  (missing mocker fixture); this is not an entirely passing current baseline.
- `DuplexStagePort` exposes stage_count, sampling_defaults, ensure_request,
  submit, cleanup, and abort_requests with fenced immutable request DTOs.
  A project-owned external service adapter is a plausible reuse boundary,
  but virtual-stage output/finalization and import requirements need a mock proof.
- Runner serializes commands/outputs through one mailbox and binds cancellation
  to epochs/fences. Existing engine session contains playback and conversation
  ledgers. Prefer composition over a second independently maintained history.

## Issues Encountered
| Issue | Resolution |
|-------|------------|
| External Doc requires write approval | Approved no-clobber copy published five new files; recursive diff matches Git source |
| Guessed TTS documentation paths do not exist | Discover actual paths with rg --files; code and existing tests remain available |

## Current Integration Constraints
- Source confirms bridge activation explicitly requires Qwen3OmniDuplexPlugin,
  async_chunk, and local SHM. It caps thinker generation at one token, then
  discards its text and emits MiMo text through the existing fenced runner.
- `build_mimo_messages()` imports Qwen plugin/history formatting; `mimo_text_stream()`
  resides in the Qwen-specific bridge alongside torch/SHM dependencies.
  A MiMo-only service needs a narrow model-independent SSE/input boundary, not
  wholesale import of this bridge into a new gateway.
- TTS speech WebSocket source says default split_granularity=none buffers until
  input.done; sentence/clause splitting starts separate synthesis requests before
  input.done. That is segmented input streaming, not one token-fed continuous TTS KV.
- Speech handler awaits generation in the receive loop. Public response.cancel
  is not listed by this TTS protocol; disconnect/abort effectiveness needs tests.
- Current turn detection validates only server_vad and rejects
  interrupt_response=false; semantic confirmation cannot be inserted by merely
  passing an extra field to the old deployment.
- Legacy start_services.py opens fixed log paths with "w" and overwrites PID JSON.
  Do not execute it for new runs before adding an isolated artifact/output contract.

## Environment Inventory (2026-10-25, Read-Only)
- Default Python: `.../my_envs/miniconda3/envs/liu/bin/python`, 3.12.14.
- Metadata: torch 2.7.1+cu126; transformers 4.56.2; pytest 9.1.1; aiohttp 3.14.3.
- vllm, vllm_omni, pytest_mock, qwen_tts, silero_vad, and onnxruntime not discoverable
  in the default interpreter. pytest_asyncio is installed.
- Both submodule branches are duplex-stage2 and clean. No source modifications made.
- Checkpoint architecture says MiMoV2ForCausalLM; registry also includes separate
  MiMoV2OmniForCausalLM. Actual multimodal class selection/preprocessing in the
  serving environment needs tracing before assuming new tree supports raw audio.
- Follow-up search found `model_arch_config_convertor.py:643` explicitly promotes
  multimodal MiMo config to MiMoV2OmniForCausalLM; inspect its condition/runtime next.
- Historical omni interpreter and vllm executable exist, so inspect that environment
  read-only before deciding a new build is needed.
- Existing `SpeechTextSplitter` is stdlib-only and handles decimal separators,
  abbreviations, punctuation/closing-delimiter tails, and multilingual delimiters.
  Reuse its parser; add exact-source spans externally because its emitted units
  strip boundary whitespace and do not themselves track original text offsets.
- Existing TTS word timestamps have optional aligner dependencies; presence of
  an API flag is not evidence of free, native, low-latency word alignment.
- Read-only omni probe: Python 3.12.14, torch 2.13.0+cu129, transformers 5.14.1,
  VAD packages present, pytest/pytest_asyncio/pytest_mock absent.
- omni imports point to `/mnt/geminihzceph/user_whynotzhliu/Omni/vllm-src`
  and `/mnt/geminihzceph/user_whynotzhliu/Omni/vllm-omni`, NOT this repository's
  submodules. Do not reinstall or redirect a serving environment silently.
- Verified conversion condition: nonempty vision_config triggers
  MiMoV2OmniForCausalLM; model constructs BF16 vision/audio towers and wraps
  MiMoV2FlashForCausalLM. Class-selection uncertainty resolved statically;
  actual checkpoint loading/audio acceptance remains a runtime gate.
- Source speech HTTP streaming closes engine generators in a shielded cancel
  scope. Prefer isolated HTTP PCM requests for first adapter, but prove both
  TTS-stage abort and MiMo disconnect cancellation in real serving tests.
- Parent baseline HEAD: `9628f6c`, 2026-10-22 docs commit.

## External Primary-Source Verification (2026-10-25)
- Official Qwen repository: `https://github.com/QwenLM/Qwen3-TTS`.
- Official CustomVoice card:
  `https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice`.
- Official vLLM speech API:
  `https://docs.vllm.ai/projects/vllm-omni/en/stable/serving/speech_api/`.
- Official docs agree the TTS speech WebSocket buffers until input.done by default
  and sentence/clause splitting yields separate synthesis requests.
- Official vLLM recipe lists CustomVoice on the standalone /v1/audio/speech route.
  Online current docs supplement discovery only; pinned local code controls implementation.

## Phase 1 Delivery
- Canonical knowledge: `Doc/stage3-mimo-single-omni/` (five documents).
- Approved external snapshot:
  `/mnt/geminihzceph/user_whynotzhliu/Omni/Doc/stage3-mimo-single-omni/`.
- Publication command uses `cp -R -n -T`; existing files are never replaced.
  `diff -qr` returned exit 0 after publication.
- Parent AGENTS.md supplies session recovery, ownership, tests, and preservation.
- Only README navigation, AGENTS.md, knowledge documents, and named planning files
  changed. Both inference submodules remain untouched; no commit/push performed.
- Phase 1 complete; Phases 2-6 pending. This is not completion of the overall model goal.

## Resources
- User-provided planning skill was read fully; contents match installed skill.
- Skill scripts: `/mnt/geminihzceph/user_whynotzhliu/agent_tools/planning-with-files/.agents/skills/planning-with-files/scripts/`.

## Phase 2 Start (2026-10-25)
- User authorized Phase 2 GPU-first and specified source my_envs/env.sh.
- Recovery read selected plan/findings/progress and AGENTS.md; prior documentation
  changes remain preserved. No competing plan created.
- env.sh initializes liu by default and includes SSH/chmod/link writes outside
  writable roots. Initial sandbox source emitted read-only errors; escalated
  initialization requested. Do not inspect or log secret script contents.
- GPU probe: eight NVIDIA H20, 97,871 MiB each, all at 0 MiB used at start.
- `ss` is unavailable; port probes will use Python sockets without killing services.
- Process-local PYTHONPATH selects current source but current checkout contains no
  native extensions. Actual import fails in vllm_flash_attn (FA2/FA3 absent).
- Compiled sibling vllm-src HEAD is ced6857afa0ea7b2e3f0846a62e1394e90f15607.
  Diff to pinned current HEAD changes requirements plus MiMo Python files only;
  no CUDA/C++ interface changes. Reuse its binaries via a run-local symlink overlay,
  not editable reinstall, old-source fallback, or writes to either source tree.
- vLLM-Omni reports 0.1.0 versus vLLM 0.30.1.dev0; warning retained for runtime
  validation. CLI import also hits missing extensions, not yet a GPU model failure.
- Generated dependency overlay must recursively include absent Python interfaces,
  not just native binaries: flashmla, DeepGEMM and other wheel-generated packages.
- Attempt 02 runtime confirms MiMo multimodal architecture, 161.06 GiB checkpoint,
  TP4/EP and MARLIN selection. DeepGEMM optional import warns system libstdc++
  lacks GLIBCXX_3.4.31; inference not yet tested, do not silently preload libraries.
- Binary donor worktree has historical requirements/MiMo Python edits; no changes
  made to it. Current tracked source always wins over donor generated dependencies.
- Real TTS first transport chunk contains 80ms of near-silence: first-byte is
  not first effective speech. Cancellation acceptance must include actual backend
  termination, not just HTTP cleanup or a client-side zero-byte read.
- MiMo02 current-source multimodal service produces content-only SSE and recovers
  after disconnect. Five TTS PCM samples are available for independent GPU ASR.
- Existing offline Whisper checkpoint lacks generation_config/tokenizer files;
  bundled openai-whisper tokenizer can supply in-memory language/task IDs.
- GPU outcomes are recorded in Doc/stage3-mimo-single-omni/phase2_gpu_20261025.md.
  Independent Whisper matches four samples, mixed Qwen TTS has shared ASR bias/
  pronunciation concern. Warm PCM hashes match cold; effective energy .192-.200s.
- Orchestrator matched abort logs do exist; case-sensitive discovery originally
  missed "Aborted". AsyncOmni uses internal abort helper, not public ID remapping.
  Pipeline counters stable/frontend idle/recovery pass; stage snapshots remain
  nonzero even after ordinary completions. Do not interpret stale gauges as proof.
- /pause and /resume are development routers, not available by default.
  Probes returned404. Source register_vllm_dev_api_routers installs them;
  any subsequent dev-enabled diagnostics must stay isolated/loopback.

## Preview Startup (2026-10-25)
- Gradio is absent from omni, but aiohttp is installed. A loopback experiment UI
  can proxy fixed CustomVoice PCM without installing packages or adding a model
  pipeline. This is not the Phase3 session adapter or Phase4 voice dialogue.
- During new run5f193640 startup, other tasks allocated33188MiB per GPU on all
  eight H20. nvidia-smi reports foreign PIDs3177257-3177264 (outside this process
  namespace) and100% GPU utilization. Do not assume startup inventory reserves
  resources. MiMo90% budget failed with60.82GiB free versus85.57GiB requested.
- MiMo preview01 exited1 and its workers exited gracefully; existing foreign
  tasks were untouched. TTS's two15% stages continue initialization onGPU4.
- No Playwright/Chromium executable or package in the inspected standard caches;
  missing-cache ls returned2, not evidence of an application failure. No install.
- Direct aiohttp proxy test passed at12:54:16Z: page200, TTShealth=true,
  MiMohealth=false, four malformed/invalid input cases400. One Chinese synthesis
  returned4 network chunks,130560 bytes monoPCM16/24kHz,2.72s, RMS.10167.
  First-byte.909s, complete1.929s under sharedGPU contention; not a new latency
  baseline or actual browser audible-onset measurement.
- GPU4 total memory around50013MiB includes foreign33188MiB plus TTS; do not
  attribute total device memory to the preview. TTS and UI are intentionally
  left running, with launch records and owned supervisors for later shutdown.

## User Restart (2026-10-25)
- User reported competing tasks stopped. Fresh GPU inventory confirmsGPU0-3
  andGPU5-7 at0MiB, GPU4 only16821MiB/0% for existing TTS.
- Verified old TTS supervisor107614/child107820 and UI124742/124947 commands
  belong to run5f193640. Restart models only; UI can retain its fixed upstream
  ports and recover without a restart. No application pipeline change implied.
- Restart succeeded: TTS application ready14:53:37Z, MiMo14:54:48Z.
  Minimal MiMo SSE returnedready, DONE=true, reasoning empty,.2998s.
  Preview status reports both backends true; Chinese PCM2.72s/130560bytes,
  RMS.10167, SHA matches the preserved earlier sample. First-byte.8669s,
  complete1.1693s; this is a cold smoke, not a latency distribution.
- Steady inventory: MiMoGPU0-3 each89149MiB, TTSGPU4 16817MiB,
  GPU5-7 empty. New models use runa205c357; retained UI uses run5f193640.

## Direct-IP Access Correction (2026-10-25)
- User's Mac workflow uses server IP/port7865 and an isolated Chrome profile,
  not SSH forwarding. Mac127.0.0.1 cannot reach server127.0.0.1 without a tunnel.
- Approved hostname discovery shows current server address28.29.210.210.
  Historical user address28.29.210.139 is not a current interface.
- At15:02Z, wildcard7865 probe is free; loopback7866 status200 shows both
  models healthy. Direct current-IP7866 refuses TCP, consistent with UI binding.
- Only UI receives configurable host; default remains loopback and both model
  commands stay loopback. Bind the requested preview to the specific current
  interface rather than all interfaces. No authentication/production exposure.
- Same-origin browser requests already fit direct access; no HTML change needed.
  Parameterize the existing GPU preview check URL and preserve its old default.
- UI directip01 now bound28.29.210.210:7865, child216007/supervisor215773,
  session19541. Old UI preview02 exited0; both original GPU models retained.
- At15:12:16Z direct-IP page/status200, both models healthy, four invalid inputs400.
  GPU PCM130560bytes/2.72s/RMS.10167,4chunks; first-byte.02927s,total.26842s.
  Same PCM SHA as earlier; local interface test does not prove Mac connectivity.

## Mac 502 Report (2026-10-25)
- User's browser received JSON with status502 Bad Gateway, an IT hotline,
  enterprise-message link and version3.1.3.119. This is not the preview index
  HTML or its status JSON; intermediary origin is a hypothesis to verify.
- The prior claim of a usable direct-IP entry was stronger than the evidence:
  server-local access does not prove client routing or gateway reachability.
- A current interface IP need not be the historical externally routed address.
  Do not infer that28.29.210.139 is obsolete merely because it is not local.
- Keep current UI and models running while investigating; no deployment or
  security-policy changes before identifying the failing network path.
- User specified Doc/Qwen3_Omni_duplex_legacy/02_running.md; full read confirms
  deployed UI8080, default7865 is not the actual allowed entry. The document
  records ports80/8080/8081/443 as allowed; current policy not independently
  verified. Therefore port choice is a concrete deployment mismatch to correct.
- Legacy doc also requires a fresh/fully closed Chrome profile for new flags
  and NO_PROXY/no_proxy for loopback UI upstreams. Current aiohttp already
  uses trust_env=False. Do not use legacy broad pkill or startup scripts.
- At15:28:30Z all original processes/commands match records, direct page200
  text/html from aiohttp, status/backends200. ip utility absent; archived
  /proc/net/route and hostname output instead. No network settings changed.
- Server-only proxy comparison: trust_env=False200 vs trust_env=True403,
  not the user's502; confirms server proxy behavior, not Mac proxy cause.
- Wildcard8080 bind probe passes. Plan additional owned UI on specific current
  interface8080, test before retiring7865, keep both GPU backends untouched.
- UI allowed8080_01 ready at15:36:26Z, child/PGID230994, supervisor230676,
  session54807; specific current-IP8080. Original model PIDs unchanged.
- GPU check at15:36:55Z passes page/status200, four invalid400, PCM200,
  130560bytes/2.72s/RMS.10167,5networkchunks,.02882s first-byte,.26875s total.
  Old7865 owned supervisor stopped after8080 checks; graceful exit0.
- Final /proc listener check: only UI8080 at current IP and model8090/8093
  loopback. Explicit NO_PROXY/no_proxy verified on new UI; client trust_env=False.
  No Mac acceptance yet; do not present historical allowed-port policy as a
  measured current firewall rule or definitively attribute502 to the port.

## MiMo-To-TTS Integration Scope (2026-10-25)
- User confirms Mac TTS preview works and wants MiMo connected to TTS.
  Network troubleshooting is no longer the active task.
- Existing MiMo bridge SSE logic is useful evidence but importing it would
  pull Qwen/torch/history/SHM into the new service. Build a narrow independent
  client with its same content-only/finish/DONE validation.
- Reuse pinned SpeechTextSplitter, loaded directly as a stdlib-only module
  from the current repository (avoid importing heavyweight package init).
- Add manual-turn application separately, preserve old preview assets/results,
  /tts endpoint and original model backends. This is not old session runner
  composition or semantic/acoustic VAD completion.
- Ordered one-worker TTS synthesis, bounded segment queue, exact source spans,
  explicit final-text versus audio-done, and disconnect cancellation required.
- Implemented backend/server/chat and tests in new20261025_mimo_tts_integration.
  No Qwen Omni bridge/model/session import; only direct stdlib splitter module.
- Protocol11 tests pass, deterministic Node playback/history checks pass.
  These are narrow behavior tests, not a CPU regression prerequisite.
- Actual GPU MiMo content feeds TTS:2+2=four,3+4audio=seven, history remembers
  prior question, cancellation and recovery pass. Slow injectedMiMo with actual
  GPU TTS firstPCM precedesmodel_done; effective audible onset not measured.
- Live dialogue8080 child256583/supervisor256349/session64792, original model
  processes retained. Old8080 and isolated7866 UI sessions exited0.
- Manual-turn slice complete; engine runner/ledger reuse proof not implemented.
  Client-local bounded completed history is provisional, not engine protocol
  compatibility or full semantic/acoustic/duplex completion.
- Final16:20Z checks confirm all three owned services match launch manifests,
  UI8080/currentIP and model8090/8093loopback only, page/tts/worklet200 and both
  health flags true. Original speech GPU regression matches preserved PCM SHA;
  artifact preview_check_20261025T162007Z. Both submodules remain clean.

## Existing Voice Workflow Correction
- User explicitly requests existing vLLM frontend, VAD and direct MiMo audio,
  not a separate manual recording demo. Previous implementation was a detour.
- Reread stage2 README/plan_a and stage1 architecture/VAD/running docs.
  Stage2 explicitly preserves realtime_web, VAD, playback ACK, history and
  raw audio to MiMo. Engine server_vad is frontend-independent, not a property
  requiring Qwen reasoning. Learned semantic endpointing remains separate.
- Existing frontend qwen3-turn/vad uploads continuous PCM at24kHz; gate/stt
  are explicit diagnostic/manual modes. Reuse protocol and capture/playback.
- Canonical runner accepts a model-neutral DuplexStagePort (contracts.py),
  OmniRequestOutput stage outputs and an independent plugin. Existing Qwen
  turn PCM/history helpers can be reused without its processor/prefill.
  Runner marks support exact cumulative completed-segment audio/text bounds.

## Voice Consistency Report (2026-10-26)
- User reports perceptibly different timbre on each conversation turn. This is
  listening feedback, not evidence of whole-browser acceptance or a known cause.
- Current realtime_backend.py passes fixed vivian/Auto to backend.run. The
  backend sends task_type=CustomVoice and seed=42 for every sentence segment.
  It does not send instructions or explicit sampling overrides.
- Each segment is a separate HTTP synthesis request, with no acoustic
  continuation/reference carried between sentences or turns. Whether this
  accounts for the reported severity remains unverified.
- Source adapter validates built-in voice names and maps request.voice into
  the speaker field. Inspect downstream speaker conditioning and actual
  deployed roots before concluding that the voice parameter is ignored.
- Prior same-text waveform repeat checks do not constitute cross-text timbre
  acceptance. Do not propose adding a seed that is already present.
- Current prompt builder explicitly embeds the configured CustomVoice spk_id
  into every prompt and rejects unknown/missing speakers. The speech entrypoint
  maps seed to stage0 seed and tts_local_seed. No source evidence of intentional
  speaker rotation or ignored voice/seed so far.
- Auto omits an explicit codec language ID for non-dialect speakers; explicit
  Chinese supplies one. Empty instructions add no style conditioning.
- Historical manifest points to qwen3_tts_h20.yaml, not a configs subdirectory.
  Sandbox ps found none of the October25 PIDs; distinguish namespace restrictions
  from actual service exit before making any runtime claim.
- Escalated ps also found none of the three historical PIDs; relevant pgrep
  found no matching service. Local8093/health failed (curl7/HTTP000).
  hostname -I includes28.29.218.180, not recorded deployment28.29.210.210.
  Current host is different; do not conclude the earlier services are stopped.
- H20 YAML inherits talker/subtalker temperature0.9/top_k50 and subtalker
  top_p1.0/do_sample=true. Preserved startup log confirms nine speakers and
  sampling defaults. Fixed seed does not establish cross-text identity.
- Current diagnosis cannot distinguish severe speaker drift from delivery
  changes without fresh audio. No corrective parameter is accepted yet.

## Full Startup Recovery (2026-10-26)
- New run b8e9f10b retains the original realtime frontend and real Silero;
  all three services reached HTTP200. Current UI28.29.218.180:8080,
  MiMo127.0.0.1:8090 and TTS127.0.0.1:8093. Watcher6916 completed0.
- Exact launch manifests record MiMo13046/supervisor12804, TTS13083/12864,
  UI13059/12823, attempt startup01. Do not repeat startup on repeated requests.
- Preserve vivian/Auto/seed42; per-turn voice diagnosis remains open.
  Fresh voice replay and Mac microphone/listening are distinct from readiness.

## Fresh Session Recovery (2026-10-26)
- Newest progress handoff supersedes the October25 PIDs quoted in the plan:
  b8e9f10b/startup01 serves current28.29.218.180:8080. Fresh HTTP checks pass
  for UI and both private model APIs; no duplicate startup needed.
- Children13046/13083/13059 match manifests and current-source PYTHONPATH.
  Historical supervisors12804/12864/12823 are absent; children have PPID1.
  Historical tool session identifiers are not evidence of live supervision.
- Per-turn voice consistency, actual browser capture/playback, strict stage
  idle, semantic policy and wider performance/regression remain unaccepted.

## Publication Checkpoint And Shutdown (2026-10-26)
- User accepts the current basic integration for repository publication,
  without closing wider phase gates. Fresh focused protocol/runner/host
  tests17/17 and deterministic Node frontend checks pass.
- Project UI/MiMo/TTS were stopped by user authorization with manifest-verified
  process-group SIGINT. Eight H20 GPUs are empty and service ports released.
  Exited child zombies under PID1 consume no model resources; supervisors
  were already absent, so no supervisor-reported exit codes are available.
- Interrupted GPU checker has no discovered completed result. Historical
  passing replay remains the accepted server-side fixture evidence.
