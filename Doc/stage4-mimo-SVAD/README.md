# Stage 4: MiMo Semantic VAD

This stage adds the specified acoustic + semantic input controller on branch
`feature/SVAD`. The normative behavior remains
`duplex_input_fsm_function_spec.md`; this document describes the repository
integration and its current acceptance boundary.

Detailed current-state documentation:
[`current_vad_implementation_20261026.md`](current_vad_implementation_20261026.md).
It describes the normative FSM and the currently running `svad12` v0.2 behavior.

## Implemented Components

- `DuplexInputFSM`: exactly `Silence`, `Judge`, and `Listen`.
- `SemanticVADController`: calls VASD only in Judge and VAED only at an AVAD
  `speech_stopped` edge while in Listen.
- `MiMoSemanticVADProvider`: sends candidate audio to the existing MiMo
  `/v1/chat/completions` audio interface and parses:
  - VASD: `<b>`, `</b>`, or internal `REJECT`.
  - VAED: `<c>` or `</c>`.
- `SemanticRealtimeAdapter`: runs Silero AVAD, buffers candidate audio, and
  maps FSM events onto the existing realtime runner.
- Speak-decision boundary: `choose_decode_token` implements
  `p(speak) > threshold` versus direct EOS without putting a fourth state in
  the input FSM.

The implementation is in
`workspace/experiments/20261025_mimo_tts_integration/semantic_vad.py`.

## Realtime Configuration

The MiMo realtime profile now opens with an application-owned turn detector:

```json
{
  "model": "mimo-v2.6-flash",
  "overlap_policy": "listen_only",
  "audio": {
    "input": {
      "format": {"type": "audio/pcm", "rate": 24000},
      "turn_detection": {
        "type": "semantic_vad",
        "threshold": 0.5,
        "prefix_padding_ms": 300,
        "silence_duration_ms": 500,
        "min_speech_duration_ms": 96
      }
    }
  }
}
```

The parent WebSocket service consumes `semantic_vad` before constructing the
engine session. The engine receives `turn_detection: null` and
`overlap_policy: listen_only`, so the legacy server-VAD policy cannot also
interrupt or auto-commit the same audio.

The existing modes are unchanged:

- `turn_detection: {"type": "server_vad", ...}`: legacy Silero interruption
  and endpointing.
- `turn_detection: null`: client-owned/manual turns.

Changing semantic-VAD configuration after opening a session is currently
rejected. Input clear/cancel resets both semantic FSM buffers and AVAD stream
state.

## Event Mapping

| FSM event | Realtime runner commands |
|---|---|
| `NO_OP` | None |
| `PREFILL` | `barge_in`, then all exact-once candidate audio appends |
| `CHUNK_PREFILL` | Append only the new audio chunk |
| `DECODE` | Append the final chunk, then final commit with response creation |

`barge_in` is sent before initial candidate audio because the current runner
clears pending input during interruption. Reversing that order would discard
the newly accepted user audio.

## Current Engine Boundary

The current MiMo stage plugin accepts committed whole turns and rejects
non-final model appends. Therefore:

- FSM event ordering and audio delivery are real.
- Candidate and Listen chunks are delivered exactly once to the runner input
  buffer.
- Actual MiMo model execution starts on final commit.
- This checkpoint must not be described as native incremental MiMo KV prefill.

Native model-side Chunk Prefill requires a future stage-port/model capability;
it is not simulated or claimed here.

## Verification

Focused Stage 4 tests cover the specification's T01-T13 cases, Reject versus
NO_BREAK telemetry, Break priority, exact-once candidate delivery,
endpoint-only VAED, incomplete pause/resume, timeout decode, reset behavior,
configuration isolation, MiMo label parsing, Chat cancellation and WebSocket
dispatch.

Latest local results:

- Current semantic VAD and debug WebSocket suite: 35/35 passed.
- Python compile check: passed.
- Frontend deterministic state check: passed.

The live checks below establish service wiring and a narrow speech/noise smoke.
Broad false-interruption/reject quality, multilingual behavior, browser
microphone acceptance and long-session resource use remain open gates.

## Live Acceptance Console

The current uncommitted acceptance slice adds a standalone console that runs
AVAD, MiMo VASD/VAED, the input FSM and MiMo text Chat. It does not start TTS.

Current origin: `http://28.29.217.180:8080/`.

The page shows the active Silence/Judge/Listen state, waveform, AVAD
probability, semantic label, raw break/reject/complete values, FSM event,
candidate/turn chunk counts, MiMo decision latency and a transition timeline.
The transition log also shows MiMo's exact generated `message.content`, the
normalized command and whether strict command validation passed.

The normative labels are not single tokenizer tokens in this checkpoint:
`<b>` uses two tokens, `</b>` three, `<c>` two, `</c>` three, and `REJECT`
two. The runtime therefore uses constrained internal single-token class codes
without modifying the tokenizer or checkpoint:

- VASD: `A -> <b>`, `B -> </b>`, `C -> REJECT`.
- VAED: `A -> <c>`, `B -> </c>`.

Each request sets `allowed_token_ids`, `logprob_token_ids`, `logprobs=true` and
`max_tokens=1`. The sampled code must equal the candidate-logprob argmax. The
page and logs expose the canonical-label logprobs, normalized confidence and
top-two logprob margin. External FSM events continue to use the six normative
tokens rather than the internal A/B/C codes.

Continuous `Silence -> Silence` audio blocks are not written as separate INFO
transitions. They are accumulated and emitted once as a
`semantic_vad_state_interval` with start/end time, duration and true silent
chunk count when Silence ends, the FSM resets, or the connection closes.

On macOS, microphone access for this HTTP test origin requires a dedicated
Chrome profile:

```bash
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
  --user-data-dir=/tmp/chrome-mimo-svad-8080-20261026 \
  --unsafely-treat-insecure-origin-as-secure=http://28.29.217.180:8080 \
  --new-window http://28.29.217.180:8080/
```

Live services currently use separate retained run directories:

- MiMo PID 42095, supervisor 42091, GPU 0-3, loopback 8090.
- SVAD UI `svad12` PID 146753, supervisor 146752, CPU,
  `28.29.217.180:8080`, run directory
  `workspace/logs/20261027T035800Z_mimo_svad_chunk_config/`.
- TTS remains stopped; GPU 4-7 are unused.

Fresh real-model checks before user acceptance:

- MiMo and UI health return HTTP 200; UI health-to-MiMo latency was 1.5 ms.
- Warm VASD latency: 41.8-49.4 ms over three repeated requests.
- Warm VAED latency: 37.6-39.3 ms over three repeated requests.
- First VASD after model startup took 24.7 s due to one-time multimodal warmup.
- Real speech replay produced Silence -> Judge, then BREAK/PREFILL -> Listen,
  then COMPLETE/DECODE -> Silence. Observed semantic calls were 66-118 ms in
  the chunked WebSocket replay.
- One second of low-amplitude synthetic noise returned Reject in 67.3 ms.

These are service-side checks, not the user's browser microphone acceptance.
No acceptance-console change has been committed or pushed.

## FSM-Driven Text Conversation

The current uncommitted `svad12` acceptance service connects FSM DECODE
to MiMo text generation. TTS remains stopped.

- A DECODE carries the complete accepted turn audio to MiMo Chat.
- Chat output streams into the right-side conversation panel.
- A new effective BREAK cancels an active Chat HTTP stream.
- Up to four completed audio/text turns are retained as bounded history.
- VAED runs only on AVAD speech-stop edges using the complete accumulated turn.
- `</c>` keeps Listen across silence; resumed speech continues the same turn
  without rerunning VASD. A later accepted `<c>` starts Chat.
- Incomplete silence defaults to an 8-second external fallback DECODE without
  adding a fourth public FSM state.

The browser has one all-in-one settings panel for the target audio chunk
interval, all AVAD parameters, VASD
BREAK and VAED COMPLETE probability/margin/confirmation gates, buffer/timeout
values and the Chinese VASD, VAED and Chat prompts. `Apply all settings`
rebuilds the current WebSocket adapter and updates all three prompts without
changing model files or global service state.
The defaults are stored in
`workspace/experiments/20261025_mimo_tts_integration/svad_config.json`.
`/defaults` rereads and validates this file on every page refresh, so local file
edits become the next browser/session defaults without restarting the service.
`audio_chunk_ms` defaults to500ms. It is a minimum target interval; when a
semantic request remains in flight, queued audio is merged into a longer chunk.

The Chat user audio is followed by an explicit Chinese instruction to answer
the user's question rather than transcribe or repeat the audio. Fresh real
probe `chat_probe_20261026T154033Z` produced one Chat turn, zero cancellations,
and the answer `三加四等于七。` for the preserved `三加四等于几` fixture.
