(function () {
  "use strict";

  const synth = window.speechSynthesis;
  let cachedVoices = [];

  function refresh() {
    cachedVoices = synth ? synth.getVoices() : [];
    return cachedVoices;
  }

  if (synth) {
    refresh();
    if (typeof synth.onvoiceschanged !== "undefined") {
      synth.onvoiceschanged = refresh;
    }
  }

  function pickVoice(coach) {
    const all = cachedVoices.length ? cachedVoices : refresh();
    if (!all.length) return null;
    const russian = all.filter((voice) => (voice.lang || "").toLowerCase().startsWith("ru"));
    const pool = russian.length ? russian : all;
    const gender = coach && coach.gender === "female"
      ? /(female|woman|irina|svetlana|anna|maria|elena|alena|milena|google)/i
      : /(male|man|yuri|dmitry|dmitri|pavel|alexey|alexei|artem|maxim|ivan|lev)/i;
    const match = pool.find((voice) => gender.test(voice.name || ""));
    if (match) return match;
    const index = coach && Number.isFinite(Number(coach.voice_index))
      ? Number(coach.voice_index)
      : 0;
    return pool[index % pool.length];
  }

  function speak(text, coach) {
    if (!synth || typeof SpeechSynthesisUtterance === "undefined" || !text) return false;
    synth.cancel();
    const utterance = new SpeechSynthesisUtterance(String(text));
    const voice = pickVoice(coach);
    if (voice) utterance.voice = voice;
    utterance.lang = "ru-RU";
    utterance.pitch = coach && coach.pitch ? Number(coach.pitch) : 1;
    utterance.rate = coach && coach.rate ? Number(coach.rate) : 1;
    utterance.volume = 1;
    synth.speak(utterance);
    return true;
  }

  function stop() {
    if (synth) synth.cancel();
  }

  window.ChessVoice = {
    speak: speak,
    stop: stop,
    refresh: refresh,
    available: Boolean(synth)
  };
})();
