import { renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useSpeechSynthesis } from "@/hooks/useSpeechSynthesis";
import { resetStores } from "@/test/resetStores";
import { useSpeechStore } from "@/stores/speechStore";
import { useTaskStore } from "@/stores/taskStore";
import { useVoiceStore } from "@/stores/voiceStore";

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

  afterEach(() => {
    vi.useRealTimers();
  });

  function spokenTexts(): string[] {
    return speakMock.mock.calls.map((call) => (call[0] as MockUtterance).text);
  }

  it("does not call speechSynthesis.speak in screenreader mode but updates live regions", () => {
    useSpeechStore.getState().setSettings({ outputMode: "screenreader" });
    const { result } = renderHook(() => useSpeechSynthesis());
    result.current.speak("Starting: search", { priority: "polite", event: "task_started" });
    expect(speakMock).not.toHaveBeenCalled();
    expect(useSpeechStore.getState().politeLive).toBe("Starting: search");
    expect(useSpeechStore.getState().lastSpoken).toBe("Starting: search");
  });

  it("uses speechSynthesis in voice mode", () => {
    useSpeechStore.getState().setSettings({ verbosity: "detailed" });
    const { result } = renderHook(() => useSpeechSynthesis());
    result.current.speak("Opening wikipedia.org", { priority: "polite", event: "browser_action" });
    expect(speakMock).toHaveBeenCalledOnce();
    expect(useSpeechStore.getState().politeLive).toBe("Opening wikipedia.org");
  });

  it("never calls speechSynthesis.speak while listening and flushes compacted held items", async () => {
    vi.useFakeTimers();
    useVoiceStore.setState({ listening: true });
    const brief = renderHook(() => useSpeechSynthesis());
    for (let i = 1; i <= 5; i += 1) {
      brief.result.current.speak(`Action ${i}`, { event: "browser_action" });
    }
    brief.result.current.speak("Done.", { priority: "assertive", event: "task_completed" });
    expect(speakMock).not.toHaveBeenCalled();
    expect(useSpeechStore.getState().assertiveLive).toBe("Done.");

    useVoiceStore.setState({ listening: false });
    await vi.advanceTimersByTimeAsync(400);
    expect(spokenTexts()).toEqual(["Done."]);
    brief.unmount();

    resetStores();
    speakMock.mockReset();
    useSpeechStore.getState().setSettings({ verbosity: "detailed" });
    useVoiceStore.setState({ listening: true });
    const detailed = renderHook(() => useSpeechSynthesis());
    for (let i = 1; i <= 5; i += 1) {
      detailed.result.current.speak(`Action ${i}`, { event: "browser_action" });
    }
    detailed.result.current.speak("Done.", { priority: "assertive", event: "task_completed" });
    expect(speakMock).not.toHaveBeenCalled();
    useVoiceStore.setState({ listening: false });
    await vi.advanceTimersByTimeAsync(400);
    expect(spokenTexts()).toEqual(["Action 5", "Done."]);
  });

  it("does not start the next item when onend fires while gated", () => {
    useSpeechStore.getState().setSettings({ verbosity: "detailed" });
    const { result } = renderHook(() => useSpeechSynthesis());
    result.current.speak("First", { event: "browser_action" });
    result.current.speak("Second", { event: "browser_action" });
    expect(spokenTexts()).toEqual(["First"]);
    useVoiceStore.setState({ listening: true });
    const utterance = speakMock.mock.calls[0][0] as MockUtterance;
    utterance.onend?.();
    expect(spokenTexts()).toEqual(["First"]);
  });

  it("speaks a brief-mode heartbeat after 12s of silence but not while gated", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(1_000_000);
    useTaskStore.setState({
      task: {
        id: "t1",
        goal: "search",
        mode: "task",
        status: "running",
        result_text: null,
        error_code: null,
        error_message: null,
        final_url: null,
        step_count: 1,
        created_at: null,
        finished_at: null,
        pending_confirmation: null,
      },
    });
    useSpeechStore.setState({ lastSpokenAt: 1_000_000 });
    useVoiceStore.setState({ listening: true });
    renderHook(() => useSpeechSynthesis());
    await vi.advanceTimersByTimeAsync(13_000);
    expect(speakMock).not.toHaveBeenCalled();

    useVoiceStore.setState({ listening: false });
    useSpeechStore.setState({ lastSpokenAt: Date.now() - 13_000 });
    await vi.advanceTimersByTimeAsync(1000);
    expect(spokenTexts()).toEqual(["Still working."]);
  });
});
