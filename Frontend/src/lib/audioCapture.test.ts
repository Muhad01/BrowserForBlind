import { describe, expect, it } from "vitest";

import {
  CaptureEngine,
  calibrateNoiseFloor,
  downsampleTo16k,
  encodeWavPcm16,
  isSpeechFrame,
  parseWavHeader,
  pcmFromWav,
  rms,
  silenceFrame,
  TARGET_SAMPLE_RATE,
  toneFrame,
} from "@/lib/audioCapture";

function pushMs(
  engine: CaptureEngine,
  frame: Float32Array,
  fromMs: number,
  durationMs: number,
): ReturnType<CaptureEngine["push"]> | undefined {
  let last;
  for (let t = fromMs; t < fromMs + durationMs; t += 20) {
    last = engine.push(frame, TARGET_SAMPLE_RATE, t);
  }
  return last;
}

describe("WAV encoder and downsample", () => {
  it("writes a mono 16 kHz 16-bit PCM header", () => {
    const wav = encodeWavPcm16(new Float32Array([0.5, -0.5, 0]), TARGET_SAMPLE_RATE);
    const header = parseWavHeader(wav);
    expect(header.channels).toBe(1);
    expect(header.sampleRate).toBe(16_000);
    expect(header.bitsPerSample).toBe(16);
    expect(header.dataBytes).toBe(6);
    expect(new TextDecoder().decode(new Uint8Array(wav, 0, 4))).toBe("RIFF");
  });

  it("downsamples 48 kHz by averaging groups of three", () => {
    const src = new Float32Array([0.3, 0.6, 0.9, 0.1, 0.2, 0.3]);
    const out = downsampleTo16k(src, 48_000);
    expect(out.length).toBe(2);
    expect(out[0]).toBeCloseTo(0.6);
    expect(out[1]).toBeCloseTo(0.2);
  });
});

describe("VAD noise floor", () => {
  it("calibrates from quiet pre-roll and detects louder speech", () => {
    const quiet = silenceFrame(8000);
    for (let i = 0; i < quiet.length; i += 1) {
      quiet[i] = 0.002;
    }
    const floor = calibrateNoiseFloor(quiet);
    expect(floor).toBeGreaterThan(0.008);
    expect(isSpeechFrame(0.009, floor)).toBe(false);
    expect(isSpeechFrame(0.2, floor)).toBe(true);
  });
});

describe("CaptureEngine cut-off regressions", () => {
  it("keeps words that started 200 ms before keydown (pre-roll)", () => {
    const engine = new CaptureEngine();
    pushMs(engine, toneFrame(0.6), 0, 200);
    engine.start(200, "press");
    pushMs(engine, toneFrame(0.6), 340, 200);
    const pcm = pcmFromWav(engine.flushWav());
    expect(rms(pcm.slice(0, 3_200))).toBeGreaterThan(0.2);
  });

  it("does not end press-mode capture after a 1.0 s mid-sentence pause", () => {
    const engine = new CaptureEngine();
    engine.start(0, "press");
    const afterSpeech = pushMs(engine, toneFrame(0.7), 120, 400);
    expect(afterSpeech?.ended).toBeUndefined();
    const afterPause = pushMs(engine, silenceFrame(), 520, 1000);
    expect(afterPause?.ended).toBeUndefined();
    const afterSilence = pushMs(engine, silenceFrame(), 1520, 900);
    expect(afterSilence?.ended).toBe("silence");
  });

  it("keeps a 300 ms tail after hold-mode keyup", () => {
    const engine = new CaptureEngine();
    engine.start(0, "hold");
    pushMs(engine, toneFrame(0.5), 120, 80);
    engine.requestStop(200);
    const mid = pushMs(engine, toneFrame(0.5), 200, 280);
    expect(mid?.ended).toBeUndefined();
    const end = engine.push(toneFrame(0.5), TARGET_SAMPLE_RATE, 500);
    expect(end.ended).toBe("stop");
    const pcm = pcmFromWav(engine.flushWav());
    expect(pcm.length).toBeGreaterThanOrEqual(TARGET_SAMPLE_RATE * 0.3);
  });
});
