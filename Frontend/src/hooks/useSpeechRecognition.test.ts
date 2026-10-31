import { renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

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
  const cancelSpeech = vi.fn();
  const speakAssertive = vi.fn();
  const sendVoiceCommand = vi.fn();

  beforeEach(() => {
    resetStores();
    cancelSpeech.mockReset();
    speakAssertive.mockReset();
    sendVoiceCommand.mockReset();
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

  function renderRecognition() {
    return renderHook(() =>
      useSpeechRecognition({
        handlers: {
          sendVoiceCommand,
          repeatLast: vi.fn(),
          openHelp: vi.fn(),
        },
        cancelSpeech,
        speakAssertive,
      }),
    );
  }

  it("cancels speech before starting the microphone", () => {
    const { result } = renderRecognition();
    result.current.startListening();
    expect(cancelSpeech).toHaveBeenCalled();
    expect(MockRecognition.last?.start).toHaveBeenCalled();
    expect(useVoiceStore.getState().listening).toBe(true);
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
