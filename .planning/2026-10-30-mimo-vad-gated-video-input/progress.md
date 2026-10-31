# Progress Log

## Session: 2026-10-30

### Current Status
- **Phase:** 4 - Browser camera acceptance and real-scene quality
- **Started:** 2026-10-30

### Actions Taken
- Verified merged `main` at `3f3e4ca` and clean submodules; preserved unrelated
  untracked `wx_tts_ref.py`.
- Created branch `feature/video-input`.
- Initialized isolated plan `2026-10-30-mimo-vad-gated-video-input`; no prior
  project plan was overwritten.
- Traced current audio-only browser/WebSocket/FSM/Chat path and generic vLLM
  `video_url` support.
- Recorded the governing design: optional video is attached to audio chunks and
  inherits VAD candidate retention, semantic admission, reset and DECODE.
- Verified checkpoint and current vLLM source support native video: chat
  `video_url`, MiMo Omni vision tower, video tokens/timestamps and registered
  audio/image/video processing. `omni` has OpenCV and PyAV; no install needed.
- Selected browser JPEG frame per audio submit, stored in the same audio-chunk
  mapping. The initial short-MP4 product transport was later replaced by
  vLLM's tested `video/jpeg` frame sequence after a real zero-frame failure.
- Added no-clobber `probe_mimo_video.py`; generated a 3-frame 224x224 MP4 and
  sent it to live MiMo 8090 as `video_url`. Result HTTP 200 and answer
  `红色、绿色、蓝色` prove the deployed model path accepts native video.
- Completed Phase 1/2 contract: optional bounded JPEG on audio append, existing
  FSM owns frame lifecycle, accepted frames become one ordered 1 FPS JPEG
  sequence at DECODE.
- First combined frontend patch failed exact-context verification because the
  settings panel is stored as one long HTML line; no partial edit was applied.
  Split the frontend change into exact CSS, markup and JavaScript patches.
- Implemented optional browser camera capture with no independent video timer:
  `flush()` may attach one JPEG only while sending an audio chunk and no more
  than once per second. Stop/reset releases the camera. Service validation,
  accepted-turn video encoding, current/history `video_url` ordering and runner
  command projection are implemented.
- Five focused video tests initially passed 4/5; the only failure was a new
  fake SSE fixture that combined event and blank delimiter in one bytes chunk.
  Corrected it to the established line-wise fixture; video and pure-audio Chat
  payload tests passed. A later runner regression expected unconditional
  `barge_in`; updated the stale assertion to the current playback-gated policy.
- Added `generate_tts_fixture.py` and generated a no-clobber 24 kHz WAV asking
  `请按顺序说出视频中出现的三种主要颜色。` at
  `tts_fixture_20261030T090652Z_0db0dbc9/input.wav` for full WebSocket acceptance.
- First full video01 WebSocket probe admitted and decoded the audio but reported
  `video_frame_count=0`; MiMo correctly said it could not see video. Root cause
  was protocol adaptation before the FSM: `svad_debug_server` rebuilt the audio
  append with only audio/format/rate and omitted the companion `video_frame`.
  The FSM and media encoder were not implicated. Preserve this failed artifact
  `live_svad_probe_20261030T091105Z_bdfd5347` and forward the optional companion
  field in the same audio append before rerunning.
- A separate ad-hoc encoder inspection command used an invalid dotted Python
  import containing a numeric directory name and raised SyntaxError. It changed
  nothing; focused media contract tests already pass.
- Added a regression test that forwards valid JPEG frames through the real
  WebSocket adapter and asserts `chat.started.video_frame_count=3`; adapter
  tests also prove video stays in accepted decode chunks but is stripped from
  realtime runner commands. Both tests pass after an interrupted run was
  safely restarted with no residual unittest process.
- Rolled only owned 8080 from orphaned `video01` child to host-tracked
  `video02`; MiMo 8090 and external TTS were preserved. Generated a 24 kHz
  spoken question fixture through the formal streaming TTS client.
- Fresh full artifact `live_svad_probe_20261030T125627Z_9a2a2c91` passes:
  VASD_SEM accepted, VAED decoded, `chat.started.video_frame_count=8`, and MiMo
  answered `视频中出现的三种主要颜色依次是红色、绿色和蓝色。`
- Added `Doc/stage5-mimo-video/README.md` with protocol, limits, evidence and
  the explicit boundary that current model execution occurs at DECODE rather
  than native incremental multimodal KV prefill.
- User reported a later `MiMo Chat HTTP 400` with processor input
  `tensor([], size=(0, 3, 360, 640))`. Logs confirm the error at 13:08:21 UTC:
  video reached MiMo but the short MP4 decoded to zero frames. This is an
  in-memory OpenCV container-decoding defect, not a VAD/FSM ownership error.
- Replaced accepted-turn MP4 conversion with vLLM native `video/jpeg` frame
  sequence. Direct 8090 probes with one and three frames both returned HTTP 200.
  Four focused JPEG-sequence tests pass.
- Rolled only 8080 from video03 to video04. Single-frame artifact
  `live_svad_probe_20261030T133852Z_70cfe560` completed Chat without HTTP 400;
  multi-frame artifact `live_svad_probe_20261030T133926Z_77917ef8` answered
  `视频中出现的三种主要颜色依次是红色、绿色和蓝色。`

### Test Results
| Test | Expected | Actual | Status |
|------|----------|--------|--------|
| Native MiMo video probe | `video_url` accepted and color order understood | HTTP 200, red/green/blue | PASS |
| JPEG validation/frame-sequence encoding | Ordered frames and invalid media rejection | Focused tests pass | PASS |
| VAD chunk ownership | Rejected frame discarded; accepted frames exact once | Focused adapter test pass | PASS |
| Runner compatibility | No `video_frame` in runner append commands | Focused adapter test pass | PASS |
| Chat payload | video, audio, instruction ordering; audio-only unchanged | Focused tests pass | PASS |
| WebSocket forwarding | Companion frames reach accepted Chat turn | 3-frame fake provider test pass | PASS |
| Full live audio+video | 8080 VAD path delivers frames to MiMo | 8 frames, correct color answer | PASS |
| Short single-frame video | No zero-frame processor failure | chat.done, no HTTP 400 | PASS |
| Browser real camera | Permission, preview and real scene | Awaiting user | OPEN |

### Errors
| Error | Resolution |
|-------|------------|
| Combined frontend patch context mismatch | Switched to precise dynamic insertion; no partial edit existed |
| Fake SSE fixture ended inside event | Changed fixture to line-wise SSE chunks |
| Old PREFILL test expected unconditional barge-in | Updated assertion to current playback-gated policy |
| First live probe had zero video frames | Forwarded `video_frame` in WebSocket adapter and added regression coverage |
| Short-video diagnostic used `cv2.VideoCapture(BytesIO(...))`, unsupported by installed OpenCV overloads | No MiMo request was made; retry using explicit temporary MP4 paths |
| Direct OpenCV stream-buffer reproduction segfaulted | It confirms the unstable in-memory MP4 decoder boundary and left no process; stop exercising that API directly and investigate vLLM's tested `video/jpeg` frame-sequence format |
| Short MP4 reached MiMo as a zero-frame tensor | Replaced product transport with tested `video/jpeg` frame sequence; one-frame and multi-frame live regressions pass |
| Initial unprivileged remote branch lookup failed DNS | No Git state changed; use the existing env/github_env network path for fetch and push verification |
