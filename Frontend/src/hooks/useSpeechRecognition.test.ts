import { renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { accumulateFinals, joinFinals, useSpeechRecognition } from "@/hooks/useSpeechRecognition";
import { MIC_ERROR_MESSAGES } from "@/lib/phrases";
import { resetStores } from "@/test/resetStores";
import { useSpeechStore } from "@/stores/speechStore";
import { useVoiceStore } from "@/stores/voiceStore";

class MockRecognition {
  static last: MockRecognition | null = null;
  lang = "";
  continuous = false;
  interimResults = false;
  maxAlternatives = 1;
  onresult: ((event: SpeechRecognitionEvent) => void) | null = null;
  onerror: ((event: SpeechRecognitionErrorEvent) => void) | null = null;
  onend: (() => void) | null = null;
  start = vi.fn();
  stop = vi.fn();
  abort = vi.fn();

  constructor() {
    MockRecognition.last = this;
  }
}

function resultEvent(results: Array<{ transcript: string; isFinal: boolean }>, resultIndex = 0) {
  return {
    resultIndex,
    results: results.map((item) => ({
      isFinal: item.isFinal,
      0: { transcript: item.transcript, confidence: 1 },
    })),
  } as unknown as SpeechRecognitionEvent;
}

describe("accumulateFinals", () => {
  it("keeps every final segment across two pauses, not only resultIndex", () => {
    let finals: string[] = [];
    finals = accumulateFinals(
      finals,
      resultEvent([
        { transcript: "Open Wikipedia", isFinal: true },
        { transcript: "and search", isFinal: true },
      ]),
    );
    finals = accumulateFinals(
      finals,
      resultEvent(
        [
          { transcript: "Open Wikipedia", isFinal: true },
          { transcript: "and search", isFinal: true },
          { transcript: "for Babar Azam", isFinal: true },
        ],
        2,
      ),
    );
    expect(joinFinals(finals)).toBe("Open Wikipedia and search for Babar Azam");
  });
});

describe("useSpeechRecognition", () => {
  const bargeIn = vi.fn();
  const speakAssertive = vi.fn();
  const sendVoiceCommand = vi.fn();

  beforeEach(() => {
    resetStores();
    bargeIn.mockReset();
    speakAssertive.mockReset();
    sendVoiceCommand.mockReset();
    vi.useFakeTimers();
    MockRecognition.last = null;
    Object.defineProperty(window, "SpeechRecognition", {
      configurable: true,
      value: MockRecognition,
    });
    Object.defineProperty(window, "AudioContext", {
      configurable: true,
      value: class {
        currentTime = 0;
        resume = vi.fn();
        createOscillator() {
          return {
            type: "sine",
            frequency: { value: 0 },
            connect: vi.fn(),
            start: vi.fn(),
            stop: vi.fn(),
          };
        }
        createGain() {
          return {
            gain: { setValueAtTime: vi.fn(), exponentialRampToValueAtTime: vi.fn() },
            connect: vi.fn(),
          };
        }
        destination = {};
      },
    });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  function renderRecognition() {
    return renderHook(() =>
      useSpeechRecognition({
        handlers: {
          sendVoiceCommand,
          repeatLast: vi.fn(),
          openHelp: vi.fn(),
        },
        bargeIn,
        speakAssertive,
      }),
    );
  }

  it("starts the recognizer immediately while the earcon plays in parallel", async () => {
    const { result } = renderRecognition();
    const pending = result.current.startListening();
    expect(useVoiceStore.getState().listening).toBe(true);
    expect(bargeIn).toHaveBeenCalled();
    expect(MockRecognition.last?.start).toHaveBeenCalled();
    expect(MockRecognition.last?.continuous).toBe(true);
    expect(MockRecognition.last?.lang).toBe("en-IN");
    await pending;
    expect(useSpeechStore.getState().politeLive).toBe("Listening");
  });

  it("speaks each recognition error assertively", () => {
    renderRecognition();
    const recognition = MockRecognition.last;
    expect(recognition).not.toBeNull();
    for (const [error, message] of Object.entries(MIC_ERROR_MESSAGES)) {
      recognition?.onerror?.({ error, message: "" } as SpeechRecognitionErrorEvent);
      expect(speakAssertive).toHaveBeenCalledWith(message);
    }
    recognition?.onerror?.({ error: "aborted", message: "" } as SpeechRecognitionErrorEvent);
    expect(speakAssertive).not.toHaveBeenCalledWith(expect.stringMatching(/aborted/i));
  });

  it("joins three final segments across two pauses and delivers once on end", async () => {
    const { result } = renderRecognition();
    await result.current.startListening();
    const recognition = MockRecognition.last;
    recognition?.onresult?.(
      resultEvent([{ transcript: "Open Wikipedia", isFinal: true }]),
    );
    recognition?.onresult?.(
      resultEvent(
        [
          { transcript: "Open Wikipedia", isFinal: true },
          { transcript: "and search", isFinal: true },
        ],
        1,
      ),
    );
    recognition?.onresult?.(
      resultEvent(
        [
          { transcript: "Open Wikipedia", isFinal: true },
          { transcript: "and search", isFinal: true },
          { transcript: "for Babar Azam", isFinal: true },
        ],
        2,
      ),
    );
    expect(sendVoiceCommand).not.toHaveBeenCalled();
    recognition?.onend?.();
    expect(sendVoiceCommand).toHaveBeenCalledTimes(1);
    expect(sendVoiceCommand).toHaveBeenCalledWith("Open Wikipedia and search for Babar Azam");
  });

  it("does not end press-mode capture after a 1s mid-sentence pause", async () => {
    const { result } = renderRecognition();
    await result.current.startListening();
    MockRecognition.last?.onresult?.(resultEvent([{ transcript: "Open Wikipedia", isFinal: true }]));
    await vi.advanceTimersByTimeAsync(1000);
    expect(MockRecognition.last?.stop).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(900);
    expect(MockRecognition.last?.stop).toHaveBeenCalled();
  });

  it("stopListening calls stop not abort", async () => {
    const { result } = renderRecognition();
    await result.current.startListening();
    result.current.stopListening();
    expect(MockRecognition.last?.stop).toHaveBeenCalled();
    expect(MockRecognition.last?.abort).not.toHaveBeenCalled();
  });
});
