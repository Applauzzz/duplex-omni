# Findings & Decisions

## Requirements
- Integrate VAD-gated audio/video MiMo plus streaming TTS as one duplex MiMo
  inference backend for an agent framework.
- Use the user's fork: `https://github.com/Applauzzz/openai-realtime-agents`.
- Add the framework under this project as a third-party dependency.
- Freeze the existing browser frontend during Stage 6.
- Preserve current VAD semantic admission: video accompanies admitted audio and
  has no independent state machine.
- Preserve current TTS interruption, model cancellation and optional retained
  interrupted context behavior unless the agent contract requires an explicit mapping.
- Use focused tests; a single-module change must not fan out beyond five test
  entry points, and live end-to-end verification has priority.

## Research Findings
- Browser session `svad-de71908500f4` reached VASD_SEM, VAED and
  `agent_chat_started`, while vLLM completed its GPU requests with HTTP 200 and
  no engine error. The backend emitted neither a tool event nor `chat.done`.
- Native streaming completion previously waited for the trailing SSE `[DONE]`
  even after receiving a definitive `finish_reason`. The affected multimodal
  request stopped making application progress at that boundary despite the
  vLLM engine already being idle.
- Treating a non-null `finish_reason` as the authoritative stream completion
  boundary fixes the stall while retaining `[DONE]` compatibility. Native tool
  output is already fully present before the `finish_reason=tool_calls` chunk.
- A 120-second SDK tool-output timeout now prevents an unavailable browser tool
  implementation from leaving a Chat turn pending indefinitely.
- On the new compute node, all eight NVIDIA H20 GPUs were effectively idle at
  inspection time (521 MiB used of 97871 MiB each). The likely externally
  reachable address is `28.29.218.56`; final bind/reachability still needs a
  live service check.
- Current `vllm-src` registers both `mimo` and `qwen3_xml` to
  `Qwen3EngineToolParser`. Use the model-specific public name `mimo` as directed.
- The checkpoint chat template emits native XML tool calls in the form
  `<tool_call><function=name><parameter=key>value</parameter></function></tool_call>`.
- The activated `omni` environment does not complete a plain `import vllm`
  promptly on this node. Service startup must pin an explicit validated runtime
  import root rather than assuming the environment installation is usable.
- Stage 5 video support is merged into synchronized `main`; the product payload
  is vLLM's JPEG frame sequence rather than short MP4.
- Existing third-party engine dependencies are Git submodules, so a pinned
  submodule under `third_party/` matches repository practice.
- The current duplex MiMo browser/service contract is custom WebSocket `/ws`,
  not yet an OpenAI Realtime API endpoint.
- The only unrelated working-tree item is untracked
  `workspace/experiments/20261025_mimo_tts_integration/wx_tts_ref.py`; do not touch it.
- A clean local clone was available as an offline object seed at
  `/mnt/geminihzceph/user_whynotzhliu/Omni/openai-realtime-agents`. It was at
  upstream commit `94c9e9116b581052655cff7b756cc5e02771cda1`; its configured
  remote was OpenAI upstream rather than the requested fork.
- The requested fork is now represented by a gitlink at
  `third_party/openai-realtime-agents`; `.gitmodules` and the local submodule
  remote point to `https://github.com/Applauzzz/openai-realtime-agents.git`.
  Remote reachability/commit presence still needs verification because GitHub
  reference lookup timed out without output.
- The third-party repository is a Next.js 15 TypeScript demonstration app, not
  a standalone backend agent runtime. Agent lifecycle, tools, handoffs and
  history come from pinned npm package `@openai/agents@0.0.5`.
- Its current `useRealtimeSession` constructs `RealtimeSession` with
  `OpenAIRealtimeWebRTC`, obtains an ephemeral OpenAI session key, and assumes
  browser WebRTC audio plus OpenAI Realtime wire events.
- `RealtimeSession` accepts an explicit `transport` object. This is the
  intended seam, but the exact `@openai/agents-realtime@0.0.5` custom transport
  interface and required server-event sequence must be read before implementation.
- The duplex MiMo `/ws` endpoint already owns configure/reset, VAD admission,
  audio-attached JPEG frames, MiMo response streaming, TTS PCM streaming,
  playback state, semantic interruption and retained partial context.
- Therefore SDK/OpenAI Realtime must not remain a second voice model in the
  target path. Stage 6 should preserve duplex MiMo as the sole inference/audio
  backend and map its accepted turns/responses into the agent runtime contract.
- Exact SDK 0.0.5 inspection confirmed RealtimeSession owns function tool
  execution and handoffs. A custom transport emits function calls, history,
  turn and audio events; SDK returns results through sendFunctionCallOutput and
  updates instructions/tools after handoff.
- DuplexMiMoTransport now maps SDK session/tool/cancel calls to the duplex /ws
  control plane and maps Chat/TTS events back to SDK transport events.
- AgenticMiMoChatProvider does not execute business tools. It pauses MiMo at a
  tool call, emits the call to the SDK, receives the SDK result, and continues
  the same MiMo turn with an OpenAI tool message.
- Existing frontend source is unchanged. useRealtimeSession only gains an
  optional transport parameter; its default remains OpenAIRealtimeWebRTC.
- Current MiMo 8090 rejects both auto and named native tool choices because it
  was not started with a vLLM tool-call parser. Structured JSON schema output is
  accepted and produced the required tool envelope.
- Default agent mode therefore uses structured tool envelopes while preserving
  the SDK-facing function_call contract. Native stream parsing remains available
  for a future MiMo service launched with a validated parser.
- Live artifact `live_agent_probe_20261031T071408Z_9556c730` proved real
  VASD_SEM/VAED, MiMo tool selection, SDK-style output return and final Chat.
- Real SDK artifact `sdk_handoff_probe_final_only` proves RealtimeSession
  executed transfer_to_specialist, changed currentAgent to specialist, retained
  the completed handoff item and received the final assistant item/agent_end.
- Guided JSON was unstable when arguments used an arbitrary object schema.
  Encoding arguments as a JSON string and validating it server-side produced a
  stable SDK-compatible function call.
- After handoff, an agent with no tools must receive a final-only schema;
  otherwise MiMo may repeat a stale handoff name despite the updated tool list.
- Transport history now adds an accepted user audio item at chat.started and
  marks cancelled partial assistant output incomplete; retained partials append
  the same one-token interruption marker used by duplex MiMo history.
- The runnable host is an additive /duplex-mimo route. It does not modify the
  existing App.tsx workflow or register the new scenario in the old selector.
- Browser microphone input uses an AudioWorklet and reports its actual
  AudioContext sample rate to the transport. The service receives PCM16 chunks
  every approximately 500 ms.
- Camera frames have no independent timer/protocol. A current JPEG can accompany
  an outgoing audio flush no more than once per second.
- TTS audio remains service-owned 24 kHz PCM. The browser schedules AudioBuffers
  on one output timeline and sends playback active/inactive acknowledgements.
- Direct IP HTTP may require the user's existing Chrome insecure-origin policy
  for getUserMedia. The page reports an explicit secure-origin error if
  navigator.mediaDevices is unavailable.
- Corporate access allows port 8080 but returned an IT gateway 502 for port
  3000. The production-facing browser path is therefore same-origin
  http://28.29.217.180:8080/agent; 3000 and 8081 are internal proxy targets.
- The existing state-machine page remains at / and its WebSocket remains /ws.
  Agent assets use /_next and /duplex_pcm_capture.js; agent traffic uses
  /agent-ws, so the two browser experiences do not share conversation protocol.
- Guided JSON can still return a syntactically valid final envelope with empty
  content. The provider now retries exactly once in the same user turn with a
  nonempty-answer correction message; a second empty result remains an error.
- The initial greeter/haiku graph was only an SDK handoff demonstration and is
  unsuitable as the product default. The browser host now starts one general
  multimodal agent with an empty tool list.
- When the active agent has no tools, MiMo uses normal streaming multimodal
  completion. Structured envelopes are reserved for turns with real SDK tools.
- Live logs now expose agent_chat_started video_frames and tools. Six labeled
  frames reached both original and Agent Chat and produced the same correct
  red/green/blue answer.

## Technical Decisions
| Decision | Rationale |
|----------|-----------|
| Inspect framework extension points before choosing a facade | A native provider/transport adapter is preferable if the fork exposes one |
| Parent repo owns adapter and application policy | Third-party framework should stay close to its fork and remain replaceable |
| Do not restart existing MiMo/TTS services for source discovery | Avoid disrupting a healthy shared runtime without a validation need |
| Let RealtimeSession remain orchestration owner | Preserve SDK tool execution, handoff lifecycle, context and agent events |
| Add explicit agentic service mode | Keep current service behavior unchanged until isolated live validation passes |
| Use structured envelope as current deployment fallback | It preserves shared 8090 and passes real model validation without parser configuration |
| Treat the SDK transport as the primary integration seam | The demo already injects a transport into `RealtimeSession`; replacing WebRTC is smaller than emulating browser UI state |
| Keep VAD, multimodal admission and TTS in duplex MiMo | Duplicating those responsibilities in the Realtime SDK would create conflicting turn and interruption ownership |

## Issues Encountered
| Issue | Resolution |
|-------|------------|
| GitHub fork reference lookup returned no data and one direct attempt hung | Stopped the lookup, used the existing clean local clone as an offline submodule seed, and retained remote verification as an acceptance gate |
| Initial `git submodule sync` could not write sandboxed `.git/config` | Re-ran the Git metadata operation with scoped approval; working-tree files were unaffected |
| Direct npm access timed out | Retried through the initialized environment proxy; exact locked tarball and dependencies downloaded |
| Initial WebSocket test bind was denied | Re-ran only the focused test with localhost-bind approval |
| New test method split an existing page test | Moved it after the original method; both focused tests passed |
| First 8081 launch used incompatible current vLLM source | Switched to the immutable runtime snapshot used by healthy 8080 |
| Native tool call failed on live 8090 | Added JSON-schema envelope fallback; second live probe passed |

## Resources
- `workspace/experiments/20261025_mimo_tts_integration/semantic_vad.py`
- `workspace/experiments/20261025_mimo_tts_integration/svad_debug_server.py`
- `workspace/experiments/20261025_mimo_tts_integration/streaming_tts.py`
- `Doc/stage3-mimo-single-omni/README.md`
- `Doc/stage5-mimo-video/README.md`
