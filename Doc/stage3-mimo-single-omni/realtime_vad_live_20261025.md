# MiMo Voice Input With Existing VAD Frontend

2026-10-25. This replaces the manual-recording experience as the current
delivery target. Historical manual-turn documents and artifacts remain intact.

## Architecture

The homepage hosts the original `realtime_web` application, capture worklet,
playback worklet and `qwen3-turn` VAD profile specialized for MiMo. The real
`DuplexSessionManager` and `DuplexSessionRunner` own acoustic turn detection,
input buffering, cancellation epochs, playback ACK and conversation history.

```text
continuous microphone PCM24k
  -> existing Silero/server_vad -> committed audio
  -> MiMo-V2.6-Flash-RL content SSE
  -> ordered Qwen3-TTS CustomVoice segment synthesis
  -> PCM24k -> original playback worklet -> playback ACK ledger
```

MiMo is the only understanding/reply model. No Qwen Omni processor, thinker
prefill, embeddings, native talker or native code2wav is loaded by this path.
Existing Qwen pure PCM/history preparation helpers are reused by composition.
One external virtual stage represents MiMo and independent TTS HTTP lifecycles.
This is concurrent capture and interruptible committed-turn inference, not
native continuously incremented audio KV or a single persistent TTS text KV.

Default voice is Vivian. Server VAD threshold0.5, prefix300ms, silence500ms;
create_response/interrupt_response enabled. One admitted realtime session.
Completed TTS segments supply exact cumulative audio/text marks. Partial
segments do not invent word alignment or commit unplayed assistant text.

## Access And Startup

Current UI origin: `http://28.29.210.210:8080/`.
Model services remain private: MiMo `127.0.0.1:8090`, TTS `127.0.0.1:8093`.
Legacy allowed-port8080 strategy is retained; historical7865 returned an
IT-gateway502. The user confirmed8080 TTS preview access before this UI swap.
New realtime microphone/playback acceptance still requires the user's Mac.

Mac command using a fresh profile:

```bash
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
  --user-data-dir=/tmp/chrome-mimo-vad-8080-20261025 \
  --unsafely-treat-insecure-origin-as-secure=http://28.29.210.210:8080 \
  --new-window http://28.29.210.210:8080/
```

Select Start session once; VAD automatically ends spoken turns. Capture
continues during playback and new speech interrupts the response.
Use one browser session at a time. `/tts` remains the standalone preview;
`/manual` and `/api/chat` retain the earlier diagnostic integration.

Only the UI is replaced; existing GPU models are not restarted. Current
launch/exit manifests are authoritative for ownership:

```text
workspace/logs/20261025T143656Z_mimo_single_phase2_a205c357/
  mimo_restart01_launch.json
  tts_restart01_launch.json
  mimo-realtime-ui_live8080_02_launch.json
```

Recreate UI only after verifying and gracefully stopping its exact owned
supervisor. Do not run legacy broad pkill commands or overwrite an attempt.

```bash
source /mnt/geminihzceph/user_whynotzhliu/my_envs/env.sh
conda activate omni
CUDA_VISIBLE_DEVICES='' NO_PROXY=localhost,127.0.0.1 \
no_proxy=localhost,127.0.0.1 \
python -B workspace/experiments/20261025_mimo_single_phase2/run_service.py \
  --run workspace/logs/20261025T143656Z_mimo_single_phase2_a205c357 \
  --role mimo-realtime-ui --attempt NEW_UNIQUE_ATTEMPT \
  --ui-host 28.29.210.210 --port 8080
```

Supervisor sets process-local source/runtime overlay, offline flags and
exclusive logs. UI GPU visibility is empty; inference runs on GPUs0-3 and4
in the unchanged model services.

## Verification

- Six focused tests against the actual manager/runner pass after the final
  chronological prompt fix (session35810). Cover full ACK/history, partial
  prefix cancel, stale epoch suppression, pipeline failure and retry, auto
  VAD scorer, unread old text followed by voice, admission/close/reconnect.
- The original profile contract passes in Node VM: fixed MiMo model,
  server_vad, barge_in_on_speech, continuous audio append.
- Real Silero + existing GPU models replay passed on isolated7866:
  `realtime_check_20261025T172931Z_0fc2b2d2`.
  Automatic audio3+4 -> answer7,1.92sPCM/RMS0.08308, ACK/history followup,
  speech while generating/streaming -> actual cancellation -> new answer7.
  No old PCM after cancellation; clean disconnect logs external tasks0.
- Every GPU replay saves exclusive WAVs/events/summary. Final8080 replay and
  handoff ownership results are appended below after completion.

These are server-side fixture/protocol results. No browser executable was
available; no actual Mac microphone capture, acoustic playback/listening,
camera, echo loop or desktop/mobile screenshot acceptance is claimed.

## Failures And Decisions

1. Manual-turn demo bypassed the already-existing voice workflow. Restore
   original frontend and real VAD/runner; preserve the demo for diagnostics.
2. Omitted bridge audio hint caused MiMo to transcribe rather than answer.
   Restore the exact audio question hint without importing the Qwen bridge.
3. Error closes protocol response but does not complete the model turn.
   Emit a distinct terminal, recognize it after request unbinding, and release
   the exact failed streaming binding/resources. Error retry now passes.
4. Qwen's final media-first history merger moved new audio before old text,
   producing recovery refusals. Distinct consecutive user messages instead
   repeated the old history reply. Saved-input GPU probe76ca351f compares
   four formats; chronological merged user parts answer7 without lost history
   or additional prompt intervention. Adopt `format_mimo_history`, leaving
   the addressable ledger and whole-turn retention unchanged.
5. aiohttp disconnect cancellation interrupted finalization and stranded
   admission slots. Use tracked shielded cleanup tasks and drain them during
   application shutdown. Close/reconnect now passes.
6. Nearly silent mock audio was rejected without committed input. Use an
   effective-amplitude fixture. GPU checker used wrong transcript event at
   first; consume existing output_audio_transcript deltas.
7. Initial180s readiness wait expired before UI finished importing. Extend
   only startup wait600s, keeping turn/content assertions unchanged.
8. Initial8080 bind check reported errno98 before creating child/log. Later
   TCP/argv inventory found no8080 listener and old UI exit0 was confirmed.
   Retry as independent live8080_02. Transient socket reuse is plausible,
   not proven; no unknown process was stopped or protection bypassed.

Failed artifacts retained: b7647d5f, bba1e346, f6ec9646,927b90be,cb266532.
These failures are not passing samples.

## Remaining Gates

Existing Silero is acoustic VAD, not learned semantic endpointing. Phase5B
semantic policy remains pending; broader acoustic false positives, echo,
long sessions and performance remain open. TTS real-stage/connector idle,
mixed proper-noun pronunciation, actual browser capture/playback and wider
regressions are independent gates. HTTP cancellation and runner cleanup do
not close the strict GPU-stage idle gate.

Canonical status/recovery remains the named Git planning directory, not
this historical snapshot. No checkpoint/environment install or automatic
Git commit/push is part of this deployment.

## Final Live Handoff

At17:37Z final8080 replay passed:
`realtime_check_20261025T173356Z_b5683805` (name records checker start).
Automatic speech3+4 answered7 with1.92sPCM/RMS0.08308, ACK/history followup
correct, real new speech cancelled old generation/streaming, recovered answer7,
and no old audio after cancellation. Receiver/connection cleanup completed.

Live UI child343636, supervisor343381, tool session43259, attempt live8080_02.
Original MiMo child187389/supervisor187203 and TTS187446/187272 unchanged.
The verified isolated7866 UI exited0. Handoff HTTP200 includes homepage,
profile, app.js, both worklets, /tts and /manual; both health flags true.
Listener checks confirm8080=currentIP and8090/8093=loopback, no7865/7866.
Live NO_PROXY/no_proxy are explicit; model-input debug capture is disabled.

User-facing realtime slice is server-verified and deployed. All verification
processes finished; the requested three services remain running. Wider stage
gates above remain open. This snapshot and the design are published as new
files only; external historical records and README are not replaced.
