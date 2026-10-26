(function (root) {
  'use strict';
  const profiles = root.OmniRealtimeProfiles;
  profiles['mimo-tts'] = (config) => {
    const profile = profiles['qwen3-turn'](config);
    return {
      ...profile,
      title: 'MiMo + Qwen3-TTS',
      eyebrow: 'Voice conversation',
      policy: 'MiMo Semantic VAD',
      description: '',
      initialMessages(config, instructions) {
        const session = { model: config.model, overlap_policy: 'listen_only', audio: { input: {
          format: { type: 'audio/pcm', rate: 24000 },
          turn_detection: { type: 'semantic_vad', threshold: 0.5,
            prefix_padding_ms: 300, silence_duration_ms: 500,
            min_speech_duration_ms: 96 },
        } } };
        if (instructions) session.instructions = instructions;
        return [{ type: 'session.update', session }];
      },
      connectionHint: 'Check MiMo, Qwen3-TTS and the realtime service.',
    };
  };
})(globalThis);
