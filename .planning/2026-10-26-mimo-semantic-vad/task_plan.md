# Task Plan: MiMo Semantic VAD

## Goal
Implement the Stage 4 three-state duplex input controller on `feature/SVAD`,
using acoustic VAD plus Omni-backed VASD/VAED interfaces to emit ordered
PREFILL, CHUNK_PREFILL and DECODE events without changing the specified FSM.

## Next Step
Run user browser acceptance against `svad12` with the Beijing pause/resume
example. Confirm the first endpoint returns `</c>` and remains Listen, resumed
speech stays in the same turn, and a later accepted `<c>` triggers one DECODE.
Do not commit or push until the user accepts the behavior.

## Current Phase
Phase 5: Live FSM + AVAD + semantic VAD browser acceptance.

## Phases

### Phase 1: Requirements And Existing-Path Discovery
- [x] Confirm Stage 3 MiMo input/text-output baseline and stopped runtime
- [x] Read the complete Stage 4 FSM functional specification
- [x] Create and switch to `feature/SVAD` from published `main`
- [x] Trace current Silero, runner, MiMo adapter and scheduler contracts
- [x] Record implementation ownership and compatibility constraints
- **Status:** complete

### Phase 2: Independent FSM And Contracts
- [x] Implement exactly Silence/Judge/Listen and four control events
- [x] Implement candidate audio buffering and no-duplicate delivery
- [x] Define AVAD, Omni VASD, Omni VAED and speak-decision boundaries
- [x] Add structured transition observability and token mappings
- **Status:** complete

### Phase 3: Omni Semantic Adapter And Realtime Integration
- [x] Connect VASD/VAED interfaces to the existing Omni/MiMo service boundary
- [x] Integrate the controller with the existing realtime input path
- [x] Preserve current manual/server-VAD behavior behind explicit configuration
- [x] Keep scheduler, decode kernel, KV cache and playback outside the FSM
- **Status:** complete

### Phase 4: Focused Verification
- [x] Cover specification tests T01-T13
- [x] Test Reject versus NO_BREAK observability and Break priority
- [x] Test cache clearing, exact-once PREFILL and incremental CHUNK_PREFILL
- [x] Run existing realtime/MiMo regression tests
- **Status:** complete

### Phase 5: Integration Acceptance And Publication
- [x] Add live FSM/AVAD/semantic decision visualization and transition timeline
- [x] Launch only MiMo plus the isolated SVAD debug service; keep TTS stopped
- [ ] Complete browser microphone and decision-quality acceptance with the user
- [x] Document actual commands, artifacts, skips and remaining model-quality gaps
- [x] Publish `feature/SVAD` after explicit user authorization of the current feature snapshot
- **Status:** in_progress

### Phase 6: FSM-Driven MiMo Text Conversation
- [x] Expose complete accepted-turn audio on DECODE without changing FSM rules
- [x] Stream MiMo text replies with bounded multimodal conversation history
- [x] Cancel an active Chat request on a new effective BREAK
- [x] Add a right-side conversation panel to the existing visualization
- [x] Expose editable VASD, VAED and Chat prompts per WebSocket session
- [x] Verify semantic classification remains independent from Chat generation
- **Status:** in_progress

## Decisions Made
| Decision | Rationale |
|----------|-----------|
| Use a new named plan | Stage 4 is a separate task and must not overwrite Stage 3 history |
| Work on `feature/SVAD` | Explicit user requirement; branch starts at published main SHA 5c0aeb9 |
| Treat the specification transition table as authoritative | User requires no extra states, debounce or decision rules |
| Separate deterministic FSM from model adapters | Enables complete state/cache tests without GPU or prompt coupling |
| Preserve current realtime path behind configuration | Stage 3 is the regression baseline while semantic VAD is introduced |
| Keep Stage 4 implementation parent-owned | Policy, HTTP adapters, deployment and tests belong in the parent; the stable runner is consumed as a downstream scheduler |
| Map semantic PREFILL/CHUNK_PREFILL onto buffered runner append | Current MiMo port supports committed whole turns, not native incremental KV; preserve event semantics without overstating engine capability |
| Isolate the acceptance service from TTS and response generation | This stage must localize failures to AVAD, semantic classification or FSM transitions |
| Visualize every state transition and decision latency | User requested browser-visible acceptance and debugging before publication |
| Trigger Chat only from DECODE | Keeps inference downstream of the authoritative FSM rather than duplicating endpointing policy |
| Cancel Chat on effective BREAK | Matches duplex interruption semantics while preserving the existing semantic gate |
| Keep prompts session-local and editable | Enables prompt experiments without mutating model files or global service state |
| Trigger VAED only on acoustic endpoint | Prevents grammatically complete speech prefixes from being decoded while the user is still speaking |
| Allow Listen to span semantic-incomplete silence | Supports `[</c>, </s>]` followed by resumed speech in the same user turn |
| Use an external incomplete-silence timeout | Prevents an incomplete semantic turn from waiting forever without adding a fourth FSM state |
| Publish the current snapshot with browser long-utterance acceptance still open | User explicitly requested commit and push; preserve the open acceptance item rather than claiming it passed |

## Errors Encountered
| Error | Resolution |
|-------|------------|
| Initial `git switch -c feature/SVAD` could not create `.git/refs/heads/feature/` in the sandbox | Verified no conflicting ref, then created the requested branch with approved Git metadata access |
| Initial multi-file replacement patch was invalid | Retried as independent in-place updates; no file had changed |
