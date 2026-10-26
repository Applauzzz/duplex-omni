# Voice Consistency Diagnosis

Date: 2026-10-26. Status: open, source tracing only.

## Report And Scope

User hears a different timbre on each dialogue turn. Earlier same-text PCM
hash checks did not accept speaker consistency across different answers.
Do not dismiss a substantial identity change as ordinary prosody.

This investigation changes records only. No inference code, checkpoint,
sampling configuration, installation or running service was changed.

## Confirmed Source Path

- realtime_backend.py:300 passes vivian/Auto on every response.
- backend.py:299-305 sends CustomVoice, voice, language, seed42 and PCM24k.
  Each sentence segment opens a new /v1/audio/speech synthesis request.
- Qwen3TTSAdapter maps voice to additional_information.speaker and defaults
  absent instructions to an empty string.
- prompt_embeds_builder.py:1402-1424 embeds the selected CustomVoice spk_id
  into each prompt. Local checkpoint config maps vivian to3065.
- serving_speech.py:2036-2044 forwards seed into stage0 seed and
  tts_local_seed; residual sampling paths use explicit request seeds.
- The deployed H20 config inherits talker temperature0.9/top_k50 and
  subtalker do_sample=true/temperature0.9/top_k50/top_p1.0.
  Historical startup logs list all nine speakers and these model sampling
  defaults. These are historical configuration evidence, not fresh runtime
  inspection of the user's current instance.

No source evidence was found for intentional voice rotation or silently
dropping voice/seed. A fixed seed can make repeated identical inputs
reproducible without proving speaker consistency across different inputs.

## Candidate Causes, Not Proven

- Every segment/turn starts synthesis afresh with no preceding acoustic
  continuation. Text-conditioned delivery can vary without changing spk_id.
- Auto provides no explicit codec language ID for Vivian; Chinese does.
  Language conditioning may affect pronunciation/delivery, but it has not
  been shown to cause this reported timbre drift.
- No stable style instruction is provided. Its effect on consistency remains
  to be measured, not assumed.
- Request-specific speaker conditioning, decoder-state leakage or playback
  rate errors remain possible if differences include apparent gender changes
  or inconsistent delivery for identical text. Source tracing alone cannot
  rule these out in the deployed process.

Do not claim temperature0.9 alone causes random per-turn voices when seed42
is already supplied. Do not claim Chinese/instructions or greedy decoding
will fix the issue without comparing actual audio.

## Runtime Limitation

Current host interface includes28.29.218.180, unlike the October25 deployment
at28.29.210.210. Historical PIDs were absent even outside the sandbox and
local8093/health failed to connect. This does not establish that services on
the earlier host have stopped. No fresh GPU audio or listening comparison
was performed during this diagnosis.

## Next Acceptance

1. Locate the actual deployed host, process, source roots and effective config.
2. Capture immutable audio/request manifests for identical text repeated
   sequentially, different Chinese answers using the same speaker, and a
   contrasting built-in speaker.
3. Compare Auto against Chinese, then an explicit fixed style separately.
   Change one factor at a time; retain original audio and sampling settings.
4. Evaluate audible speaker identity separately from pitch/rhythm/emotion;
   check PCM24k playback when pitch and speaking speed change together.
5. Only deploy a scoped correction after the listening/quality gate passes.

GPU validation uses env.sh followed by conda activate omni and process-local
current-source PYTHONPATH. No CPU regression prerequisite. New artifacts must
use exclusive timestamped directories, preserving earlier experiments.
