/**
 * AmbientManager — procedural background soundscapes via Web Audio API.
 * Ported from the reader project's useAmbient hook (no audio files needed).
 *
 * Tracks: none | rain | forest | beach | cafe
 * Auto-ducks to DUCK_VOLUME when TTS is speaking.
 */

const DUCK_VOLUME = 0.12;
const LS_TRACK  = "wactorz.ambientTrack";
const LS_VOLUME = "wactorz.ambientVolume";

export type AmbientTrackId = "none" | "rain" | "forest" | "beach" | "cafe";

export const AMBIENT_TRACKS: { id: AmbientTrackId; label: string }[] = [
  { id: "none",   label: "Off"    },
  { id: "rain",   label: "🌧 Rain"  },
  { id: "forest", label: "🌲 Forest" },
  { id: "beach",  label: "🌊 Beach"  },
  { id: "cafe",   label: "☕ Cafe"   },
];

type Stopper = () => void;

// ── Noise generators ──────────────────────────────────────────────────────────

function makeWhiteNoise(ctx: AudioContext): AudioBufferSourceNode {
  const len = ctx.sampleRate * 2;
  const buf = ctx.createBuffer(1, len, ctx.sampleRate);
  const d = buf.getChannelData(0);
  for (let i = 0; i < len; i++) d[i] = Math.random() * 2 - 1;
  const src = ctx.createBufferSource();
  src.buffer = buf; src.loop = true;
  return src;
}

function makePinkNoise(ctx: AudioContext): AudioBufferSourceNode {
  const len = ctx.sampleRate * 2;
  const buf = ctx.createBuffer(1, len, ctx.sampleRate);
  const d = buf.getChannelData(0);
  let b0=0,b1=0,b2=0,b3=0,b4=0,b5=0,b6=0;
  for (let i = 0; i < len; i++) {
    const w = Math.random() * 2 - 1;
    b0=0.99886*b0+w*0.0555179; b1=0.99332*b1+w*0.0750759;
    b2=0.96900*b2+w*0.1538520; b3=0.86650*b3+w*0.3104856;
    b4=0.55000*b4+w*0.5329522; b5=-0.7616*b5-w*0.0168980;
    d[i]=(b0+b1+b2+b3+b4+b5+b6+w*0.5362)*0.11; b6=w*0.115926;
  }
  const src = ctx.createBufferSource();
  src.buffer = buf; src.loop = true;
  return src;
}

function makeBrownNoise(ctx: AudioContext): AudioBufferSourceNode {
  const len = ctx.sampleRate * 2;
  const buf = ctx.createBuffer(1, len, ctx.sampleRate);
  const d = buf.getChannelData(0);
  let last = 0;
  for (let i = 0; i < len; i++) {
    last = (last + 0.02 * (Math.random() * 2 - 1)) / 1.02;
    d[i] = last * 3.5;
  }
  const src = ctx.createBufferSource();
  src.buffer = buf; src.loop = true;
  return src;
}

function lfoMod(ctx: AudioContext, param: AudioParam, min: number, max: number, periodSec: number): Stopper {
  const mid = (min + max) / 2, depth = (max - min) / 2;
  param.value = mid;
  const osc = ctx.createOscillator();
  osc.type = "sine"; osc.frequency.value = 1 / periodSec;
  const g = ctx.createGain(); g.gain.value = depth;
  osc.connect(g); g.connect(param); osc.start();
  return () => { try { osc.stop(); } catch {} };
}

// ── Track builders ────────────────────────────────────────────────────────────

function buildRain(ctx: AudioContext, out: GainNode): Stopper {
  const noise = makeWhiteNoise(ctx);
  const hp = ctx.createBiquadFilter(); hp.type="highpass"; hp.frequency.value=400; hp.Q.value=0.5;
  const shape = ctx.createBiquadFilter(); shape.type="peaking"; shape.frequency.value=1400; shape.gain.value=6; shape.Q.value=1;
  const env = ctx.createGain();
  const stopLfo = lfoMod(ctx, env.gain, 0.55, 1.0, 4.5);
  noise.connect(hp); hp.connect(shape); shape.connect(env); env.connect(out);
  noise.start();
  return () => { stopLfo(); noise.stop(); };
}

function buildForest(ctx: AudioContext, out: GainNode): Stopper {
  const wind = makePinkNoise(ctx);
  const windLp = ctx.createBiquadFilter(); windLp.type="lowpass"; windLp.frequency.value=700; windLp.Q.value=0.3;
  const windGain = ctx.createGain();
  const stopWind = lfoMod(ctx, windGain.gain, 0.2, 0.7, 8);
  wind.connect(windLp); windLp.connect(windGain); windGain.connect(out); wind.start();

  const leaves = makeWhiteNoise(ctx);
  const leafBp = ctx.createBiquadFilter(); leafBp.type="bandpass"; leafBp.frequency.value=3500; leafBp.Q.value=2;
  const leafGain = ctx.createGain();
  const stopLeaf = lfoMod(ctx, leafGain.gain, 0.04, 0.18, 3.2);
  leaves.connect(leafBp); leafBp.connect(leafGain); leafGain.connect(out); leaves.start();

  return () => { stopWind(); stopLeaf(); wind.stop(); leaves.stop(); };
}

function buildBeach(ctx: AudioContext, out: GainNode): Stopper {
  const wave = makeBrownNoise(ctx);
  const waveLp = ctx.createBiquadFilter(); waveLp.type="lowpass"; waveLp.frequency.value=550; waveLp.Q.value=0.4;
  const waveGain = ctx.createGain();
  const stopWave = lfoMod(ctx, waveGain.gain, 0.08, 0.85, 7);
  wave.connect(waveLp); waveLp.connect(waveGain); waveGain.connect(out); wave.start();

  const breeze = makePinkNoise(ctx);
  const breezeHp = ctx.createBiquadFilter(); breezeHp.type="highpass"; breezeHp.frequency.value=1200;
  const breezeGain = ctx.createGain(); breezeGain.gain.value=0.15;
  breeze.connect(breezeHp); breezeHp.connect(breezeGain); breezeGain.connect(out); breeze.start();

  return () => { stopWave(); wave.stop(); breeze.stop(); };
}

function buildCafe(ctx: AudioContext, out: GainNode): Stopper {
  const rumble = makeBrownNoise(ctx);
  const rumbleLp = ctx.createBiquadFilter(); rumbleLp.type="lowpass"; rumbleLp.frequency.value=280;
  const rumbleGain = ctx.createGain(); rumbleGain.gain.value=0.3;
  rumble.connect(rumbleLp); rumbleLp.connect(rumbleGain); rumbleGain.connect(out); rumble.start();

  const chat = makePinkNoise(ctx);
  const chatBp = ctx.createBiquadFilter(); chatBp.type="bandpass"; chatBp.frequency.value=1000; chatBp.Q.value=1.2;
  const chatGain = ctx.createGain();
  const stopChat = lfoMod(ctx, chatGain.gain, 0.15, 0.5, 5.5);
  chat.connect(chatBp); chatBp.connect(chatGain); chatGain.connect(out); chat.start();

  return () => { stopChat(); rumble.stop(); chat.stop(); };
}

// ── Manager class ─────────────────────────────────────────────────────────────

export class AmbientManager {
  private _track: AmbientTrackId;
  private _volume: number;
  private _ducked = false;
  private _ctx: AudioContext | null = null;
  private _master: GainNode | null = null;
  private _stop: Stopper | null = null;

  constructor() {
    this._track  = (localStorage.getItem(LS_TRACK)  as AmbientTrackId) ?? "none";
    this._volume = parseFloat(localStorage.getItem(LS_VOLUME) ?? "0.4");
  }

  get track():  AmbientTrackId { return this._track; }
  get volume(): number         { return this._volume; }

  setTrack(id: AmbientTrackId): void {
    this._track = id;
    localStorage.setItem(LS_TRACK, id);
    this._restart();
  }

  setVolume(v: number): void {
    this._volume = Math.max(0, Math.min(1, v));
    localStorage.setItem(LS_VOLUME, String(this._volume));
    this._applyVolume();
  }

  duck(on: boolean): void {
    this._ducked = on;
    this._applyVolume();
  }

  destroy(): void {
    this._stopCurrent();
    this._ctx?.close().catch(() => {});
    this._ctx = null;
  }

  // ── Private ────────────────────────────────────────────────────────────────

  private _ensureCtx(): { ctx: AudioContext; master: GainNode } {
    if (!this._ctx) {
      this._ctx = new AudioContext();
      this._master = this._ctx.createGain();
      this._master.connect(this._ctx.destination);
    }
    if (this._ctx.state === "suspended") this._ctx.resume().catch(() => {});
    return { ctx: this._ctx, master: this._master! };
  }

  private _stopCurrent(): void {
    if (this._stop) { try { this._stop(); } catch {} this._stop = null; }
  }

  private _restart(): void {
    this._stopCurrent();
    if (this._track === "none") return;
    const { ctx, master } = this._ensureCtx();
    this._applyVolume();
    switch (this._track) {
      case "rain":   this._stop = buildRain(ctx, master);   break;
      case "forest": this._stop = buildForest(ctx, master); break;
      case "beach":  this._stop = buildBeach(ctx, master);  break;
      case "cafe":   this._stop = buildCafe(ctx, master);   break;
    }
  }

  private _applyVolume(): void {
    if (this._master) {
      this._master.gain.value = this._ducked
        ? DUCK_VOLUME * this._volume
        : this._volume;
    }
  }
}

export const ambient = new AmbientManager();
