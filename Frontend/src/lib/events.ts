/** TypeScript types for every SRS frame (mirror core/realtime/schemas.py). FR-55..66 */

export const SRS_EVENTS = [
  "task_started",
  "agent_status",
  "browser_action",
  "perception_result",
  "confirmation_required",
  "task_completed",
  "task_failed",
] as const;

export type SrsEventName = (typeof SRS_EVENTS)[number];

export type ClientMessageType = "voice_command" | "stop_task" | "confirmation_response";

export interface ClientEnvelope {
  type: ClientMessageType;
  request_id: string;
  payload: Record<string, unknown>;
}

export interface ServerFrame {
  event: string;
  task_id: string | null;
  request_id: string | null;
  payload: Record<string, unknown>;
}

export interface TaskSnapshot {
  id: string;
  goal: string;
  mode: string;
  status: string;
  result_text: string | null;
  error_code: string | null;
  error_message: string | null;
  final_url: string | null;
  step_count: number;
  cancel_requested?: boolean;
  created_at: string | null;
  finished_at: string | null;
  pending_confirmation: PendingConfirmation | null;
}

export interface PendingConfirmation {
  confirmation_id: string;
  token: string;
  speak: string;
}

export const POLITE_EVENTS: ReadonlySet<string> = new Set([
  "task_started",
  "browser_action",
  "agent_status",
  "perception_result",
]);

export const ASSERTIVE_EVENTS: ReadonlySet<string> = new Set([
  "task_completed",
  "task_failed",
  "confirmation_required",
]);

export function isSrsEvent(event: string): event is SrsEventName {
  return (SRS_EVENTS as readonly string[]).includes(event);
}

export function isServerFrame(value: unknown): value is ServerFrame {
  if (!value || typeof value !== "object") {
    return false;
  }
  const candidate = value as Record<string, unknown>;
  if (typeof candidate.event !== "string") {
    return false;
  }
  if (candidate.payload === null || typeof candidate.payload !== "object") {
    return false;
  }
  return true;
}

export function speakFromPayload(payload: Record<string, unknown>): string {
  return typeof payload.speak === "string" ? payload.speak : "";
}
