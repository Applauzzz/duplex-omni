# Progress Log

## Session: 2026-10-26

### Current Status
- **Phase:** 5 - Integration acceptance and publication
- **Branch:** `feature/SVAD`
- **Base:** `5c0aeb909c5bc15e8679f960979b6cdb5920654b`

### Actions Taken
- Confirmed published `main` and clean parent/submodule baseline.
- Read the full Stage 4 functional specification supplied by the user.
- Created and switched to `feature/SVAD`.
- Created independent plan `2026-10-26-mimo-semantic-vad`; Stage 3 planning
  records remain intact.
- Located the parent realtime adapter, existing Silero provider and focused
  realtime tests.
- Traced the vllm-omni append, overlap, barge-in, VAD and auto-commit paths.
  Chose a parent-owned explicit semantic_vad adapter; neither submodule will be
  edited for the initial implementation.
- Confirmed the current MiMo port is whole-turn only. FSM Prefill events can be
  delivered to the runner input buffer, but actual model execution begins at
  final commit rather than native incremental KV prefill.
- Implemented the three-state FSM, exact six-token mappings, Reject telemetry,
  Speak Decision boundary, MiMo HTTP VASD/VAED provider, Silero AVAD adapter,
  explicit `semantic_vad` handshake and runner command mapping.
- Added bounded pre-speech prefix retention, exact-once candidate/chunk
  delivery, client clear/cancel reset, and protection against cross-turn tail
  reuse. Ordinary session updates remain supported.
- Added Stage 4 README and kept the supplied functional specification as the
  normative transition source.
- Final review confirmed no parent/submodule ownership violation, no additional
  FSM state, no debounce/timeout decision rule, no credential-pattern match and
  no submodule worktree or gitlink change.
- Created local checkpoint commit c757117 on feature/SVAD. The subsequent push
  command was interrupted by the user; no remote branch publication is claimed.
- User changed acceptance order: do not publish further work before hands-on
  validation. Build a standalone visualization and run only MiMo + FSM/AVAD/
  semantic VAD, with TTS and the full response path out of scope.
- Added standalone `svad_debug_server.py` and `svad_debug.html`: live waveform,
  three-state rail, AVAD probability, VASD/Reject, VAED, FSM events, chunk
  counts, model latency and a transition timeline. Audio sends are serialized
  to one in-flight semantic request so the visible order is deterministic.
- Extended the owned service launcher with `svad-ui`; no TTS role was started.
- New exclusive run:
  `workspace/logs/20261026T105528Z_mimo_single_phase2_daaf8fb0/`.
  Current origin is `http://28.29.217.180:8080/`.
- Owned live processes: SVAD UI child41693/supervisor41692 on CPU and current-IP
  8080; MiMo child42095/supervisor42091 on GPUs0-3 and loopback8090. GPU4-7
  remain unused. Launch manifests are in the new run directory.
- MiMo became healthy at11:26:31Z. UI /health returned mimo=true with1.5ms
  loopback latency; page HTTP200 and expected visualization markers passed.
- Real provider probe artifact `svad_probe_20261026T113528Z`: strict label
  parsing passed. First VASD took24679.3ms (one-time multimodal warmup), VAED
  took55.9ms. Repeated warm probe `svad_repeat_20261026T113921Z`: VASD
  41.8-49.4ms and VAED37.6-39.3ms across three iterations.
- Real WebSocket replay of the preserved2.72s speech fixture passed actual
  AVAD and semantic flow: Silence->Judge; initial NO_BREAK; BREAK/PREFILL to
  Listen at87.3ms; COMPLETE/DECODE to Silence at70.1ms; trailing speech/noise
  returned through Judge to Silence without a second interrupt.
- Synthetic low-amplitude noise returned VASD Reject in67.3ms. This confirms
  the Reject path without claiming broad acoustic false-positive acceptance.
- User requested less transient visualization. Replaced per-chunk state cards
  and rows with a persistent three-node FSM graph and duration timeline.
  Edges are labelled with the six semantic tokens; Reject remains a Judge
  self-loop annotation. Consecutive identical states merge into one growing
  duration segment, and transition rows are added only for state changes,
  semantic decisions, AVAD start/stop or non-NO_OP events. VASD/VAED panels
  retain their last meaningful result instead of flashing back to NOT_RUN.
- Added MiMo raw generation auditing. Every VASD/VAED response now records the
  exact `message.content`, request kind, normalized semantic command and strict
  validity in both the service log and transition payload. A command is valid
  only when `strip()` equals exactly one allowed label; explanations, Markdown,
  multiple labels and surrounding non-whitespace text are invalid.
- Invalid commands are non-fatal in the debug service: the FSM remains in its
  current state, the WebSocket stays open, and a red timeline row shows the raw
  output plus allowed commands. Added server-side ERROR logging for the same
  evidence. Restarted only the owned UI from svad02 (exit0) to svad03 child
  78190; MiMo child42095 remained running.
- Fresh real WebSocket proof on svad03 showed exact valid outputs in order:
  VASD raw `</b>` -> NO_BREAK, VASD raw `<b>` -> BREAK/PREFILL, and VAED raw
  `<c>` -> COMPLETE/DECODE. Service logs contain the same raw strings and
  `semantic_valid=true` fields.
- Replaced free generated semantic labels with constrained single-token logprob
  classification. Tokenization proof: `<b>`2, `</b>`3, `<c>`2, `</c>`3,
  `REJECT`2 tokens. Internal class codes A/B/C are token IDs32/33/34; requests
  use `allowed_token_ids`, `logprob_token_ids`, `logprobs=true`, max_tokens1.
  External commands remain the normative semantic labels.
- Real logprob probe passed: preserved speech VASD selected `<b>` with97.53%
  normalized probability and4.25 logprob margin; VAED selected `<c>` with
  99.96% and7.875 margin. A short WebSocket probe selected BREAK at94.33%
  margin3.125, then INCOMPLETE at67.92% margin0.75, demonstrating useful
  uncertainty visibility.
- Replaced per-block Silence INFO with `semantic_vad_state_interval`. A probe
  containing four true silent blocks now produces one interval summary before
  the Silence->Judge transition; reset and connection close also flush any
  open interval. Semantic transitions include full label logprobs, probability
  and margin. Final focused/debug suite28/28 passes.
- User started the next acceptance slice: reuse the current visualization,
  add a right-side text conversation panel, trigger MiMo Chat from FSM DECODE,
  cancel active Chat on a new effective BREAK, and expose editable VASD, VAED
  and Chat prompts. TTS remains out of scope; no commit/push before acceptance.
- Added complete accepted-turn audio to DECODE output, an independent streaming
  MiMo Chat provider, bounded four-turn multimodal history, and Chat events:
  started/delta/done/cancelled/error. New effective BREAK cancels an active
  Chat task while semantic classification continues on the same MiMo service.
- Added a right-side conversation panel and a collapsible prompt editor. VASD,
  VAED and Chat defaults are Chinese; prompts are sent during configure and can
  be updated for subsequent requests with `prompts.update`.
- Initial real probe `chat_probe_20261026T152937Z` exposed two defects: MiMo
  transcribed instead of answering, and semantic completion while AVAD remained
  active let the same acoustic tail start a second Break that cancelled Chat.
  Added a Chinese per-audio answer instruction and an acoustic-release gate
  that keeps the public FSM in Silence until AVAD falls inactive.
- Final real probe `chat_probe_20261026T154033Z` passed: one Chat started, zero
  cancellations, and MiMo replied `三加四等于七。`. Current UI is svad07 child
  100896; MiMo child42095 remained running. Focused/debug suite32/32 passes.
- Added detailed Chinese implementation document
  `Doc/stage4-mimo-SVAD/current_vad_implementation_20261026.md`. It covers the
  three timing scales, AVAD framing, cumulative VASD/VAED windows, FSM rules,
  buffers, constrained single-token logprobs, Chinese prompts, Silence interval
  logs, acoustic-release gating, Chat/history/interruption, visualization,
  runtime evidence and known limits. The document explicitly distinguishes
  the running svad07 behavior from the unverified/unloaded conservative VAED
  threshold + margin + confirmation candidate currently in the worktree.
- User corrected the VAED responsibility boundary with a long-utterance pause
  example. New implementation scope: VASD remains chunk/cumulative-prefix
  driven; VAED runs only once on each AVAD speech-stopped edge using the full
  accepted turn. `</c> + </s>` keeps Listen across silence; resumed speech
  continues the same turn; accepted `<c>` triggers DECODE. Repeated silence
  does not rerun VAED. Add a configurable external incomplete-silence timeout
  (default8000ms) as a no-fourth-state fallback.
- Completed v0.2 endpoint migration. Final endpoint audio is appended exactly
  once before commit, while `decode_audio` retains the complete accumulated
  turn. Repeated inactive blocks are neither appended nor reclassified.
- Added explicit tests for incomplete endpoint wait, repeated-silence NO_OP,
  resumed speech in the same Listen turn, later complete endpoint, full-turn
  VAED inputs, exact-once endpoint delivery, 8-second fallback behavior and
  optional multi-endpoint confirmations.
- Full core/debug WebSocket suite passes 35/35 outside the sandbox. Python
  compile, frontend JavaScript parse and `git diff --check` pass. The first
  combined static command found `node` absent from the activated omni PATH;
  reran with `/mnt/geminihzceph/user_whynotzhliu/my_envs/miniconda3/bin/node`.
- Stopped only owned `svad07` supervisor100895; MiMo PID42095 remained live.
  One shell-background launch attempt produced no run artifacts and no live
  process. Restarted successfully as `svad08` supervisor121165/child121166 in
  new run `workspace/logs/20261026T164300Z_mimo_svad_v02/`.
- Live `svad08` health reports `mimo=true` with1.8ms loopback latency. Defaults
  expose all three Chinese prompts; the page contains semantic wait,
  completion-threshold and incomplete-timeout controls. User browser acceptance
  of the Beijing pause/resume example remains open; nothing was committed or pushed.
- Consolidated AVAD, VAED, buffer, timeout and all three Chinese prompts into
  one open-by-default all-in-one settings panel. Added the previously hidden
  `max_buffered_chunks` control. `/defaults` now returns structured config and
  prompts. Applying settings during a live WebSocket cancels active Chat,
  closes the old adapter and rebuilds the complete session policy atomically.
- Added a protocol test for live all-in-one reconfiguration. Core/debug suite
  now passes36/36; Python compile, frontend parse and whitespace checks pass.
- Stopped owned svad08 supervisor121165 and started svad09
  supervisor126288/child126289 in exclusive run
  `workspace/logs/20261026T170300Z_mimo_svad_all_settings/`; MiMo PID42095 was
  not restarted. Live health reports mimo=true at1.9ms. `/defaults` returns the
  complete nine-field config plus all three prompts, and the served page
  contains the all-in-one panel, apply button and max-buffer control.
- Added tracked local default file
  `workspace/experiments/20261025_mimo_tts_integration/svad_config.json` with
  all nine numeric settings and three Chinese prompts. `/defaults` rereads and
  validates it on every request with no-store caching; new WebSocket sessions
  initialize from the same file. Local edits therefore require only a page
  refresh. Invalid JSON returns an explicit HTTP500 error. Added refresh and
  invalid-file tests; full suite now passes38/38.
- Restarted only the UI as svad10 supervisor129153/child129154 in
  `workspace/logs/20261026T171900Z_mimo_svad_local_config/`; MiMo PID42095 was
  preserved. Live no-restart proof changed local threshold0.5->0.55, observed
  `/defaults` immediately return0.55, restored the file, then observed0.5.
- Added a top-level `_说明` object to `svad_config.json` with Chinese
  documentation for all nine numeric settings, all three prompts and the
  refresh/apply lifecycle. It remains valid JSON; the loader intentionally
  consumes only `config` and `prompts`.
- Investigated reported VASD NO_BREAK decline. svad10 logs contain39 BREAK,
  33 NO_BREAK and45 REJECT decisions, including one earlier session with32
  consecutive NO_BREAK results, so the B/`</b>` class path remains functional.
  Current prompt defines A broadly as any meaningful request/question and B
  narrowly as self-talk/companion speech, while VASD receives no assistant-
  speaking, wake-word or reply-content context. BREAK also uses raw argmax:
  observed p=0.543/margin=0.25 and p=0.629/margin=1.0 candidates immediately
  interrupted. Once one prefix wins A the FSM leaves Judge, whereas B must win
  on every accumulated prefix; this explains the recent apparent bias.
- Added VASD gates symmetric with VAED:
  `break_probability_threshold` default0.8, `break_margin_threshold` default1.5
  and `break_confirmations` default1. Raw `<b>` remains visible as BREAK
  candidate; only accepted candidates produce PREFILL/interrupt. `</b>`,
  REJECT and weak `<b>` reset the confirmation count. Added config validation,
  JSON comments, all-in-one UI controls and model-vs-policy telemetry. Tests
  cover weak candidates, consecutive confirmations and NO_BREAK reset; suite
  passes41/41.
- Stopped only svad10 supervisor129153 and started svad11
  supervisor142631/child142632 in
  `workspace/logs/20261027T034500Z_mimo_svad_break_gate/`; MiMo PID42095 was
  preserved. Live health reports mimo=true at1.8ms. `/defaults` exposes
  break probability0.8, margin1.5 and confirmations1; served HTML contains all
  three controls and BREAK CANDIDATE telemetry.
- Added `audio_chunk_ms` to the local JSON and all-in-one UI, default500ms and
  validated range50-5000ms. It is a minimum target browser dispatch interval:
  responses no longer cause sub-target immediate sends; if one semantic request
  is still in flight, queued audio is merged and the actual chunk is longer.
  Applying settings live restarts the browser flush timer. Added defaults,
  reconfigure, invalid-range and frontend gate tests; suite passes42/42.
- Stopped only svad11 supervisor142631 and started svad12
  supervisor146752/child146753 in
  `workspace/logs/20261027T035800Z_mimo_svad_chunk_config/`; MiMo PID42095 was
  preserved. Live health reports mimo=true at1.3ms, `/defaults` returns
  audio_chunk_ms=500, and served HTML includes the chunk control and minimum-
  interval gate.
- User explicitly authorized committing and pushing the current `feature/SVAD`
  snapshot. Publication no longer waits on the still-open Beijing browser
  acceptance; that acceptance remains documented as an open quality gate.
- New v0.3 direction: VASD uses a configurable x-second sliding window and
  becomes binary semantic/no-semantic (`<b>`/`</b>`); VAED remains acoustic-
  endpoint triggered. Inference must retain all SVAD-accepted audio from a
  user turn and deliver that complete context to Chat at DECODE.
- Backend audit found the current MiMo realtime plugin is not capable of the
  requested model-side behavior: it advertises turn-commit-only and raises
  `MiMo inference requires a committed turn` on non-final append. Existing
  append commands only buffer audio. Native resumable Stage0 examples exist in
  other model plugins, so real MiMo KV reuse requires a new backend contract.
- Implemented v0.3 strategy layer in the worktree. VASD is now masked A/B only,
  runs on t0 immediately, and uses a duration-aware `vasd_window_ms` suffix.
  A 500ms/8s test proves `[t0..t15] -> [t1..t16]` while full candidate audio
  still retains all17 chunks. VAED endpoint behavior is unchanged.
- An experimental masked A/B Response decision (`LISTENING`/`GENERATE`),
  thresholds, sidecar server and fourth Prompt were added briefly but were not
  accepted. They were removed on 2026-10-28. The accepted v0.3 contract is
  normal full-context Chat: `DECODE` passes the complete `decode_audio` to
  MiMo Chat, and the Chinese Chat Prompt asks for literal `listening` when
  there is no active interaction intent. Native MiMo request/KV reuse remains
  deferred backend work and is not claimed by the service.
- Completed v0.3 cleanup on 2026-10-28. Removed the uncommitted streaming
  sidecar, its launcher role, classifier tests, fourth Prompt, response
  thresholds, WebSocket `response.decision` events and UI controls. The debug
  service now has a single DECODE path: `output.decode_audio` is passed
  directly and unchanged to `MiMoChatProvider.stream_reply`.
- Strengthened the WebSocket regression: three distinct accepted audio chunks
  must arrive at Chat in exact input order, including the adapter's normalized
  append metadata. This proves the Chat path uses the complete accepted turn,
  not the VASD suffix window or only the final chunk.
- Outside-sandbox validation on 2026-10-28 used `env.sh`, `conda activate
  omni`, and repository-local `vllm-omni`/`vllm-src` import roots:
  `python -B -m unittest test_semantic_vad test_svad_debug -q` passed 43/43.
  JSON parsing, Python compile, frontend JavaScript parsing with the pinned
  Node binary, stale-response-control scan and `git diff --check` also passed.
- First `svad13` launch exposed a launcher assumption: `run_service.py` raised
  `KeyError: CUDA_VISIBLE_DEVICES` after spawning the CPU UI child, so the
  child was stopped. The launcher now records an empty value when the variable
  is absent. A new retained `svad14` run started in
  `workspace/logs/20261028T042103Z_mimo_single_phase2_8d3aafea/` with
  supervisor PID282603 and UI PID282608. MiMo PID42095 on loopback8090 was not
  restarted. After Silero initialized, `/health` returned `mimo=true` at1.8ms;
  `/defaults` exposed only VASD/VAED/Chat prompts and the served page had no
  response-classifier controls.
- Updated the two semantic prompts on 2026-10-28 using the supplied boundary
  policy. VASD now constrains MiMo to `需要 -> <b>` or `不需要 -> </b>`; VAED
  constrains it to `已 -> <c>` or `未 -> </c>`. Direct local `tokenizer.json`
  verification found IDs `需要=85106`、`不需要=104689`、`已=36667`、`未=38342`,
  all one token without a leading space. A live HTTP probe accepted both masks:
  VASD returned `需要`; VAED returned `未`; each response included both
  requested candidate logprobs. The classifier parser now rejects surrounding
  whitespace as well as explanations, preserving exact-label observability.
- Restarted only the CPU UI as `svad15` in
  `workspace/logs/20261028T044418Z_mimo_single_phase2_3b2e9797/` after the
  label change; supervisor PID289405 and UI PID289410. MiMo PID42095 was
  preserved. `/health` returned `mimo=true` at1.7ms, and `/defaults` confirmed
  the three Prompt keys plus exact `需要/不需要` and `已/未` output instructions.
- After aligning invalid-command diagnostics with the Chinese labels, restarted
  only the CPU UI as `svad16` in
  `workspace/logs/20261028T053651Z_mimo_single_phase2_1babea77/`; supervisor
  PID303530 and UI PID303536. MiMo PID42095 remained unchanged. `/health`
  returned `mimo=true` at2.0ms and `/defaults` verified the final prompts.

### Test Results
| Test | Expected | Actual | Status |
|------|----------|--------|--------|
| Branch base | `feature/SVAD` starts at published main | Base SHA 5c0aeb9 | PASS |
| Submodule cleanliness | No inherited edits | Both worktrees clean | PASS |
| Stage 4 focused tests | T01-T13 and adapter boundaries | 23/23 passed | PASS |
| Stage 3 + Stage 4 regression | Existing integration/realtime plus semantic VAD | 41/41 passed in 32.003s | PASS |
| Python compile | Modified Python files compile | Passed | PASS |
| Frontend deterministic state | Existing history/cancel/stale/PCM behavior | Passed | PASS |
| Whitespace | No malformed patch whitespace | `git diff --check` passed | PASS |
| Scoped credential scan | No key/token/private credential patterns | No matches | PASS |
| Standalone debug protocol | Page/worklet, configure, transitions and reset | 2/2 passed outside socket-restricted sandbox | PASS |
| Live UI | Current-IP page and MiMo health | HTTP 200; mimo=true | PASS |
| Real MiMo labels | VASD/VAED parser accepts actual model output | Passed | PASS |
| Real semantic flow | AVAD -> Judge -> Listen -> Decode | Passed on preserved speech fixture | PASS |
| Reject smoke | Low-amplitude noise does not break | reject=True, 67.3ms | PASS |
| Final FSM + debug suite | Pure controller plus standalone WebSocket service | 25/25 passed outside socket-restricted sandbox | PASS |
| Final live assets | UI, health and capture worklet | HTTP 200; health mimo=true, 1.4ms | PASS |
| Service isolation | Only expected acceptance services | 8080 current-IP, 8090 loopback; no 8093 listener | PASS |
| Strict command protocol | Exact labels only; invalid raw output remains visible and session continues | 27/27 tests passed | PASS |
| Real raw-output audit | Actual MiMo text reaches logs and timeline metadata | `</b>`, `<b>`, `<c>` all strict-valid | PASS |
| Single-token logprob probe | Constrained candidate distribution and argmax mapping | VASD/VAED passed on real MiMo | PASS |
| Silence interval persistence | No per-block Silence INFO; exact interval summary | Four-block probe and unit test passed | PASS |
| FSM-driven Chat | DECODE streams a MiMo text reply | Real answer `三加四等于七。` | PASS |
| Chat interruption | New effective BREAK cancels active generation | Focused blocking-stream test passed | PASS |
| Editable Chinese prompts | VASD/VAED/Chat prompts visible and session-updatable | Protocol/UI tests passed | PASS |
| Acoustic tail suppression | Completed utterance tail does not open a second turn | Real probe: one Chat, zero cancellation | PASS |
| v0.2 endpoint VAED suite | Endpoint-only VAED, pause/resume, timeout and Chat protocol | 35/35 passed outside sandbox | PASS |
| v0.2 live service | Updated UI with existing MiMo and no TTS | svad08 health mimo=true, 1.8ms | PASS |
| Beijing long-utterance browser acceptance | `</c>` pause then resumed same turn and later `<c>` | Awaiting user microphone test | OPEN |
| All-in-one settings | AVAD/VAED/buffer/timeout plus three prompts in one panel | 36/36 suite and live reconfigure protocol | PASS |
| Local config refresh | Edit JSON locally, refresh browser, receive new defaults | Per-request reread and invalid-file tests; 38/38 suite | PASS |

### Errors
| Error | Resolution |
|-------|------------|
| Sandbox could not create `.git/refs/heads/feature/` | Verified no existing `feature` ref; approved Git metadata command created `feature/SVAD` |
| Initial plan replacement patch was invalid | Reissued independent in-place updates; no partial changes occurred |
| First semantic VAD unit run passed 13/14; one test expected Judge validation while the FSM was still in Silence | Corrected the test to enter Judge before omitting its required semantic fields; implementation unchanged |
| After realtime adapter wiring, importing semantic_vad pulled the full current vLLM tree and failed on missing local FlashAttention extensions | Made Silero loading lazy and detector-injectable; pure FSM/contract tests no longer import the inference stack |
| Cached whitespace check found two Markdown hard-break trailing spaces in the supplied specification header | Removed only those two trailing spaces; specification semantics are unchanged |
| Feature branch push was interrupted before a result was observed | Confirmed no Git push process remains; keep publication paused pending user acceptance |
| Standalone debug-service tests could not bind aiohttp TestServer sockets inside the sandbox (PermissionError errno 1) | FSM 23/23, compile and page-script syntax passed; rerun only the socket tests with explicit sandbox escalation |
| Initial nohup background shells exited before creating launch artifacts | Verified both were zombies with no port/GPU use; switched to `setsid -f` plus absolute paths, then verified manifests and owned live children |
| User clicked Start microphone but saw no response | Access logs showed successful WebSocket upgrades but no configure messages. Fixed a frontend handshake deadlock: connect waited for configured before configure was sent. Added visible startup phases, a 5-second configuration timeout, secure-context checks and explicit microphone errors |
| Combined static command returned `node: command not found` after activating omni | Located Node at `/mnt/geminihzceph/user_whynotzhliu/my_envs/miniconda3/bin/node`; frontend script parse passed with that explicit path |
| First svad08 background launch produced no process or artifacts | The shell initialization/background grouping lost the intended run variable; retried with explicit run directory `20261026T164300Z_mimo_svad_v02`, then verified supervisor121165 and child121166 |
