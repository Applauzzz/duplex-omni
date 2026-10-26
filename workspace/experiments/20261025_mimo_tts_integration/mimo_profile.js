(function (root) {
  'use strict';
  const profiles = root.OmniRealtimeProfiles;
  profiles['mimo-tts'] = (config) => {
    const profile = profiles['qwen3-turn'](config);
    return {
      ...profile,
      title: 'MiMo + Qwen3-TTS',
      eyebrow: 'Voice conversation',
      policy: 'Server VAD',
      description: '',
      connectionHint: 'Check MiMo, Qwen3-TTS and the realtime service.',
    };
  };
})(globalThis);
