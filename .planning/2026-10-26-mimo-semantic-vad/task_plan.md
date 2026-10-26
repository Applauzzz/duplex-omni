# Task Plan: MiMo Semantic VAD

## Goal
Implement the Stage 4 three-state duplex input controller on `feature/SVAD`,
using acoustic VAD plus Omni-backed VASD/VAED interfaces to emit ordered
PREFILL, CHUNK_PREFILL and DECODE events without changing the specified FSM.

## Next Step
Create and publish the first `feature/SVAD` checkpoint, then run isolated real
MiMo VASD/VAED audio classification for latency and decision-quality evidence.

## Current Phase
Phase 1: Requirements and architecture discovery.

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
- [ ] Run isolated real MiMo VASD/VAED classification and latency validation
- [ ] Document actual commands, artifacts, skips and remaining model-quality gaps
- [ ] Review branch diff and publish `feature/SVAD`
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

## Errors Encountered
| Error | Resolution |
|-------|------------|
| Initial `git switch -c feature/SVAD` could not create `.git/refs/heads/feature/` in the sandbox | Verified no conflicting ref, then created the requested branch with approved Git metadata access |
| Initial multi-file replacement patch was invalid | Retried as independent in-place updates; no file had changed |
