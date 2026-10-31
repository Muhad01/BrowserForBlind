import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { fetchCurrentTask } from "@/lib/api";
import { useRealtime } from "@/hooks/useRealtime";
import { AUTH_CLOSE_CODE } from "@/lib/wsClient";
import { resetStores } from "@/test/resetStores";
import { useAuthStore } from "@/stores/authStore";
import { useTaskStore } from "@/stores/taskStore";

vi.mock("@/lib/api", () => ({
  fetchWsTicket: vi.fn(async () => "ticket-live"),
  fetchCurrentTask: vi.fn(async () => ({
    task: {
      id: "server-task",
      goal: "Recovered goal",
      mode: "task",
      status: "running",
      result_text: null,
      error_code: null,
      error_message: null,
      final_url: null,
      step_count: 2,
      created_at: null,
      finished_at: null,
      pending_confirmation: null,
    },
  })),
}));

class MockSocket {
  static instances: MockSocket[] = [];
  url: string;
  readyState = 0;
  onopen: ((event: Event) => void) | null = null;
  onclose: ((event: CloseEvent) => void) | null = null;
  onmessage: ((event: MessageEvent<string>) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  constructor(url: string) {
    this.url = url;
    MockSocket.instances.push(this);
  }
  send() {}
  close(code = 1000) {
    this.readyState = 3;
    this.onclose?.({ code } as CloseEvent);
  }
  open() {
    this.readyState = 1;
    this.onopen?.({} as Event);
  }
}

describe("useRealtime", () => {
  const speak = vi.fn();

  beforeEach(() => {
    resetStores();
    speak.mockReset();
    MockSocket.instances = [];
    vi.stubGlobal("WebSocket", MockSocket);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it("replaces task state after reconnect and speaks when the disconnect lasted over 3s", async () => {
    let offset = 0;
    const realNow = Date.now.bind(Date);
    vi.spyOn(Date, "now").mockImplementation(() => realNow() + offset);

    renderHook(() => useRealtime({ enabled: true, speak }));
    await waitFor(() => expect(MockSocket.instances.length).toBe(1));
    MockSocket.instances[0].open();
    MockSocket.instances[0].close(1006);
    offset = 4000;
    await waitFor(() => expect(MockSocket.instances.length).toBe(2), { timeout: 2500 });
    MockSocket.instances[1].open();
    await waitFor(() => expect(useTaskStore.getState().task?.id).toBe("server-task"));
    expect(fetchCurrentTask).toHaveBeenCalled();
    expect(speak).toHaveBeenCalledWith("Reconnected.", { priority: "assertive", event: "local" });
  });

  it("speaks a finished-while-disconnected result exactly once", async () => {
    useTaskStore.setState({
      task: {
        id: "t-done",
        goal: "search",
        mode: "task",
        status: "running",
        result_text: null,
        error_code: null,
        error_message: null,
        final_url: null,
        step_count: 2,
        created_at: null,
        finished_at: null,
        pending_confirmation: null,
      },
    });
    vi.mocked(fetchCurrentTask).mockResolvedValue({
      task: {
        id: "t-done",
        goal: "search",
        mode: "task",
        status: "completed",
        result_text: "Found the article.",
        error_code: null,
        error_message: null,
        final_url: "https://en.wikipedia.org",
        step_count: 4,
        created_at: null,
        finished_at: null,
        pending_confirmation: null,
      },
    });

    renderHook(() => useRealtime({ enabled: true, speak }));
    await waitFor(() => expect(MockSocket.instances.length).toBe(1));
    MockSocket.instances[0].open();
    MockSocket.instances[0].close(1006);
    await waitFor(() => expect(MockSocket.instances.length).toBe(2), { timeout: 2500 });
    MockSocket.instances[1].open();
    await waitFor(() =>
      expect(speak).toHaveBeenCalledWith(
        "While we were disconnected, your task finished. Found the article.",
        { priority: "assertive", event: "local" },
      ),
    );

    speak.mockClear();
    MockSocket.instances[1].close(1006);
    await waitFor(() => expect(MockSocket.instances.length).toBe(3), { timeout: 2500 });
    MockSocket.instances[2].open();
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(speak).not.toHaveBeenCalledWith(
      expect.stringContaining("While we were disconnected"),
      expect.anything(),
    );
  });

  it("clears auth on close code 4401 and does not reconnect", async () => {
    useAuthStore.getState().setUser({ id: "1", username: "demo" });
    renderHook(() => useRealtime({ enabled: true, speak }));
    await waitFor(() => expect(MockSocket.instances.length).toBe(1));
    MockSocket.instances[0].open();
    MockSocket.instances[0].close(AUTH_CLOSE_CODE);
    await waitFor(() => expect(useAuthStore.getState().status).toBe("unauthenticated"));
    expect(speak).toHaveBeenCalledWith("Please sign in again.", { priority: "assertive" });
    await new Promise((resolve) => setTimeout(resolve, 200));
    expect(MockSocket.instances).toHaveLength(1);
  });
});
