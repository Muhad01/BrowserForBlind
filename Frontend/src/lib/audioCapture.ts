/** Warm-mic capture with pre-roll, VAD, and 16 kHz mono WAV encoding. */

export const TARGET_SAMPLE_RATE = 16_000;
export const PRE_ROLL_MS = 500;
export const EARCON_MUTE_MS = 120;
export const HOLD_TAIL_MS = 300;
export const PRESS_SILENCE_MS = 1_800;
export const MIN_SPEECH_MS = 400;
export const NO_SPEECH_MS = 7_000;
export const MAX_AUDIO_SECONDS = 20;
export const FRAME_MS = 20;

export type TalkMode = "press" | "hold";
export type CaptureEndReason = "silence" | "stop" | "max" | "no_speech" | "abort";

export function rms(samples: Float32Array): number {
  if (samples.length === 0) {
    return 0;
  }
  let sum = 0;
  for (let i = 0; i < samples.length; i += 1) {
    sum += samples[i] * samples[i];
  }
  return Math.sqrt(sum / samples.length);
}

export function calibrateNoiseFloor(samples: Float32Array): number {
  const floor = rms(samples);
  return Math.max(floor * 1.6, 0.008);
}

export function isSpeechFrame(frameRms: number, floor: number): boolean {
  return frameRms > floor * 1.8;
}

export function downsampleTo16k(samples: Float32Array, sourceRate: number): Float32Array {
  if (sourceRate === TARGET_SAMPLE_RATE) {
    return samples;
  }
  if (sourceRate <= 0 || samples.length === 0) {
    return new Float32Array(0);
  }
  const ratio = sourceRate / TARGET_SAMPLE_RATE;
  const outLen = Math.max(1, Math.floor(samples.length / ratio));
  const out = new Float32Array(outLen);
  for (let i = 0; i < outLen; i += 1) {
    const start = Math.floor(i * ratio);
    const end = Math.min(samples.length, Math.floor((i + 1) * ratio) || start + 1);
    let sum = 0;
    const count = Math.max(1, end - start);
    for (let j = start; j < end; j += 1) {
      sum += samples[j];
    }
    out[i] = sum / count;
  }
  return out;
}

export function encodeWavPcm16(samples: Float32Array, sampleRate = TARGET_SAMPLE_RATE): ArrayBuffer {
  const dataSize = samples.length * 2;
  const buffer = new ArrayBuffer(44 + dataSize);
  const view = new DataView(buffer);
  const writeString = (offset: number, text: string) => {
    for (let i = 0; i < text.length; i += 1) {
      view.setUint8(offset + i, text.charCodeAt(i));
    }
  };
  writeString(0, "RIFF");
  view.setUint32(4, 36 + dataSize, true);
  writeString(8, "WAVE");
  writeString(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  writeString(36, "data");
  view.setUint32(40, dataSize, true);
  let offset = 44;
  for (let i = 0; i < samples.length; i += 1) {
    const clipped = Math.max(-1, Math.min(1, samples[i]));
    view.setInt16(offset, clipped < 0 ? clipped * 0x8000 : clipped * 0x7fff, true);
    offset += 2;
  }
  return buffer;
}

export function parseWavHeader(buffer: ArrayBuffer): {
  channels: number;
  sampleRate: number;
  bitsPerSample: number;
  dataBytes: number;
} {
  const view = new DataView(buffer);
  return {
    channels: view.getUint16(22, true),
    sampleRate: view.getUint32(24, true),
    bitsPerSample: view.getUint16(34, true),
    dataBytes: view.getUint32(40, true),
  };
}

export function pcmFromWav(buffer: ArrayBuffer): Float32Array {
  const view = new DataView(buffer);
  const samples = new Float32Array((buffer.byteLength - 44) / 2);
  let offset = 44;
  for (let i = 0; i < samples.length; i += 1) {
    samples[i] = view.getInt16(offset, true) / 0x8000;
    offset += 2;
  }
  return samples;
}

export class RingBuffer {
  private readonly buffer: Float32Array;
  private writeIndex = 0;
  private filled = 0;

  constructor(capacitySamples: number) {
    this.buffer = new Float32Array(Math.max(1, capacitySamples));
  }

  write(samples: Float32Array): void {
    for (let i = 0; i < samples.length; i += 1) {
      this.buffer[this.writeIndex] = samples[i];
      this.writeIndex = (this.writeIndex + 1) % this.buffer.length;
      this.filled = Math.min(this.buffer.length, this.filled + 1);
    }
  }

  snapshot(): Float32Array {
    const out = new Float32Array(this.filled);
    const start = (this.writeIndex - this.filled + this.buffer.length) % this.buffer.length;
    for (let i = 0; i < this.filled; i += 1) {
      out[i] = this.buffer[(start + i) % this.buffer.length];
    }
    return out;
  }
}

export interface CaptureTick {
  level: number;
  ended?: CaptureEndReason;
}

export class CaptureEngine {
  private readonly preRoll: RingBuffer;
  private chunks: Float32Array[] = [];
  private capturing = false;
  private mutedUntil = 0;
  private startedAt = 0;
  private talkMode: TalkMode = "press";
  private noiseFloor = 0.01;
  private speechMs = 0;
  private silenceMs = 0;
  private stopAt: number | null = null;
  private sampleRate = TARGET_SAMPLE_RATE;

  constructor(preRollMs = PRE_ROLL_MS, sampleRate = TARGET_SAMPLE_RATE) {
    this.sampleRate = sampleRate;
    this.preRoll = new RingBuffer(Math.round((sampleRate * preRollMs) / 1000));
  }

  get isCapturing(): boolean {
    return this.capturing;
  }

  feedPreRoll(samples: Float32Array): void {
    if (!this.capturing) {
      this.preRoll.write(samples);
    }
  }

  start(nowMs: number, talkMode: TalkMode): void {
    this.talkMode = talkMode;
    this.capturing = true;
    this.startedAt = nowMs;
    this.mutedUntil = nowMs + EARCON_MUTE_MS;
    this.speechMs = 0;
    this.silenceMs = 0;
    this.stopAt = null;
    const pre = this.preRoll.snapshot();
    this.noiseFloor = calibrateNoiseFloor(pre);
    this.chunks = pre.length ? [pre] : [];
  }

  requestStop(nowMs: number): void {
    if (!this.capturing) {
      return;
    }
    if (this.talkMode === "hold") {
      this.stopAt = nowMs + HOLD_TAIL_MS;
      return;
    }
    this.stopAt = nowMs;
  }

  abort(): void {
    this.capturing = false;
    this.chunks = [];
    this.stopAt = null;
  }

  push(samples: Float32Array, sampleRate: number, nowMs: number): CaptureTick {
    const mono = downsampleTo16k(samples, sampleRate);
    const level = Math.min(1, rms(mono) * 4);
    if (!this.capturing) {
      this.preRoll.write(mono);
      return { level };
    }
    if (this.stopAt !== null && nowMs >= this.stopAt) {
      this.capturing = false;
      return { level, ended: "stop" };
    }
    if (nowMs - this.startedAt >= MAX_AUDIO_SECONDS * 1000) {
      this.capturing = false;
      return { level, ended: "max" };
    }
    if (nowMs < this.mutedUntil) {
      return { level };
    }
    this.chunks.push(mono);
    const frameMs = (mono.length / TARGET_SAMPLE_RATE) * 1000;
    const speaking = isSpeechFrame(rms(mono), this.noiseFloor);
    if (speaking) {
      this.speechMs += frameMs;
      this.silenceMs = 0;
    } else {
      this.silenceMs += frameMs;
    }
    if (this.talkMode === "press") {
      if (this.speechMs < 1 && nowMs - this.startedAt >= NO_SPEECH_MS) {
        this.capturing = false;
        return { level, ended: "no_speech" };
      }
      if (this.speechMs >= MIN_SPEECH_MS && this.silenceMs >= PRESS_SILENCE_MS) {
        this.capturing = false;
        return { level, ended: "silence" };
      }
    }
    return { level };
  }

  flushWav(): ArrayBuffer {
    const total = this.chunks.reduce((sum, chunk) => sum + chunk.length, 0);
    const merged = new Float32Array(total);
    let offset = 0;
    for (const chunk of this.chunks) {
      merged.set(chunk, offset);
      offset += chunk.length;
    }
    return encodeWavPcm16(merged, TARGET_SAMPLE_RATE);
  }
}

const WORKLET_SOURCE = `
class CightCaptureProcessor extends AudioWorkletProcessor {
  process(inputs) {
    const channel = inputs[0] && inputs[0][0];
    if (channel) {
      this.port.postMessage(channel);
    }
    return true;
  }
}
registerProcessor("cight-capture", CightCaptureProcessor);
`;

export interface AudioCaptureHandlers {
  onLevel: (level: number) => void;
  onEnded: (wav: ArrayBuffer, reason: CaptureEndReason) => void;
  onError: (code: string) => void;
}

export class AudioCapture {
  private engine = new CaptureEngine();
  private stream: MediaStream | null = null;
  private context: AudioContext | null = null;
  private source: MediaStreamAudioSourceNode | null = null;
  private worklet: AudioWorkletNode | null = null;
  private processor: ScriptProcessorNode | null = null;
  private warmed = false;
  private talkMode: TalkMode = "press";
  private visibilityHandler: (() => void) | null = null;

  constructor(private readonly handlers: AudioCaptureHandlers) {}

  async warm(): Promise<void> {
    if (this.stream) {
      return;
    }
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
          channelCount: 1,
        },
      });
      await this.attachGraph();
      this.warmed = true;
      this.watchVisibility();
    } catch {
      this.handlers.onError("not-allowed");
    }
  }

  start(talkMode: TalkMode): void {
    this.talkMode = talkMode;
    if (!this.stream) {
      void this.warm().then(() => {
        if (this.stream) {
          this.engine.start(performance.now(), talkMode);
        }
      });
      return;
    }
    this.engine.start(performance.now(), talkMode);
  }

  stop(): void {
    this.engine.requestStop(performance.now());
  }

  abort(): void {
    this.engine.abort();
  }

  release(): void {
    this.engine.abort();
    this.teardownGraph();
    this.stream?.getTracks().forEach((track) => track.stop());
    this.stream = null;
    this.warmed = false;
  }

  private watchVisibility(): void {
    if (this.visibilityHandler || typeof document === "undefined") {
      return;
    }
    this.visibilityHandler = () => {
      if (document.visibilityState === "hidden") {
        this.release();
        return;
      }
      if (this.warmed) {
        void this.warm();
      }
    };
    document.addEventListener("visibilitychange", this.visibilityHandler);
  }

  private async attachGraph(): Promise<void> {
    if (!this.stream) {
      return;
    }
    const Ctor = window.AudioContext || (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!Ctor) {
      this.handlers.onError("audio-capture");
      return;
    }
    this.context = new Ctor();
    this.source = this.context.createMediaStreamSource(this.stream);
    const handleFrame = (samples: Float32Array) => {
      const rate = this.context?.sampleRate ?? TARGET_SAMPLE_RATE;
      const tick = this.engine.push(samples, rate, performance.now());
      this.handlers.onLevel(tick.level);
      if (tick.ended) {
        this.handlers.onEnded(this.engine.flushWav(), tick.ended);
      }
    };
    try {
      const blob = new Blob([WORKLET_SOURCE], { type: "application/javascript" });
      const url = URL.createObjectURL(blob);
      await this.context.audioWorklet.addModule(url);
      URL.revokeObjectURL(url);
      this.worklet = new AudioWorkletNode(this.context, "cight-capture");
      this.worklet.port.onmessage = (event: MessageEvent<Float32Array>) => {
        handleFrame(event.data);
      };
      this.source.connect(this.worklet);
    } catch {
      this.processor = this.context.createScriptProcessor(1024, 1, 1);
      this.processor.onaudioprocess = (event) => {
        handleFrame(event.inputBuffer.getChannelData(0));
      };
      this.source.connect(this.processor);
      this.processor.connect(this.context.destination);
    }
  }

  private teardownGraph(): void {
    try {
      this.worklet?.disconnect();
      this.processor?.disconnect();
      this.source?.disconnect();
      void this.context?.close();
    } catch {
      // Graph teardown is best-effort.
    }
    this.worklet = null;
    this.processor = null;
    this.source = null;
    this.context = null;
  }
}

export function toneFrame(amplitude: number, samples = 320): Float32Array {
  const frame = new Float32Array(samples);
  for (let i = 0; i < samples; i += 1) {
    frame[i] = amplitude * Math.sin((2 * Math.PI * 440 * i) / TARGET_SAMPLE_RATE);
  }
  return frame;
}

export function silenceFrame(samples = 320): Float32Array {
  return new Float32Array(samples);
}
