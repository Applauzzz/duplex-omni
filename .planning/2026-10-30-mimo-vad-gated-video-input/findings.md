# Findings & Decisions

## Requirements
- MiMo remains the sole multimodal understanding/reasoning model.
- Add video input to the existing browser voice experience.
- Video follows VAD admission. Do not create video-specific states, endpointing,
  semantic decisions, history timing or commit policy.
- If candidate audio is rejected as non-semantic, associated video is rejected.
- If audio is admitted into Listen, associated video is admitted and supplied
  to MiMo with the accepted turn.
- Preserve current TTS, interruption, retained-context and audio-only behavior.

## Research Findings
- Parent branch was synchronized at merged main commit `3f3e4ca`; new branch is
  `feature/video-input`. Both submodules are clean. Existing untracked
  `wx_tts_ref.py` is unrelated and must remain untouched.
- Current browser sends PCM audio only. `SemanticRealtimeAdapter` buffers audio
  mappings and emits the complete accepted audio sequence at DECODE.
- Current `MiMoChatProvider` builds OpenAI-style content with `input_audio` and
  history audio. It has no image/video part yet.
- Current vLLM Chat parser supports `video_url` content and raw/base64 video
  loading generally. Model-specific MiMo video registration and accepted codec
  remain to be verified before choosing browser transport.
- The minimal lifecycle should attach optional video data to each audio append,
  so existing candidate and turn buffers are the only ownership mechanism.
- Checkpoint chat template explicitly renders `video_url` as
  `<|vision_start|><|video_pad|><|vision_end|>`. The checkpoint config contains
  the vision tower, video start/end/token IDs, 1 FPS input, two video tokens per
  second, timestamp support and bounded pixel settings.
- Current vLLM registers `MiMoV2OmniForCausalLM` with multimodal limits for
  audio, image and video. Its processor converts decoded THWC video to TCHW plus
  timestamps and treats decoded input frames as one second apart.
- OpenAI Chat accepts `video_url`; vLLM also has explicit production tests for
  inline `data:video/jpeg;base64,<frame1>,<frame2>,...` frame sequences with
  1 FPS metadata and frame-count limiting.
- Browser MediaRecorder chunks are not selected as the initial contract because
  later WebM chunks may depend on an earlier container header. Independent JPEG
  frames attached to audio chunks are easier to validate, bound and discard.
- Fresh real probe `mimo_video_probe_20261030T083411Z_c03f134a` generated a
  6,802-byte, 3-frame MP4 (red, green, blue) and sent it as `video_url` to the
  existing TP4 MiMo 8090 service. HTTP 200 response was exactly
  `红色、绿色、蓝色`; prompt tokens 142. Native deployed video input is accepted.
- Initial append contract: optional `video_frame` object with base64 JPEG data.
  At most one frame is consumed per audio append. Server validates JPEG decode,
  pixel dimensions and a 512 KiB encoded-byte limit. Accepted turns cap at 32
  frames and join their validated base64 payloads in order for `video/jpeg`.
- Privacy/lifecycle boundary: camera capture is opt-in; no frame is sent without
  an audio append, no rejected frame reaches MiMo, and no frame is written to
  tracked files or experiment output during ordinary conversation.
- The FSM remains video-agnostic in code: there is no video field in FSMInput or
  FSMOutput and no video branch in transition logic. The chunk mapping retains
  the companion frame, while semantic providers convert only its audio bytes.
- Existing realtime runner commands explicitly project only audio fields, so
  adding video does not change the downstream runner append schema.
- Full `video02` WebSocket acceptance passed after fixing protocol forwarding:
  eight accepted frames accompanied a VASD-admitted audio turn and MiMo answered
  the requested color sequence. Browser camera permission remains manual.
- A later real browser turn exposed a separate media-container issue: accepted
  frames reached Chat, but short MP4 in-memory decoding returned a zero-length
  `(T=0, C=3, H=360, W=640)` tensor. The FSM was not involved. Reproducing the
  OpenCV stream-buffer API caused a segmentation fault, while ordinary file
  decode succeeded.
- Switched the product path from MP4 to vLLM's tested `video/jpeg` base64 frame
  sequence. Direct one-frame and three-frame MiMo probes both returned HTTP 200.
  Full video04 WebSocket regressions completed without processor 400: single
  frame reached `chat.done`; multi-frame red/green/blue order was correct.

## Technical Decisions
| Decision | Rationale |
|----------|-----------|
| Treat video as optional metadata on an audio chunk | Reuses exact VAD buffering and prevents a second temporal state machine |
| Do not send rejected candidate video to MiMo | Video acceptance is defined by the associated audio's VASD_SEM result |
| Verify native video before implementing frame fallback | MiMo is Omni-capable, but the deployed serving contract must be proven rather than assumed |
| Send accepted JPEGs as vLLM `video/jpeg` frame sequence | Keeps browser chunks independently valid and avoids unstable in-memory MP4 decoding |
| Use one frame per audio submit interval initially | Matches the checkpoint/vLLM 1 FPS video assumption and bounds bandwidth and vision tokens |
| Cap accepted video at 32 seconds/frames | Matches current vLLM video loader expectations and prevents unbounded turn memory |

## Issues Encountered
| Issue | Resolution |
|-------|------------|

## Resources
- `workspace/experiments/20261025_mimo_tts_integration/semantic_vad.py`
- `workspace/experiments/20261025_mimo_tts_integration/svad_debug_server.py`
- `workspace/experiments/20261025_mimo_tts_integration/svad_debug.html`
- `vllm-src/vllm/entrypoints/chat_utils.py`
