# Stage 4: MiMo Semantic VAD

This stage adds the specified acoustic + semantic input controller on branch
`feature/SVAD`. The normative behavior remains
`duplex_input_fsm_function_spec.md`; this document describes the repository
integration and its current acceptance boundary.

## Implemented Components

- `DuplexInputFSM`: exactly `Silence`, `Judge`, and `Listen`.
- `SemanticVADController`: calls VASD only in Judge and VAED only in Listen.
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
NO_BREAK telemetry, Break priority, exact-once candidate delivery, immediate
speech-stop decode, reset behavior, configuration isolation, MiMo label
parsing, and WebSocket dispatch.

Latest local results:

- Stage 4 control/adapter tests: 23/23 passed.
- Stage 3 + Stage 4 focused Python regression: 41/41 passed.
- Python compile check: passed.
- Frontend deterministic state check: passed.

No fresh GPU model-quality run is claimed by this document. Real MiMo VASD and
VAED latency, false-interruption/reject quality, multilingual behavior, and
long-session resource use remain integration acceptance gates.
