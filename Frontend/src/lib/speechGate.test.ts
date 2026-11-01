import { describe, expect, it } from "vitest";

import {
  compactHeld,
  dueForHeartbeat,
  markHeartbeatSpoken,
  nextHeartbeatDelayMs,
  resetHeartbeatState,
} from "@/lib/speechGate";
import type { SpeechItem } from "@/lib/speechQueue";

function item(text: string, event: string, priority: "polite" | "assertive" = "polite"): SpeechItem {
  return { text, event, priority };
}

describe("nextHeartbeatDelayMs", () => {
  it("backs off 12s, then 30s, then 45s with a 30s floor after the first", () => {
    expect(nextHeartbeatDelayMs(0)).toBe(12_000);
    expect(nextHeartbeatDelayMs(1)).toBe(30_000);
    expect(nextHeartbeatDelayMs(2)).toBe(45_000);
    expect(nextHeartbeatDelayMs(5)).toBe(45_000);
  });
});

describe("dueForHeartbeat", () => {
  it("fires at 12s, then not until 30s, then every 45s", () => {
    resetHeartbeatState();
    const spokenAt = 1_000_000;
    expect(dueForHeartbeat(spokenAt + 11_000, spokenAt)).toBe(false);
    expect(dueForHeartbeat(spokenAt + 12_000, spokenAt)).toBe(true);
    markHeartbeatSpoken(spokenAt + 12_000);
    expect(dueForHeartbeat(spokenAt + 12_000 + 29_000, spokenAt + 12_000)).toBe(false);
    expect(dueForHeartbeat(spokenAt + 12_000 + 30_000, spokenAt + 12_000)).toBe(true);
    markHeartbeatSpoken(spokenAt + 42_000);
    expect(dueForHeartbeat(spokenAt + 42_000 + 44_000, spokenAt + 42_000)).toBe(false);
    expect(dueForHeartbeat(spokenAt + 42_000 + 45_000, spokenAt + 42_000)).toBe(true);
  });
});

describe("compactHeld", () => {
  it("keeps only the latest progress item plus completions", () => {
    const held = [
      item("A1", "browser_action"),
      item("A2", "browser_action"),
      item("A3", "browser_action"),
      item("A4", "browser_action"),
      item("A5", "browser_action"),
      item("Done.", "task_completed", "assertive"),
    ];
    expect(compactHeld(held, "brief").map((entry) => entry.text)).toEqual(["Done."]);
    expect(compactHeld(held, "detailed").map((entry) => entry.text)).toEqual(["A5", "Done."]);
  });

  it("keeps task lifecycle and local messages in arrival order", () => {
    const held = [
      item("Working on it.", "task_started"),
      item("Click", "browser_action"),
      item("Looking", "perception_result", "assertive"),
      item("Help", "local", "assertive"),
    ];
    expect(compactHeld(held, "brief").map((entry) => entry.event)).toEqual([
      "task_started",
      "perception_result",
      "local",
    ]);
  });
});
