import { describe, expect, it } from "vitest";

import { SpeechQueue } from "@/lib/speechQueue";

describe("SpeechQueue", () => {
  it("speaks polite messages in order", () => {
    const queue = new SpeechQueue();
    const first = queue.enqueue({ text: "Starting", event: "task_started", priority: "polite" });
    expect(first.next?.text).toBe("Starting");
    queue.enqueue({ text: "Opening", event: "browser_action", priority: "polite" });
    queue.enqueue({ text: "Now on", event: "agent_status", priority: "polite" });
    expect(queue.shiftNext()?.text).toBe("Opening");
    expect(queue.shiftNext()?.text).toBe("Now on");
  });

  it("lets assertive speech interrupt and clear the polite queue", () => {
    const queue = new SpeechQueue();
    queue.enqueue({ text: "Starting", event: "task_started", priority: "polite" });
    queue.enqueue({ text: "Opening", event: "browser_action", priority: "polite" });
    const result = queue.enqueue({ text: "Done.", event: "task_completed", priority: "assertive" });
    expect(result.cancelCurrent).toBe(true);
    expect(result.next?.text).toBe("Done.");
    expect(queue.polite).toHaveLength(0);
  });

  it("drops the oldest browser_action when 3+ polite messages are queued", () => {
    const queue = new SpeechQueue();
    queue.enqueue({ text: "Starting", event: "task_started", priority: "polite" });
    queue.enqueue({ text: "Click one", event: "browser_action", priority: "polite" });
    queue.enqueue({ text: "Click two", event: "browser_action", priority: "polite" });
    const overflow = queue.enqueue({ text: "Click three", event: "browser_action", priority: "polite" });
    expect(overflow.dropped.map((item) => item.text)).toEqual(["Click one"]);
    expect(queue.polite.map((item) => item.text)).toEqual(["Click two", "Click three"]);
    expect(queue.current?.text).toBe("Starting");
  });

  it("never drops task_started", () => {
    const queue = new SpeechQueue();
    queue.enqueue({ text: "Starting", event: "task_started", priority: "polite" });
    queue.enqueue({ text: "Status", event: "agent_status", priority: "polite" });
    queue.enqueue({ text: "Looking", event: "perception_result", priority: "polite" });
    expect(queue.current?.event).toBe("task_started");
    expect(queue.polite.map((item) => item.event)).toEqual(["agent_status", "perception_result"]);
  });
});
