# Task Plan: MiMo VAD-Gated Video Input

## Goal
Add browser video input to the MiMo voice conversation path without a separate
video state machine: video accompanies audio chunks, follows the existing
VASD_SEM admission decision, and reaches MiMo only as part of an accepted turn.

## Next Step
Run user browser camera acceptance on `video02`, then measure real-camera turn
latency, frame downsampling and history quality. Keep the FSM unchanged; treat
native model-side incremental audio+video prefill as a future runner capability.

## Current Phase
Phase 4: browser camera acceptance and real-scene quality

## Phases

### Phase 1: Requirements And Current Multimodal Contract
- [x] Confirm branch and isolated plan ownership
- [x] Record user policy: video follows VAD admission, no video state machine
- [x] Verify MiMo checkpoint/processor supports video through current Chat API
- [x] Trace current browser capture, WebSocket, FSM buffering and Chat payload
- **Status:** complete

### Phase 2: Audio-Attached Video Contract
- [x] Define bounded audio+video append payload and validation
- [x] Define exact candidate/turn retention and discard behavior
- [x] Define MiMo message ordering for accepted audio and video
- [x] Record initial size, sampling and privacy limits
- **Status:** complete

### Phase 3: Browser And Service Integration
- [x] Add camera capture and bounded video/frame sampling
- [x] Carry video with audio append events through the existing FSM
- [x] Submit accepted video and complete audio to MiMo Chat
- [x] Preserve audio-only operation and interruption behavior
- **Status:** complete

### Phase 4: Focused Verification
- [x] Test noise rejection discards associated video
- [x] Test semantic admission delivers exact accepted video once
- [x] Test invalid media, runner protocol isolation and bounded encoding
- [x] Run a real MiMo audio+video turn through the 8080 WebSocket service
- [ ] Complete browser camera permission/preview acceptance with the user
- **Status:** in_progress

### Phase 5: Documentation And Publication
- [x] Document protocol, ownership, limits and evidence
- [ ] Review Git scope and publish after user authorization
- **Status:** in_progress

## Decisions Made
| Decision | Rationale |
|----------|-----------|
| Create `feature/video-input` from merged main | Video is an independent feature after the SVAD branch was completed |
| Use isolated plan `2026-10-30-mimo-vad-gated-video-input` | Preserve completed Stage 3/4 task history and avoid ambiguous recovery |
| No independent video state machine | User requires video to follow the existing VAD-admitted audio turn |
| Bind video lifecycle to audio chunks | Candidate rejection/reset naturally discards video; accepted Listen/DECODE naturally retains it |
| Preserve audio-only clients | Video is optional input context, not a prerequisite for voice interaction |
| Browser payload is `video_frame: {data, format: "jpeg"}` | Every frame is independently decodable and naturally travels with one audio append |
| Initial frame limits: JPEG, 512 KiB, max 32 accepted frames | Bounds WebSocket memory and model vision tokens |
| MiMo order is video, then audio, then instruction | Lets the model bind visible context to the complete spoken turn |
| Keep video out of realtime runner commands | Existing runner append schema remains audio-only; accepted video is consumed by MiMo Chat at DECODE |

## Errors Encountered
| Error | Resolution |
|-------|------------|
| Frontend long-line patch context failed twice | No partial edit applied; inserted camera controls dynamically using the page's established pattern |
| First full WebSocket probe delivered zero frames | `svad_debug_server` rebuilt the append without `video_frame`; forwarded the optional companion field and added an end-to-end regression test |
| Ad-hoc encoder probe used an invalid numeric dotted import | Kept focused media contract tests as the source of truth; no implementation change |
| Short MP4 produced zero decoded frames for some browser turns | Use vLLM's tested `video/jpeg` base64 frame-sequence format and avoid container decoding |
