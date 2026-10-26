# Existing Realtime Frontend And VAD Integration

2026-10-25. User corrected the manual-recording detour: MiMo accepts original
audio and the project already has a VAD voice frontend. This supersedes the
manual-turn experience as the active delivery target, preserving its records.

## Reuse And Scope

- Read stage1 architecture/VAD/running and stage2 README/plan_a. The documented
  workflow retains realtime_web, automatic server_vad, playback ACK and barge-in.
- Host the existing realtime_web index/app.js/capture and playback worklets.
  A small MiMo profile specializes the existing turn profile's labels/model;
  it does not create a second recorder or playback implementation.
- Compose the real DuplexSessionManager/Runner through DuplexStagePort.
  Reuse existing committed-turn PCM buffering and whole-turn audio/history
  preparation, but never load Qwen Omni processor, embeddings or reasoning.
- External virtual stage owns the already-tested MiMo SSE -> independent
  Qwen3-TTS backend. One virtual lifecycle represents both HTTP clients, not
  an engine-managed GPU stage or native persistent audio KV.
- Existing ServerTurnDetector/Silero drives automatic commits. Existing runner
  owns fencing, history, playback ACK, cancellations and input backpressure.
- Exact completed TTS segment boundaries attach cumulative text/audio marks
  to the final PCM chunk of each segment. Partial segments have no invented
  word timing. Model completion is separate from playback completion.
- No learned semantic VAD claim; semantic endpointing remains a separate gate.
- Fixed loopback model services remain running. Test separate loopback7866
  first, then switch only8080 application after ownership checks.
- Preserve /tts and the earlier manual-turn page/API for diagnostics.

## Validation Gates

1. Actual runner composition with controlled external stages: text/audio,
   ordering, segment marks, ACK history, stale output, failure and cancellation.
2. Real Silero with recorded speech followed by silence: speech_started,
   speech_stopped, automatic commit without manual client commit.
3. Actual GPU MiMo/TTS voice turn, multi-turn context, new speech while output
   runs, stale-output suppression and recovery. Save exclusive artifacts.
4. Original frontend assets/profile contract and preserved TTS endpoints.
   Browser microphone/listening acceptance is reported separately if no
   browser executable is available. No full CPU regression prerequisite.

Runtime always initializes env.sh then activates omni. No installs, checkpoint
changes, automatic commits or replacement of historical experiment outputs.
