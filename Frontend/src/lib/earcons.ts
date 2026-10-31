/** Tiny WebAudio tones: listen start, listen stop, error. FR-04 */

let audioContext: AudioContext | null = null;

export function unlockAudio(): void {
  try {
    const ctx = getAudioContext();
    void ctx.resume();
  } catch {
    // Audio unlock is best-effort; speechSynthesis is unlocked separately.
  }
}

function getAudioContext(): AudioContext {
  if (!audioContext) {
    const Ctor = window.AudioContext || (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!Ctor) {
      throw new Error("Web Audio is not available");
    }
    audioContext = new Ctor();
  }
  return audioContext;
}

function playTone(frequency: number, durationSeconds: number): void {
  try {
    const ctx = getAudioContext();
    const oscillator = ctx.createOscillator();
    const gain = ctx.createGain();
    oscillator.type = "sine";
    oscillator.frequency.value = frequency;
    gain.gain.setValueAtTime(0.07, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + durationSeconds);
    oscillator.connect(gain);
    gain.connect(ctx.destination);
    oscillator.start();
    oscillator.stop(ctx.currentTime + durationSeconds);
  } catch {
    // Earcons must never break the voice path.
  }
}

export function playListenStart(delayMs = 150): Promise<void> {
  playTone(880, 0.12);
  return new Promise((resolve) => {
    setTimeout(resolve, delayMs);
  });
}

export function playListenStop(): void {
  playTone(660, 0.1);
}

export function playErrorEarcon(): void {
  playTone(220, 0.22);
}
