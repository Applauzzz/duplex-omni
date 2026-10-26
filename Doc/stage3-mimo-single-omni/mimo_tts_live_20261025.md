# MiMo To Qwen3-TTS: Live Manual-Turn Integration

2026-10-25 16:16Z. User confirmed standalone TTS access and requested actual
MiMo-to-TTS. This slice now serves dialogue at `http://28.29.210.210:8080/`.
The old standalone preview remains at `/tts`. Refresh the existing8080 page;
the browser secure-origin configuration does not need a new address.

## Implemented Path

Text or monoWAV input -> MiMo-V2.6-Flash-RL content-only SSE -> pinned sentence
splitter/exact source spans -> ordered independent CustomVoice requests ->
typed NDJSON text/PCM events -> browser scheduledPCM playback.

New parent-owned files:
`workspace/experiments/20261025_mimo_tts_integration/`
contains backend.py,server.py,chat.html,test_integration.py,check_gpu.py and
check_frontend.js. Existing run_service.py gained a mimo-tts-ui role only.
No Qwen Omni prefill/embedding/bridge or model imports; pinned SpeechTextSplitter
is loaded directly as a stdlib-only source module.

- Text submit, manual recording start/end-and-submit, stop, new conversation,
  voice/language controls, live response text and replay.
- Raw audio goes directly to MiMo; no ASR service joins the model pipeline.
- Reasoning/tool/control content does not enter speech; require finish + DONE.
- Bounded4-segment queue,320-character segments,4096-character reply budget,
  bounded history/audio/PCM and at most2 active dialogue requests.
- Separate MiMo reader/TTS worker; model_done is not audio done or playback done.
- Cancellation closes both upstream contexts/tasks and discards queued segments.
  Browser revision isolates late output, stops scheduled audio and only records
  completely played segment prefixes on interruption.
- Input history is provisional browser-local complete-turn history, not existing
  engine session/ledger composition. No engine protocol/ACK reuse claim.

## Ownership

Run: `workspace/logs/20261025T143656Z_mimo_single_phase2_a205c357`.

| Role | Attempt | Child PID/PGID | Supervisor | Tool session | Bind |
|------|---------|----------------|------------|--------------|------|
| MiMo GPU0-3 | restart01 | 187389 | 187203 | 38811 | 127.0.0.1:8090 |
| TTS GPU4 | restart01 | 187446 | 187272 | 78763 | 127.0.0.1:8093 |
| IntegratedUI, noGPU | live8080_01 | 256583 | 256349 | 64792 | 28.29.210.210:8080 |

Original model processes retained; only UI restarted. Old allowed8080_01 and
test isolated01 exited0 after exact ownership/PGID checks. Verify records and
current commands before future signals. Never reuse historical PIDs blindly.

Launch used env.sh then omni, explicit NO_PROXY/no_proxy loopback, no UI GPU:

```bash
source /mnt/geminihzceph/user_whynotzhliu/my_envs/env.sh
conda activate omni
export NO_PROXY=localhost,127.0.0.1
export no_proxy=localhost,127.0.0.1
CUDA_VISIBLE_DEVICES='' python -B workspace/experiments/20261025_mimo_single_phase2/run_service.py \
  --run workspace/logs/20261025T143656Z_mimo_single_phase2_a205c357 \
  --role mimo-tts-ui --attempt live8080_01 --ui-host 28.29.210.210 --port 8080
```

Launch/log/exit names are exclusively created; future launches need a new
attempt. Model APIs remain loopback, clients trust_env=False. No installs,
checkpoint changes, inference-submodule edits, commits/pushes or network rules.
HTTPUI is an unauthenticated trusted-network experiment, not public deployment.

## Verification

- Focused test_integration.py:11 passed. Covers exact spans/abbreviations/numbers,
  content-prefix filtering, bounds, ordering, slowSSE firstPCM, tool/truncated
  errors, TTS failure, oddPCM, disconnect/recovery and admission limits.
- check_frontend.js: deterministic state checks pass for complete history,
  played-prefix interruption, stale completion and invalidPCM. Not a real
  browser/screenshot/microphone test.
- GPU check on isolated7866 then final8080 both exited0. Final artifact:
  `integration_check_20261025T161630Z_f12d5afb` in model run; earlier:
  `integration_check_20261025T160624Z_af0ad2d5`. WAV,requests,events,summary retained.

| Actual GPU path | Final result |
|-----------------|--------------|
| Text:2+2 | MiMo answersfour,PCM1.28s/61440bytes,RMS.06546 |
| Prior-question history | MiMo recalls2+2question,PCM1.92s/92160bytes |
| RawWAV question:3+4 | MiMo answersseven,PCM1.92s/92160bytes,RMS.08308 |
| Cancel at text/audio then recover | Client close/application tasks terminated, recoverytext/PCM success |
| Controlled slowMiMo + realGPU TTS | FirstPCM.02554s vs model_done4.00588s |

Audio input is a reproducible TTS-generated question fixture, not a real user
microphone recording. No independentASR/listening acceptance was repeated.
Short real replies finish text before firstaudio; slow fixture proves overlap.
FirstPCM is transport, not effective-energy or browser audible onset.

At16:06:27 TTS log matched internal speech-94a63b5d027d49a6-ab203217:
Orchestrator and AsyncOmni Aborted, SpeechE2E cancelled28ms. NewUI logs also
show MiMo/TTS context closure and request cancellation. This does not close
the stricter real-stage/connector idle gate from Phase2.

Initial focused test failed only an expected-string assertion that removed the
abbreviation whitespace inDr. Smith. Explicit expected segments corrected;
all11 passed twice, including after explicit final queue drainage.
Aiohttp NotAppKeyWarning retained to match existing preview's string-key
access; not a runtime failure. Browser executable not available; no installs.

## Status And Next Work

Manual-turn integration slice complete, original models/UI left running for use.
Phase2 true-idle/mixed-quality, Phase3 existingrunner composition, Phase4 actual
browser/mic and broader acceptance remain open. Phase5 VAD/semantic/continuous
duplex not started. Segments are separate TTS requests, not one continuous KV.
No server-side automatic endpointing or live concurrent microphone reception.

## Final Handoff Checks

At16:20Z exact MiMo/TTS/UI child argv and supervisor role/attempt matched the
launch manifests; all three services remained running. Listeners are8080 on
28.29.210.210 and8090/8093 on127.0.0.1;7865/7866 no longer listen.
Home,/tts and capture_worklet.js returned200; both model health flags true.
Original /api/speech GPU regression passed with2.72sPCM/130560bytes,RMS.10167,
SHA matching the historical sample. New exclusive artifact:
`preview_check_20261025T162007Z` in the same run.
Both inference submodules remain clean; parent git diff --check passed.
These final checks still do not prove browser microphone or audible playback.
