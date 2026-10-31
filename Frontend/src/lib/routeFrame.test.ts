import { beforeEach, describe, expect, it, vi } from "vitest";

import { routeFrame } from "@/lib/routeFrame";
import { resetStores } from "@/test/resetStores";
import { useTaskStore } from "@/stores/taskStore";

describe("routeFrame", () => {
  beforeEach(() => {
    resetStores();
    vi.spyOn(console, "warn").mockImplementation(() => undefined);
  });

  it("routes each SRS event into the task store", () => {
    expect(
      routeFrame({
        event: "task_started",
        task_id: "t1",
        request_id: null,
        payload: { speak: "Starting: search", goal: "search" },
      }),
    ).not.toBeNull();
    expect(useTaskStore.getState().task?.status).toBe("running");
    expect(useTaskStore.getState().latestSpeak).toBe("Starting: search");

    routeFrame({
      event: "browser_action",
      task_id: "t1",
      request_id: null,
      payload: { speak: "Opening wikipedia.org", action: "navigate", step: 1 },
    });
    routeFrame({
      event: "agent_status",
      task_id: "t1",
      request_id: null,
      payload: { speak: "Now on: Wikipedia", title: "Wikipedia" },
    });
    routeFrame({
      event: "perception_result",
      task_id: "t1",
      request_id: null,
      payload: { speak: "A Wikipedia article", text: "A Wikipedia article" },
    });
    routeFrame({
      event: "confirmation_required",
      task_id: "t1",
      request_id: null,
      payload: { speak: "Confirm this?", confirmation_id: "c1", token: "tok" },
    });
    expect(useTaskStore.getState().pendingConfirmation?.confirmation_id).toBe("c1");

    routeFrame({
      event: "task_completed",
      task_id: "t1",
      request_id: null,
      payload: { speak: "Done. Found it.", result: "Found it." },
    });
    expect(useTaskStore.getState().task?.status).toBe("completed");
    expect(useTaskStore.getState().pendingConfirmation).toBeNull();
    expect(useTaskStore.getState().events).toHaveLength(6);
  });

  it("ignores unknown event names", () => {
    routeFrame({
      event: "task_started",
      task_id: "t1",
      request_id: null,
      payload: { speak: "Starting", goal: "x" },
    });
    const before = useTaskStore.getState().events.length;
    const accepted = routeFrame({
      event: "not_an_srs_event",
      task_id: "t1",
      request_id: null,
      payload: { speak: "nope" },
    });
    expect(accepted).toBeNull();
    expect(useTaskStore.getState().events).toHaveLength(before);
  });

  it("caps the event log at 50 frames, newest first", () => {
    for (let i = 0; i < 55; i += 1) {
      routeFrame({
        event: "agent_status",
        task_id: "t1",
        request_id: null,
        payload: { speak: `step ${i}` },
      });
    }
    const events = useTaskStore.getState().events;
    expect(events).toHaveLength(50);
    expect(events[0].speak).toBe("step 54");
  });
});
