# Progress Log

## Session: 2026-11-01

### Current Status
- **Phase:** 7 - Native MiMo tool parser migration
- **Started:** 2026-11-01

### Actions Taken
- Investigated browser session `svad-de71908500f4`: VASD/VAED completed and
  Agent Chat started, but no tool/chat completion event reached the browser.
- Confirmed MiMo had zero running/waiting requests and no error/abort; the stall
  was in application-side native SSE completion handling.
- Updated direct/native streaming completion to return immediately on a
  non-null `finish_reason` instead of requiring a trailing `[DONE]` sentinel.
- Added native round, tool wait/completion, `chat.done`, and TTS completion logs.
- Added a 120-second timeout while waiting for SDK tool output.
- Restarted only the owned 8081 agent backend; MiMo 8090, public 8080 and Next
  3000 remained running.
- Real speech probe using “今天是几号，现在几点？” passed through VASD/VAED,
  native `get_current_datetime`, tool output, final Chat and `chat.done`.
- The same probe through `8080/agent-ws` with TTS enabled completed
  `agent.function_call`, `chat.done`, PCM audio streaming and `tts.done`.
- User web search reached the SDK tool correctly but Next returned HTTP 503
  because `ICHAT_API_KEY` was absent from the new-node process environment.
- Restarted only the owned Next 3000 process with the previously supplied
  limited iChat token injected through hidden terminal input. The token was not
  written to repository files, planning records, or service logs.
- Same-origin `POST /api/tools/web-search` returned HTTP 200 with one real
  result; the probe consumed one credit and reported USD 0.0003 cost.
- Recovered the pinned Stage 6 plan without replacing historical records.
- Preserved local user changes in `Doc/stage6-agentic/agent_prompt.md`,
  `Doc/stage6-agentic/agent_runtime.md`, and `wx_tts_ref.py`.
- Confirmed the new node has eight idle H20 GPUs and no known inherited service
  state has been assumed.
- Confirmed current source registers parser name `mimo` and the checkpoint uses
  the matching native XML tool-call syntax.
- Began replacing Router/envelope compatibility with native vLLM tool calls.
- Removed Tool Router, structured JSON envelope, XML recovery and malformed
  JSON-prefix recovery from `AgenticMiMoChatProvider`.
- Made native tool calls mandatory and preserved direct multimodal completion
  for agents with no tools.
- Added `--enable-auto-tool-choice --tool-call-parser mimo` to the MiMo launcher.
- Started MiMo on GPU 0-3 at `127.0.0.1:8090`; launch manifest and logs are in
  `workspace/logs/20261101T_native_mimo_agent_081500/`.
- Direct live Chat validation returned `get_current_datetime` as a standard
  OpenAI `tool_calls` item and completed a final answer after tool output.
- Streaming live validation returned `delta.tool_calls` followed by
  `finish_reason=tool_calls` and `[DONE]`, matching the provider parser.
- Started agent backend `127.0.0.1:8081`, Next host `127.0.0.1:3000`, and
  same-origin public entry `http://28.29.218.56:8080/agent`.
- Confirmed local page, backend, and public page all return HTTP 200.
- `ICHAT_API_KEY` is not set on the new node; datetime works, while web search
  requires injecting the key into the Next process environment.

### Test Results
| Test | Result |
|------|--------|
| Native provider focused suite (5 tests) | PASS |
| Python compile for provider/server/launcher | PASS |
| Live native multi-tool selection | PASS: selected `get_current_datetime` |
| Live tool-output continuation | PASS |
| Agent WebSocket function-call round trip | PASS |
| Public agent page | PASS: HTTP 200 |
| Native finish-reason boundary regression | PASS in focused 5-test suite |
| Real speech direct to 8081 after stall fix | PASS |
| Real speech through 8080 proxy with TTS | PASS |

### Errors
| Error | Resolution |
|-------|------------|
| Planning resolver script could not execute because its `/bin/sh` interpreter was denied | Used the explicitly pinned plan directory directly and did not fall back to another plan |
| `ss` is unavailable on the new node | Defer port ownership checks to socket binds/process inspection before startup |
| Plain `import vllm` did not complete in the activated environment | Validate and pin an explicit source/runtime PYTHONPATH before service launch |
| First native MiMo launch wrapper had an unmatched shell quote | No process started; retry with a fixed timestamp path and simpler command quoting |
| First WebSocket test selector used the wrong class name | Corrected to `DebugServiceTests` |
| Sandbox denied the aiohttp test's localhost bind | Re-ran the same single test with scoped local-bind permission; passed |

## Session: 2026-10-31

### Current Status
- **Phase:** 6 - Runnable browser agent host
- **Started:** 2026-10-31

### Actions Taken
- Confirmed `main` matched `origin/main`, both existing submodules were clean,
  and the only untracked file was the unrelated `wx_tts_ref.py`.
- Read the Stage 5 plan and Stage 3/5 canonical documentation to recover the
  current duplex MiMo and video contracts.
- Created `feature/stage6-agentic` from synchronized `main`.
- Initialized isolated plan `2026-10-31-stage-6-agentic-duplex-mimo`; previous
  project plans were not overwritten.
- Recorded Stage 6 ownership, preservation and focused-test constraints before
  changing dependencies or integration code.
- Added `third_party/openai-realtime-agents` as a submodule pinned to
  `94c9e9116b581052655cff7b756cc5e02771cda1`; recorded URL and local remote
  point to the user's `Applauzzz` fork.
- Inspected the fork README, package lock, session hook and API routes. It is a
  Next.js demo using `@openai/agents@0.0.5` and currently hard-wires
  `OpenAIRealtimeWebRTC` plus an OpenAI ephemeral session endpoint.
- Traced the duplex MiMo `/ws` lifecycle. That service already owns VAD,
  accepted audio/video, response generation, TTS, playback and interruption.
- Inspected exact locked `@openai/agents-realtime@0.0.5` types and confirmed
  RealtimeSession, not the transport, executes tools and handoffs.
- Added parent-owned AgenticMiMoChatProvider and agent control events behind
  explicit `--agentic` mode.
- Added DuplexMiMoTransport in the fork and made useRealtimeSession accept an
  optional custom transport while preserving default WebRTC behavior.
- Added a minimal serialized duplex MiMo handoff scenario without registering
  it in the frozen demo UI.
- Added canonical Stage 6 architecture and operations documentation.
- Started an isolated 8081 agentic service with the same runtime snapshot as
  healthy 8080; left 8080/8090 untouched.
- First live native-tool artifact recorded HTTP 400 because shared 8090 has no
  configured vLLM tool parser.
- Added structured JSON tool-envelope fallback and reran the real probe.
  MiMo emitted acknowledge_request, accepted the simulated SDK output and
  completed the response. Stopped only the owned 8081 instance afterward.
- Ran a real @openai/agents RealtimeSession through DuplexMiMoTransport.
  MiMo selected the SDK-generated transfer_to_specialist handoff; SDK updated
  currentAgent, instructions/tools and tool history, then the specialist
  completed the same turn.
- Added SDK history mapping for accepted user audio, completed/incomplete
  assistant replies and the retained interruption marker.
- Added and passed an explicit response.cancel WebSocket test.
- Began Phase 6 as an additive browser route; the existing App.tsx flow remains frozen.
- Added /duplex-mimo with direct RealtimeSession + DuplexMiMoTransport lifecycle.
- Added AudioWorklet microphone capture, 500 ms PCM aggregation and transport
  sample-rate synchronization.
- Added optional camera capture; at most one JPEG per second is attached only
  when an audio chunk is sent.
- Added streaming 24 kHz PCM playback queue, playback.state acknowledgement and
  immediate queue cancellation on interruption.
- Added session controls, microphone level, camera preview, conversation
  history and tool/handoff activity views.
- Production build generated /duplex-mimo successfully. Started agent backend
  on 28.29.217.180:8081 and Next.js host on 28.29.217.180:3000.
- User Mac access to port 3000 was blocked by the corporate gateway with HTTP
  502. Added same-origin proxy routes to the allowed 8080 service:
  /agent, /_next/*, /duplex_pcm_capture.js and /agent-ws.
- Rolled only the owned 8080 SVAD service to attempt agent01; the original /
  state-machine page remains available. /agent returned 200 and /agent-ws
  completed agent.session.update plus configure through the proxy.
- User browser exposed `MiMo agent returned no reply text`. 8081 logs showed
  successful VASD_SEM/VAED and a valid structured envelope with kind=final but
  an empty content string; this was not a proxy or MiMo HTTP failure.
- Added schema minLength for final content and one bounded same-turn correction
  retry. A live speech fixture through 8080/agent-ws completed with chat.done.
- User reported many tool errors and missing vision. The default demo graph was
  a bidirectional greeter/haiku handoff, which exposed irrelevant transfer tools
  to general multimodal questions. Replaced it with one general multimodal
  duplex_assistant and no default tools/handoffs.
- No-tool agents now use the ordinary streaming multimodal Chat path rather than
  structured tool envelopes. Tool envelopes remain only when SDK tools/handoffs
  actually exist.
- Added per-turn diagnostics for configured tool names, function call names and
  accepted video frame count. The Agent Activity view now shows
  Vision input: N frames.
- Exact A/B with six labeled RED/GREEN/BLUE JPEG frames passed on both original
  /ws and Agent /agent-ws; each answered red, green and blue in order.
- Added Doc/stage6-agentic/agent_development_guide.md as the current developer
  and operations manual covering architecture, tools, handoffs, media, protocol,
  deployment, focused tests, logging and troubleshooting.
- Validated the provided iChat token and base URL without persisting the token.
  Chat Completions works for gpt-5; Responses web_search returned invalid model
  for both gpt-5 and gpt-4.1, and chat web_search_options did not browse.
- Validated iChat Serper /api/serper/search. Added a server-only
  /api/tools/web-search route, 8080 same-origin proxy and search_web SDK tool.
- Real voice Agent test executed search_web, returned Serper results to MiMo and
  produced a final answer with source URLs. The initial test searched twice;
  default instructions now limit search_web to once per user turn.
- Browser logs exposed a mixed malformed JSON plus repeated XML tool envelope.
  Added bounded recovery of the first allowed XML tool call; unknown tools remain
  rejected. Seven parser/runtime tests plus the listening policy test pass.
- Added get_current_datetime. Date/time questions must use it, must not use
  search_web and always return Asia/Shanghai time. Real voice validation called
  only this tool and answered Beijing time.
- Added recovery for malformed JSON-prefix tool envelopes where the first
  escaped arguments object is complete but trailing think/refusal text corrupts
  the outer envelope. Recovery remains allowlist-bound and rejects incomplete
  or unknown tools. Ten focused runtime/parser tests pass.
- Added Conversation tool cards backed directly by SDK function_call history.
  In-progress calls show a spinner and arguments; the same itemId is replaced
  with formatted full output when completed. Two transport history tests pass.
- Added sticky-bottom Conversation scrolling. New messages, streaming deltas and
  tool lifecycle updates auto-scroll while the user is near the bottom; manual
  upward scrolling pauses follow mode until the user returns to the bottom.
- Created child commit b6dfb9b on feature/stage6-duplex-mimo. GitHub push is
  currently blocked by network reachability: git ls-remote, proxied HTTPS and
  forced-IPv4 direct HTTPS all timed out before TCP connect. Credentials and
  askpass from github_env.sh are present; no authentication failure was reached.

### Test Results
| Test | Expected | Actual | Status |
|------|----------|--------|--------|
| Agent provider loop | Native and envelope tool/handoff behavior | 3 focused tests pass | PASS |
| Existing MiMo Chat payload | Audio/video ordering remains unchanged | 2 focused tests pass | PASS |
| Agent WebSocket control plane | Function call round-trips and Chat completes | Focused E2E passes | PASS |
| Locked SDK TypeScript contract | Custom transport implements 0.0.5 interface | TypeScript compile passes | PASS |
| Frozen page regression | Existing page and worklet remain available | Focused page test passes | PASS |
| Live MiMo agent tool turn | Real model selects tool and resumes after output | PASS, artifact 071408Z | PASS |
| Live SDK RealtimeSession handoff | Router to specialist, completed history and agent_end | PASS, artifact final_only | PASS |
| Retained interruption history | Incomplete assistant contains the same marker | Node transport test passes | PASS |
| Agent response cancellation | response.cancel stops current Chat | Focused WebSocket test passes | PASS |
| Phase 6 TypeScript | New route, media hook and transport APIs type-check | PASS | PASS |
| Phase 6 production build | /duplex-mimo prerenders | PASS, 7.88 kB route | PASS |
| Live page/health | Page 200; MiMo/TTS health true | PASS | PASS |
| Same-origin 8080 agent proxy | /agent 200 and /agent-ws configured | PASS | PASS |
| Empty agent final recovery | Empty final retries once to nonempty chat.done | Unit + live proxy PASS | PASS |
| Agent visual A/B | Six labeled frames through original and Agent paths | Both correct red/green/blue | PASS |
| Default tool policy | General assistant has no irrelevant handoff tools | tools=[] in live log | PASS |
| iChat Serper route | Search results through 8080 same-origin API | PASS, credits=1 | PASS |
| Real voice web-search tool | Tool start/end, search output and final sources | PASS | PASS |
| Mixed XML tool recovery | First allowed call recovered; duplicate/unknown rejected | PASS | PASS |
| Beijing datetime tool | One local call, no search_web, Asia/Shanghai answer | PASS | PASS |
| Malformed JSON-prefix tool recovery | Complete allowed arguments recovered; unsafe cases rejected | PASS | PASS |
| Conversation tool lifecycle | Spinner/arguments replaced by completed output on same itemId | PASS | PASS |
| Conversation auto-scroll | Sticky bottom with manual-scroll pause/resume | TypeScript PASS | PASS |
| Browser microphone/camera/TTS | Real user browser permissions and playback | Awaiting user | OPEN |

### Errors
| Error | Resolution |
|-------|------------|
| GitHub fork `ls-remote` produced no references; a direct retry hung | Stopped the hanging process and seeded the submodule from the clean local clone; remote verification remains open |
| Sandbox denied writing `.git/config` during submodule sync | Completed the scoped Git metadata update with approval |
| npm direct/no-proxy download timed out | Used initialized environment proxy; locked downloads succeeded |
| aiohttp bind denied in sandbox | Re-ran the focused test with scoped localhost permission |
| Test insertion split an existing method | Moved the method and reran both tests |
| First 8081 startup loaded incompatible current vLLM source | Reused healthy 8080 runtime snapshot import roots |
| Native tool requests failed with missing parser HTTP 400 | Added structured tool-envelope fallback; real probe passed |
| First SDK handoff envelope was truncated/repeated braces | Increased envelope budget and encoded arguments as a JSON string |
| Specialist repeated stale handoff after tools were cleared | Constrained empty-tool agent schema to final-only; live SDK handoff completed |
| Running next build alongside next dev removed the dev routes manifest | Restarted only the Next dev server; page returned 200 again |
| Playwright browser install returned success without an executable in two locations | Removed the temporary dependency/script; retained build/static checks and left real browser acceptance open |
| Corporate gateway returned 502 for port 3000 | Proxied the agent UI and WebSocket through the already allowed secure-origin port 8080 |
| MiMo envelope returned final with empty content | Added minLength and one correction retry; live regression ended in chat.done |
| General queries triggered demo handoff tools | Replaced greeter/haiku graph with one general multimodal agent and no default tools |
| Unlabeled synthetic color blocks were misidentified | Used the established labeled frame fixture; original and Agent paths both passed |
| iChat Responses web_search rejected gpt-5 and gpt-4.1 | Used verified Serper search endpoint as a Function Tool |
| 8080 tool POST initially hung until client timeout | Forwarded request body and removed stale content-length in the proxy |
| MiMo mixed malformed JSON with repeated XML tool calls | Recover only the first allowed XML call and preserve SDK validation |
| Date question incorrectly selected web search | Added get_current_datetime and fixed default policy to Beijing time |
| Weather search envelope ended with think/refusal text | Recover first complete allowlisted JSON arguments object and ignore trailing text |
