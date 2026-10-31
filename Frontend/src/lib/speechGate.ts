/** Half-duplex speech gate: the app never talks while the microphone is open. */

import { useVoiceStore } from "@/stores/voiceStore";
import type { Verbosity } from "@/stores/speechStore";
import type { SpeechItem } from "@/lib/speechQueue";

export const GATE_RELEASE_MS = 400;
export const PROCESSING_MS = 3000;
export const EARCON_MS = 150;
export const HEARTBEAT_MS = 12_000;
export const AGENT_STATUS_THROTTLE_MS = 6_000;
export const LISTEN_TIMEOUT_MS = 15_000;

const KEEP_EVENTS = new Set([
  "task_started",
  "task_completed",
  "task_failed",
  "confirmation_required",
  "perception_result",
]);

export function isSpeechGated(): boolean {
  const voice = useVoiceStore.getState();
  return voice.listening || voice.processing;
}

function isProgressEvent(event: string | undefined, verbosity: Verbosity): boolean {
  if (event === "agent_status") {
    return true;
  }
  return event === "browser_action" && verbosity === "detailed";
}

export function compactHeld(items: SpeechItem[], verbosity: Verbosity = "brief"): SpeechItem[] {
  const progress = items.filter((item) => isProgressEvent(item.event, verbosity));
  const latestProgress = progress[progress.length - 1];
  const compacted: SpeechItem[] = [];
  let includedProgress = false;

  for (const item of items) {
    if (item.event === "browser_action" || item.event === "agent_status") {
      if (item === latestProgress && !includedProgress) {
        compacted.push(item);
        includedProgress = true;
      }
      continue;
    }
    if (!item.event || KEEP_EVENTS.has(item.event) || item.event === "local") {
      compacted.push(item);
    }
  }
  return compacted;
}
