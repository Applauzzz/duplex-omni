# Task Plan: Stage 6 Agentic Duplex MiMo

## Goal
Integrate the existing VAD-gated audio/video MiMo plus streaming TTS service
("duplex MiMo") with the user's `openai-realtime-agents` fork while keeping the
current browser frontend frozen and preserving the existing inference services.

## Next Step
Push child commit b6dfb9b and the parent feature branch when GitHub HTTPS
reachability is restored. Keep the current server services running.

## Current Phase
Phase 6: runnable browser agent host

## Phases

### Phase 1: Framework And Existing Service Discovery
- [x] Create dedicated feature branch and isolated plan
- [x] Add `openai-realtime-agents` under `third_party/` at a pinned revision
- [x] Trace framework session, transport, audio, history, tool and handoff contracts
- [x] Trace the current duplex MiMo WebSocket/backend boundary relevant to agents
- **Status:** complete

### Phase 2: Adapter Architecture
- [x] Choose direct provider/transport adapter or Realtime-compatible facade
- [x] Define event mapping, cancellation, playback acknowledgement and turn ownership
- [x] Define tool-call and handoff integration without moving model policy into the fork
- [x] Record implementation and acceptance decisions in Stage 6 documentation
- **Status:** complete

### Phase 3: Parent-Owned Integration
- [x] Implement the smallest parent-repository adapter and configuration surface
- [x] Keep third-party modifications minimal and independently reviewable
- [x] Preserve audio/video VAD admission, TTS interruption and retained context behavior
- [x] Leave the existing frontend unchanged
- **Status:** complete

### Phase 4: Focused Verification
- [x] Run focused protocol/session tests (at most five entry points per module change)
- [x] Prefer an end-to-end agent turn through the live duplex MiMo service
- [x] Verify cancellation, tool execution and resumed conversation behavior
- [x] Record exact environment, commands, artifacts and remaining gaps
- **Status:** complete

### Phase 5: Documentation And Delivery
- [x] Add canonical Stage 6 architecture and operations documentation
- [x] Review Git/submodule scope and preservation constraints
- [x] Commit child repository after user direction
- [ ] Push child and parent branches when GitHub is reachable
- **Status:** in_progress

### Phase 6: Runnable Browser Agent Host
- [x] Add an independent route without modifying the frozen legacy App workflow
- [x] Capture mono PCM16 microphone chunks and send them through DuplexMiMoTransport
- [x] Attach optional sampled JPEG frames to outgoing audio chunks
- [x] Play streaming TTS PCM with interruption-safe scheduling
- [x] Surface connection, current agent, transcript and tool/handoff state
- [ ] Run focused TypeScript/media tests and browser acceptance
- [x] Start an isolated backend and Next.js host for user validation
- **Status:** in_progress

## Decisions Made
| Decision | Rationale |
|----------|-----------|
| Branch from synchronized `main` as `feature/stage6-agentic` | Isolate the new agent integration from completed VAD/video work |
| Use isolated plan `2026-10-31-stage-6-agentic-duplex-mimo` | Preserve prior plans and make Stage 6 recovery unambiguous |
| Add the fork at `third_party/openai-realtime-agents` as a Git submodule | Pin upstream code while keeping third-party ownership explicit |
| Keep duplex MiMo service and adapter policy in the parent repository | Avoid coupling application policy to the vendored framework |
| Freeze the existing frontend | The current stage is backend/framework integration only |
| Preserve running inference services during discovery | Framework inspection does not require a model restart |
| Limit focused tests and prioritize end-to-end coverage | Follow the user's test-budget requirement while validating the real contract |
| Keep RealtimeSession as tool/handoff owner | Preserve SDK lifecycle and context instead of duplicating orchestration in Python |
| Add explicit `--agentic` service mode | Keep the existing non-agent deployment unchanged and allow isolated validation |
| Default to structured tool envelope on current 8090 | Shared vLLM lacks a configured tool parser; JSON schema works without restarting it |
| Encode envelope arguments as a JSON string | Avoid guided-decoding instability for arbitrary object values and match SDK function-call arguments |
| Constrain no-tool agents to final-only schema | Prevent a post-handoff agent from repeating a stale tool call |
| Add a separate /duplex-mimo route | Keep the previous frontend frozen while delivering a usable agent host |
| Bind video capture to outgoing audio flushes | Preserve the existing VAD-bound video lifecycle with no video state machine |
| Use AudioWorklet PCM and scheduled AudioBuffer playback | Match the duplex service PCM contract without reintroducing WebRTC/OpenAI audio |

## Errors Encountered
| Error | Resolution |
|-------|------------|
| First isolated 8081 startup imported current `vllm-src` and failed CUDA flash-attn loading | Reused the exact runtime snapshot plus vllm-omni import roots from healthy 8080 |
| Native and named OpenAI tool requests returned HTTP 400 | Confirmed 8090 lacks tool parser; added structured JSON tool-envelope fallback and retained native mode |
| GitHub HTTPS timed out before connect during push | Preserve local commits; retry push only after network path is restored |
