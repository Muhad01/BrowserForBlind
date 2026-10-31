/** Speak a result that finished while the socket was down. NFR-REL-05 */

import type { TaskSnapshot } from "@/lib/events";
import { DISCONNECTED_FINISHED_PREFIX } from "@/lib/phrases";

const ACTIVE = new Set(["running", "pending", "waiting_confirmation"]);
const FINISHED = new Set(["completed", "failed", "cancelled"]);

const heardIds = new Set<string>();

export function resetDisconnectNarration(): void {
  heardIds.clear();
}

export function markTaskResultHeard(taskId: string | null | undefined): void {
  if (taskId) {
    heardIds.add(taskId);
  }
}

export function finishedWhileDisconnectedSpeak(
  previous: TaskSnapshot | null,
  next: TaskSnapshot | null,
): string | null {
  if (!previous || !next || previous.id !== next.id) {
    return null;
  }
  if (!ACTIVE.has(previous.status) || !FINISHED.has(next.status)) {
    return null;
  }
  if (heardIds.has(next.id)) {
    return null;
  }
  heardIds.add(next.id);
  const result = (next.result_text || next.error_message || "").trim();
  return `${DISCONNECTED_FINISHED_PREFIX}${result}`.trim();
}
