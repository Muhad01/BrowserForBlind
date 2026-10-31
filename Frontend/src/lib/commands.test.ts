import { beforeEach, describe, expect, it, vi } from "vitest";

import { sendStopTask, sendVoiceCommand } from "@/lib/handleTranscript";
import { useConsoleActions } from "@/components/VoiceConsole";
import { renderHook } from "@testing-library/react";
import { resetStores } from "@/test/resetStores";
import { useTaskStore } from "@/stores/taskStore";
import type { WsClient } from "@/lib/wsClient";

describe("outgoing commands", () => {
  const send = vi.fn();
  const client = { send } as unknown as WsClient;

  beforeEach(() => {
    resetStores();
    send.mockReset();
  });

  it("sends stop_task with a null task_id", () => {
    sendStopTask(client);
    expect(send).toHaveBeenCalledWith("stop_task", { task_id: null });
  });

  it("sends voice_command text", () => {
    sendVoiceCommand(client, "Search Wikipedia for artificial intelligence");
    expect(send).toHaveBeenCalledWith("voice_command", {
      text: "Search Wikipedia for artificial intelligence",
    });
  });

  it("Escape sends stop_task through the shortcut handler", () => {
    const { result } = renderHook(() =>
      useConsoleActions(client, vi.fn(), vi.fn(), vi.fn(), vi.fn()),
    );
    result.current.handleShortcut("stop");
    expect(send).toHaveBeenCalledWith("stop_task", { task_id: null });
  });

  it("Y and N send confirmation_response only when a confirmation is pending", () => {
    const { result } = renderHook(() =>
      useConsoleActions(client, vi.fn(), vi.fn(), vi.fn(), vi.fn()),
    );
    result.current.handleShortcut("confirm-yes");
    result.current.handleShortcut("confirm-no");
    expect(send).not.toHaveBeenCalled();

    useTaskStore.setState({
      pendingConfirmation: { confirmation_id: "c-1", token: "tok-1", speak: "Confirm?" },
    });
    result.current.handleShortcut("confirm-yes");
    expect(send).toHaveBeenCalledWith("confirmation_response", {
      confirmation_id: "c-1",
      token: "tok-1",
      approved: true,
    });
  });
});
