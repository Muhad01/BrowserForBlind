import { renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useSpeechSynthesis } from "@/hooks/useSpeechSynthesis";
import { resetStores } from "@/test/resetStores";
import { useSpeechStore } from "@/stores/speechStore";

class MockUtterance {
  text: string;
  rate = 1;
  voice: SpeechSynthesisVoice | null = null;
  onend: (() => void) | null = null;
  onerror: (() => void) | null = null;
  constructor(text: string) {
    this.text = text;
  }
}

describe("useSpeechSynthesis", () => {
  const speakMock = vi.fn();
  const cancelMock = vi.fn();

  beforeEach(() => {
    resetStores();
    speakMock.mockReset();
    cancelMock.mockReset();
    Object.defineProperty(window, "speechSynthesis", {
      configurable: true,
      value: {
        speak: speakMock,
        cancel: cancelMock,
        getVoices: () => [],
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
      },
    });
    Object.defineProperty(window, "SpeechSynthesisUtterance", {
      configurable: true,
      value: MockUtterance,
    });
  });

  it("does not call speechSynthesis.speak in screenreader mode but updates live regions", () => {
    useSpeechStore.getState().setSettings({ outputMode: "screenreader" });
    const { result } = renderHook(() => useSpeechSynthesis());
    result.current.speak("Starting: search", { priority: "polite", event: "task_started" });
    expect(speakMock).not.toHaveBeenCalled();
    expect(useSpeechStore.getState().politeLive).toBe("Starting: search");
    expect(useSpeechStore.getState().lastSpoken).toBe("Starting: search");
  });

  it("uses speechSynthesis in voice mode", () => {
    const { result } = renderHook(() => useSpeechSynthesis());
    result.current.speak("Opening wikipedia.org", { priority: "polite", event: "browser_action" });
    expect(speakMock).toHaveBeenCalledOnce();
    expect(useSpeechStore.getState().politeLive).toBe("Opening wikipedia.org");
  });
});
