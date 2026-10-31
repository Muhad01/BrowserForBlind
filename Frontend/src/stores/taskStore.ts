import { create } from "zustand";

import {
  isSrsEvent,
  isServerFrame,
  speakFromPayload,
  type PendingConfirmation,
  type ServerFrame,
  type TaskSnapshot,
} from "@/lib/events";

const EVENT_CAP = 50;

export interface LoggedFrame {
  event: string;
  task_id: string | null;
  request_id: string | null;
  speak: string;
  receivedAt: string;
}

interface TaskState {
  task: TaskSnapshot | null;
  events: LoggedFrame[];
  pendingConfirmation: PendingConfirmation | null;
  latestSpeak: string;
  replaceFromServer: (task: TaskSnapshot | null) => void;
  applyFrame: (frame: unknown) => { accepted: boolean; frame?: ServerFrame };
  clearConfirmation: () => void;
}

function confirmationFromPayload(payload: Record<string, unknown>): PendingConfirmation | null {
  const confirmationId = payload.confirmation_id;
  const token = payload.token;
  const speak = speakFromPayload(payload);
  if (typeof confirmationId !== "string" || typeof token !== "string") {
    return null;
  }
  return { confirmation_id: confirmationId, token, speak };
}

function applyStatus(task: TaskSnapshot | null, frame: ServerFrame): TaskSnapshot | null {
  const base: TaskSnapshot = task ?? {
    id: frame.task_id ?? "",
    goal: typeof frame.payload.goal === "string" ? frame.payload.goal : "",
    mode: "task",
    status: "running",
    result_text: null,
    error_code: null,
    error_message: null,
    final_url: null,
    step_count: 0,
    created_at: null,
    finished_at: null,
    pending_confirmation: null,
  };

  if (frame.event === "task_started") {
    return {
      ...base,
      id: frame.task_id ?? base.id,
      goal: typeof frame.payload.goal === "string" ? frame.payload.goal : base.goal,
      status: "running",
      error_code: null,
      error_message: null,
      result_text: null,
      pending_confirmation: null,
    };
  }
  if (frame.event === "task_completed") {
    return {
      ...base,
      status: "completed",
      result_text: typeof frame.payload.result === "string" ? frame.payload.result : base.result_text,
      final_url: typeof frame.payload.final_url === "string" ? frame.payload.final_url : base.final_url,
      pending_confirmation: null,
    };
  }
  if (frame.event === "task_failed") {
    return {
      ...base,
      status: "failed",
      error_code: typeof frame.payload.error_code === "string" ? frame.payload.error_code : base.error_code,
      error_message:
        typeof frame.payload.error_message === "string" ? frame.payload.error_message : base.error_message,
      pending_confirmation: null,
    };
  }
  return { ...base, id: frame.task_id ?? base.id };
}

export const useTaskStore = create<TaskState>((set, get) => ({
  task: null,
  events: [],
  pendingConfirmation: null,
  latestSpeak: "",
  replaceFromServer: (task) =>
    set({
      task,
      pendingConfirmation: task?.pending_confirmation ?? null,
    }),
  applyFrame: (raw) => {
    if (!isServerFrame(raw)) {
      return { accepted: false };
    }
    if (!isSrsEvent(raw.event)) {
      console.warn("Ignored unknown realtime event", raw.event);
      return { accepted: false };
    }

    const speak = speakFromPayload(raw.payload);
    const logged: LoggedFrame = {
      event: raw.event,
      task_id: raw.task_id,
      request_id: raw.request_id,
      speak,
      receivedAt: new Date().toISOString(),
    };

    const pending =
      raw.event === "confirmation_required"
        ? confirmationFromPayload(raw.payload)
        : raw.event === "task_completed" || raw.event === "task_failed"
          ? null
          : get().pendingConfirmation;

    set({
      task: applyStatus(get().task, raw),
      events: [logged, ...get().events].slice(0, EVENT_CAP),
      pendingConfirmation: pending,
      latestSpeak: speak || get().latestSpeak,
    });
    return { accepted: true, frame: raw };
  },
  clearConfirmation: () => set({ pendingConfirmation: null }),
}));
