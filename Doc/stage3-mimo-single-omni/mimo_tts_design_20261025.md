# Manual-Turn MiMo To TTS Design

2026-10-25: user confirms the standalone TTS page works but requests actual
MiMo-to-TTS integration. This implementation slice advances Phase3/4 without
closing Phase2's remaining true-idle/content gates or introducing VAD.

## Implementation Decisions

- Separate parent-owned application, no edits to either inference submodule.
- Reuse running MiMo loopback8090 and CustomVoice loopback8093. Keep externally
  reachable8080; preserve old TTS assets and provide them at /tts.
- POST text or bounded WAV input plus bounded completed conversation history.
  Only fixed local upstreams; no external URL fetch or model endpoint selection.
- MiMo delta.content supplies transcript and segmentation; reasoning/tool/control
  content is not spoken. Require explicit valid completion and SSE[DONE].
- Reuse pinned SpeechTextSplitter via direct stdlib import. Preserve exact source
  spans externally; cap input/reply/segments and use one bounded ordered queue.
- Separate MiMo reader and TTS worker so audio can begin before final text.
  Stream typed NDJSON events including text, segment metadata and base64PCM.
- Stop/disconnect cancels both tasks and closes both upstream HTTP contexts.
  Browser revision invalidates late chunks, stops queued playback and stores
  only completely played segment prefixes in history on interruption.
- Manual microphone submit uses monoWAV; no separate ASR/understanding model.
  Raw audio enters MiMo directly, not the old Qwen bridge.
- No learned semantic VAD, continuous-input duplex, word alignment or native
  incremental audio KV claim. Existing engine runner composition remains open.

## Independent Checks

1. Focused local fake-upstream tests: SSE fragmentation, finish/DONE errors,
   content filtering, numeric/abbreviation segmentation, exact spans, queue
   bounds, ordered PCM, disconnect/error cleanup and stale-turn isolation.
2. Real GPU: text prompt response converted to PCM (not a fixed TTS sample);
   input WAV answered by MiMo with text/PCM; multi-turn context.
3. Controlled slow MiMo stream with real GPU TTS: first audio before MiMo DONE.
4. Stop during MiMo and TTS, recovery request, known engine abort evidence;
   do not claim exact true-stage idle while Phase2 diagnostics remain open.
5. Page/JS syntax, 8080 deployment and original TTS preview regression.
   Browser/microphone screenshots depend on available browser tooling.

Tests use env.sh then omni; no full CPU regression prerequisite. Every run
creates exclusive new artifacts; no old logs/audio/results are overwritten.
