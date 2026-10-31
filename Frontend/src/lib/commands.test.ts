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

  function renderActions() {
    return renderHook(() =>
      useConsoleActions({
        client,
        speak: vi.fn(),
        cancelSpeech: vi.fn(),
        closeMic: vi.fn(),
        startListening: vi.fn(),
        stopListening: vi.fn(),
        toggleListening: vi.fn(),
        repeatLast: vi.fn(),
      }),
    );
  }

  it("Escape clears speech including held items and sends stop_task when a task is active", () => {
    const cancelSpeech = vi.fn();
    const closeMic = vi.fn();
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
    const { result } = renderHook(() =>
      useConsoleActions({
        client,
        speak: vi.fn(),
        cancelSpeech,
        closeMic,
        startListening: vi.fn(),
        stopListening: vi.fn(),
        toggleListening: vi.fn(),
        repeatLast: vi.fn(),
      }),
    );
    result.current.handleShortcut("stop");
    expect(closeMic).toHaveBeenCalled();
    expect(cancelSpeech).toHaveBeenCalled();
    expect(send).toHaveBeenCalledWith("stop_task", { task_id: null });
  });

  it("Y and N send confirmation_response only when a confirmation is pending", () => {
    const { result } = renderActions();
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
