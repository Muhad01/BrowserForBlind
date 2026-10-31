import { describe, expect, it } from "vitest";

import { compactHeld } from "@/lib/speechGate";
import type { SpeechItem } from "@/lib/speechQueue";

function item(text: string, event: string, priority: "polite" | "assertive" = "polite"): SpeechItem {
  return { text, event, priority };
}

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
