/** Brief vs detailed narration. FR-20, NFR-ACC-02 */

import type { ServerFrame } from "@/lib/events";
import { speakFromPayload } from "@/lib/events";
import { speechPriorityForEvent } from "@/lib/routeFrame";
import { AGENT_STATUS_THROTTLE_MS } from "@/lib/speechGate";
import { WORKING_ON_IT } from "@/lib/phrases";
import type { SpeechPriority } from "@/lib/speechQueue";
import { useSpeechStore, type Verbosity } from "@/stores/speechStore";

export interface NarrationDecision {
  speakText: string | null;
  liveText: string;
  priority: SpeechPriority;
}

let lastAgentStatusAt = 0;

export function resetNarrationPolicy(): void {
  lastAgentStatusAt = 0;
}

export function decideNarration(
  frame: ServerFrame,
  options: { now?: number; verbosity?: Verbosity } = {},
): NarrationDecision {
  const verbosity = options.verbosity ?? useSpeechStore.getState().settings.verbosity;
  const now = options.now ?? Date.now();
  const full = speakFromPayload(frame.payload);
  const priority = speechPriorityForEvent(frame.event) ?? "polite";

  if (frame.event === "task_started") {
    const brief = typeof frame.payload.brief === "string" && frame.payload.brief.trim()
      ? frame.payload.brief.trim()
      : WORKING_ON_IT;
    return {
      speakText: verbosity === "brief" ? brief : full || brief,
      liveText: full || brief,
      priority: "polite",
    };
  }

  if (frame.event === "browser_action") {
    return {
      speakText: verbosity === "detailed" ? full || null : null,
      liveText: full,
      priority: "polite",
    };
  }

  if (frame.event === "agent_status") {
    if (frame.request_id) {
      return { speakText: full || null, liveText: full, priority: "polite" };
    }
    if (verbosity === "brief") {
      if (lastAgentStatusAt && now - lastAgentStatusAt < AGENT_STATUS_THROTTLE_MS) {
        return { speakText: null, liveText: full, priority: "polite" };
      }
      lastAgentStatusAt = now;
    }
    return { speakText: full || null, liveText: full, priority: "polite" };
  }

  return {
    speakText: full || null,
    liveText: full,
    priority,
  };
}

export function narrateServerFrame(
  frame: ServerFrame,
  speak: (text: string, options?: { priority?: SpeechPriority; event?: string; liveText?: string }) => void,
): void {
  const decision = decideNarration(frame);
  if (!decision.speakText) {
    if (decision.liveText) {
      useSpeechStore.getState().setLive(decision.liveText, decision.priority);
    }
    return;
  }
  speak(decision.speakText, {
    priority: decision.priority,
    event: frame.event,
    liveText: decision.liveText,
  });
}
