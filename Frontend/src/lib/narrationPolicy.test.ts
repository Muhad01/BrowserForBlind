import { beforeEach, describe, expect, it } from "vitest";

import { decideNarration, resetNarrationPolicy } from "@/lib/narrationPolicy";
import type { ServerFrame } from "@/lib/events";
import { resetStores } from "@/test/resetStores";
import { useSpeechStore } from "@/stores/speechStore";

function frame(event: string, speak: string, extra: Partial<ServerFrame> = {}): ServerFrame {
  return {
    event,
    task_id: "t1",
    request_id: extra.request_id ?? null,
    payload: { speak, ...(extra.payload ?? {}) },
  };
}

describe("decideNarration", () => {
  beforeEach(() => {
    resetStores();
    resetNarrationPolicy();
  });

  it("speaks Working on it. for task_started in brief mode", () => {
    const decision = decideNarration(frame("task_started", "Starting: search Wikipedia", { payload: { brief: "Working on it." } }));
    expect(decision.speakText).toBe("Working on it.");
    expect(decision.liveText).toBe("Starting: search Wikipedia");
  });

  it("does not speak browser_action in brief mode", () => {
    const decision = decideNarration(frame("browser_action", "Opening wikipedia.org"));
    expect(decision.speakText).toBeNull();
    expect(decision.liveText).toBe("Opening wikipedia.org");
  });

  it("throttles agent_status to one every 6 seconds in brief mode", () => {
    const first = decideNarration(frame("agent_status", "Now on: Wikipedia"), { now: 1000 });
    const second = decideNarration(frame("agent_status", "Now on: Google"), { now: 2000 });
    const later = decideNarration(frame("agent_status", "Now on: Example"), { now: 8000 });
    expect(first.speakText).toBe("Now on: Wikipedia");
    expect(second.speakText).toBeNull();
    expect(later.speakText).toBe("Now on: Example");
  });

  it("always speaks a stop reply agent_status that has a request_id", () => {
    decideNarration(frame("agent_status", "Now on: Wikipedia"), { now: 1000 });
    const stop = decideNarration(frame("agent_status", "Stopping.", { request_id: "req-1" }), { now: 1500 });
    expect(stop.speakText).toBe("Stopping.");
  });

  it("speaks the full payload in detailed mode", () => {
    useSpeechStore.getState().setSettings({ verbosity: "detailed" });
    expect(decideNarration(frame("task_started", "Starting: search")).speakText).toBe("Starting: search");
    expect(decideNarration(frame("browser_action", "Opening wikipedia.org")).speakText).toBe(
      "Opening wikipedia.org",
    );
  });
});
