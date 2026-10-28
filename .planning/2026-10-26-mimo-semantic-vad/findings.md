# Findings & Decisions

## Requirements
- Implement only `Silence`, `Judge` and `Listen` states.
- AVAD supplies `speech`; Omni VASD supplies `break` plus internal `reject`;
  Omni VAED supplies `complete`.
- Keep exactly six semantic tokens: `<s>`, `</s>`, `<b>`, `</b>`, `<c>`, `</c>`.
- Reject forces effective break false and never interrupts or submits PREFILL.
- Judge gives effective Break priority over `speech`.
- Listen immediately emits DECODE on `complete=1` or `speech=0`.
- Buffer candidate audio from Silence to Judge; initial PREFILL is exact-once;
  subsequent Listen chunks are CHUNK_PREFILL and must not duplicate prior audio.
- FSM emits scheduler events but does not implement GPU scheduling, KV cache,
  speak head, model decode or playback.
- Cover functional tests T01-T13 and structured transition logs.

## Research Findings
- Published Stage 3 baseline is commit 5c0aeb9 on main; worktree was clean
  except for the user-provided untracked Stage 4 specification directory.
- Parent realtime integration lives under
  `workspace/experiments/20261025_mimo_tts_integration/`.
- `realtime_server.py` loads the existing `SileroVADBackendProvider` and uses
  current server-VAD defaults; `realtime_backend.py` adapts external MiMo/TTS
  services to the existing `DuplexStagePort` runner contract.
- Actual runner/VAD/session implementation is owned by the pinned vllm-omni
  submodule and must be traced before selecting the integration module.
- Both submodules were clean and their gitlinks unchanged at branch creation.
- Existing `server_vad` feeds each append through Silero, marks
  `speech_started` for overlap policy, and auto-commits on speech stop.
- The current MiMo plugin refuses non-final runtime appends. Its apparent input
  append support is a buffered whole-turn contract; it does not provide native
  incremental audio KV Prefill/Chunk Prefill.
- The parent realtime WebSocket boundary can recognize `semantic_vad`, keep
  those candidate chunks away from the runner until Break, and translate FSM
  events into existing barge-in, append and commit commands.
- Silero activation may occur after speech has already entered earlier chunks.
  The adapter therefore keeps a bounded Silence-state prefix ring and moves it
  into the first Judge candidate without reusing a prior turn's decode tail.
- Runtime `session.update` remains supported for instructions and other normal
  fields; only changing turn detection after semantic mode opens is rejected.

## Technical Decisions
| Decision | Rationale |
|----------|-----------|
| Pure state controller owns only transition-local candidate buffers | Matches the spec and keeps model/scheduler concerns injectable |
| VASD and VAED remain separate interfaces even if they share one Omni client | Required semantic contract and easier state-specific validation |
| NO_BREAK and REJECT share transition behavior but remain distinct telemetry | Required for false-interruption analysis |
| Implement in the parent service, not the vllm-omni submodule | This is application policy and a model HTTP adapter; current engine contracts remain a stable scheduler dependency |
| Require explicit `semantic_vad` session mode | Legacy `server_vad` and manual commit behavior remain unchanged |
| Treat runner append as an aggregation adapter | It delivers exact audio/event boundaries but only invokes MiMo after final commit |
| Keep MiMo classification sequential per connection for the first checkpoint | Preserves decision order; measured GPU latency is required before introducing speculative/concurrent policy |
| Use constrained internal single-token codes for logprob classification | Normative `<b>/</b>/<c>/</c>/REJECT` labels tokenize to 2-3 tokens. A/B/C are existing single tokens (IDs32/33/34); `allowed_token_ids` and `logprob_token_ids` provide an exact one-position distribution without checkpoint/tokenizer mutation |
| Preserve normative tokens at the FSM boundary | Internal A/B/C are transport codes only; logs/UI map their logprobs back to `<b>`, `</b>`, `REJECT`, `<c>`, `</c>` |
| Persist Silence as intervals | Per-chunk Silence INFO created 20ms log floods; one interval summary preserves duration/chunk evidence with much lower volume |
| Run VAED only on AVAD speech-stop edges | Active-prefix VAED can mark a grammatically complete prefix as finished before the user has stopped speaking |
| Preserve Listen across `</c>` pauses | A semantic-incomplete acoustic endpoint is a continuation point, not a new Judge turn |
| Count optional confirmations across endpoints | Clearing confirmation count on resumed speech makes `complete_confirmations > 1` impossible in endpoint mode |
| Reconfigure settings by rebuilding the session adapter | AVAD and FSM configuration is constructor-owned; rebuilding avoids partial hot-update state while keeping one browser/WebSocket session |
| Read local JSON defaults per request | Allows server-local parameter and prompt edits to appear after browser refresh without restarting model or UI services |
| VASD BREAK is currently unthresholded and asymmetric | Any argmax `<b>` immediately leaves Judge, including observed probability0.543/margin0.25, while `</b>` must keep winning every cumulative-prefix request; recent missing NO_BREAK is prompt/policy bias, not a broken B token path |
| Gate BREAK symmetrically with COMPLETE | Preserve model `<b>` telemetry but require configurable probability, margin and consecutive-prefix confirmations before FSM receives effective break=1 |
| Define browser chunk size as a minimum target interval | A single in-flight semantic request can delay dispatch, so exact fixed-duration chunks are impossible without concurrent requests or dropping audio; expose `audio_chunk_ms` and merge delayed audio |
| Current MiMo realtime plugin is commit-only | `MiMoTTSPlugin.plan_append()` raises on `final=False`, advertises `supports_turn_commit_only=True`, and does not expose a resumable audio append request |
| Native duplex resumable requests exist for other models | MiniCPM-o, Nemotron VoiceChat and PersonaPlex use `supports_core_resumable_request=True`; MiMo needs an equivalent model/plugin contract rather than parent-side buffering |
| Raw MiMo engine append probe succeeded but is not productized | Same-request audio append can work at a low-level engine surface, but switching its one-token classification flow into generation hit a scheduler token-budget issue; user deferred this backend work |
| Complete-context Chat is the current inference contract | `FSMOutput.decode_audio` contains every SVAD-accepted chunk in one user turn; `svad_debug_server.py` passes it unchanged to `MiMoChatProvider.stream_reply` |
| No response-side classifier in v0.3 | The experimental A/B LISTENING/GENERATE path, thresholds, sidecar service and UI controls were removed; no-intent handling is now the Chinese Chat Prompt's literal `listening` response |
| SVAD launchers must tolerate an unset `CUDA_VISIBLE_DEVICES` | The CPU-only UI inherited no such variable; the launch-manifest formatter now records an empty value rather than crashing after spawning the child |
| Chinese constrained labels are valid single tokens | Direct `tokenizer.json` encoding gave `已=36667`、`未=38342`、`需要=85106`、`不需要=104689`; leading-space variants are multi-token and must not be emitted |
| Live MiMo accepts the Chinese masks | On 2026-10-28, VASD `[85106,104689]` returned `需要` with both candidate logprobs; VAED `[36667,38342]` returned `未` with both candidate logprobs |

## Issues Encountered
| Issue | Resolution |
|-------|------------|
| Sandbox blocked creation of a slash-named Git ref | Used approved external Git metadata access after verifying no ref conflict |
| First plan replacement patch targeted each file twice | Retried as valid in-place patches; templates were unchanged by the failure |

## Resources
- `Doc/stage4-mimo-SVAD/duplex_input_fsm_function_spec.md`
- `Doc/stage3-mimo-single-omni/README.md`
- Stage 3 realtime integration and tests under `workspace/experiments/20261025_mimo_tts_integration/`
