"use strict";

const focusAudio = (() => {
  let context, rain;
  async function play() {
    context ||= new AudioContext();
    await context.resume();
    if (context.state !== "running") throw new Error("请点击播放雨声，让浏览器开始播放。");
    if (rain) return;
    const buffer = context.createBuffer(1, context.sampleRate * 4, context.sampleRate);
    const samples = buffer.getChannelData(0);
    for (let i = 0; i < samples.length; i++) samples[i] = Math.random() * 2 - 1;
    const source = context.createBufferSource(), filter = context.createBiquadFilter(), gain = context.createGain();
    source.buffer = buffer; source.loop = true;
    filter.type = "lowpass"; filter.frequency.value = 850;
    gain.gain.value = .035;
    source.connect(filter); filter.connect(gain); gain.connect(context.destination);
    source.start(); rain = source;
  }
  function stop() { if (rain) { rain.stop(); rain.disconnect(); rain = null; } }
  return { play, stop, playing: () => Boolean(rain && context?.state === "running") };
})();
