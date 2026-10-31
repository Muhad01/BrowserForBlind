import { renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useSpeechRecognition } from "@/hooks/useSpeechRecognition";
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

  it("closes the gate and barges in before starting the microphone", async () => {
    const { result } = renderRecognition();
    const pending = result.current.startListening();
    expect(useVoiceStore.getState().listening).toBe(true);
    expect(bargeIn).toHaveBeenCalled();
    expect(MockRecognition.last?.start).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(150);
    await pending;
    expect(MockRecognition.last?.start).toHaveBeenCalled();
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

  it("uses continuous recognition in hold mode and joins finals on end", async () => {
    useSpeechStore.getState().setSettings({ talkMode: "hold" });
    const { result } = renderRecognition();
    const pending = result.current.startListening();
    await vi.advanceTimersByTimeAsync(150);
    await pending;
    expect(MockRecognition.last?.continuous).toBe(true);
    MockRecognition.last?.onresult?.({
      resultIndex: 0,
      results: [{ isFinal: true, 0: { transcript: "Search Wikipedia", confidence: 1 } }],
    } as unknown as SpeechRecognitionEvent);
    MockRecognition.last?.onresult?.({
      resultIndex: 0,
      results: [{ isFinal: true, 0: { transcript: "for cats", confidence: 1 } }],
    } as unknown as SpeechRecognitionEvent);
    expect(sendVoiceCommand).not.toHaveBeenCalled();
    MockRecognition.last?.onend?.();
    expect(sendVoiceCommand).toHaveBeenCalledWith("Search Wikipedia for cats");
  });

  it("stopListening calls stop not abort", async () => {
    const { result } = renderRecognition();
    const pending = result.current.startListening();
    await vi.advanceTimersByTimeAsync(150);
    await pending;
    result.current.stopListening();
    expect(MockRecognition.last?.stop).toHaveBeenCalled();
    expect(MockRecognition.last?.abort).not.toHaveBeenCalled();
  });

  it("sends a final transcript as a voice command", () => {
    renderRecognition();
    MockRecognition.last?.onresult?.({
      resultIndex: 0,
      results: [
        {
          isFinal: true,
          0: { transcript: "Search Wikipedia for cats", confidence: 1 },
        },
      ],
    } as unknown as SpeechRecognitionEvent);
    expect(sendVoiceCommand).toHaveBeenCalledWith("Search Wikipedia for cats");
  });
});
