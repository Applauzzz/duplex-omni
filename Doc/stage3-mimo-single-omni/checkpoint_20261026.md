# MiMo + Qwen3-TTS Integration Checkpoint

Date: 2026-10-26. User accepts the basic integration for repository publication.
This is a working integration checkpoint, not completion of every phase gate.

## Delivered

- MiMo is the only multimodal understanding/reply model.
- Independent Qwen3-TTS CustomVoice renders content-only MiMo SSE using ordered,
  bounded sentence synthesis, exact text spans and PCM16 mono24k.
- Original realtime_web, Silero/server_vad, session runner and playback ACK
  ledger provide continuous capture, automatic commits and barge-in recovery.
- Preserve standalone `/tts` and manual diagnostic `/manual` paths.
- Parent-owned adapters/config/tests; unchanged pinned inference submodules.

## Verification

Fresh precommit command, after `source env.sh` and `conda activate omni`, with
process-local `PYTHONPATH` selecting the current runtime overlay/submodule:

```bash
cd workspace/experiments/20261025_mimo_tts_integration
CUDA_VISIBLE_DEVICES='' python -B -m unittest test_integration test_realtime -v
node check_frontend.js
```

Results: 17 focused tests passed (31.010s after imports); Node history,
played-prefix interruption, stale completion and invalid PCM checks passed.
Warnings about package version alignment, CPU CUDA_HOME and aiohttp remain.
The injected TTS failure traceback is an intentional passing recovery case.

Historical real-GPU voice/history/barge-in evidence:
`realtime_check_20261025T173356Z_b5683805`, documented in the realtime live record.
October26 startup01 reached healthy APIs using current source roots. The later
checker was interrupted before a completed result was discovered; no fresh GPU
replay or actual browser/listening acceptance is claimed by this checkpoint.

## Stopped Runtime

User requested stopping services after requesting publication. On October26,
manifest-verified SIGINT stopped UI13059, TTS13083 and MiMo13046 process groups.
Eight H20 GPUs report0MiB/0%; ports8080/8090/8093 have no listeners.
Children remain exited zombies under PID1; old supervisors were already absent.
Do not signal these historical PIDs or claim supervisor exit codes.

Raw shutdown evidence stays outside Git:
`workspace/logs/20261026T060227Z_mimo_single_phase2_b8e9f10b/`
`shutdown_20261026T080615Z_c9f43147/{request,result}.json`.
The previous UI origin28.29.218.180:8080 is not currently serving.

## Recovery

Read the selected plan triplet and `AGENTS.md`; recheck GPU/port ownership and
the current host address. Initialize the user environment, then activate omni.
Default editable installs still target sibling sources; pin this repository's
source/runtime per process rather than reinstalling the environment.

`prepare_runtime.py --binary-source <existing-compiled-vllm-src>` creates a new
exclusive run and checks compatibility. In separate owned terminals, use
`run_service.py --run <new-run> --role mimo|tts|mimo-realtime-ui`
with a unique `--attempt`, ports8090/8093/8080 and UI-only `--ui-host <current-IP>`.
Set CUDA visibility0-3 for MiMo,4 for TTS and empty for UI. Initialize
`NO_PROXY/no_proxy` for loopback and the current UI address. Record manifests
and verify health plus new immutable realtime replay, not health alone.
Do not run overwrite-prone legacy launch/validation scripts.

## Open Gates

Cross-text voice consistency (fixed vivian/Auto/seed42 is already present),
browser microphone/playback, mixed proper-noun quality, strict real-stage/
connector idle, wider acoustic false positives/echo, learned semantic policy,
performance distributions and long-session/wider regression acceptance.

Version/config/source digests: `checkpoint_20261026.json`.
Raw logs/audio, native binaries, models and credential scripts are not published.
