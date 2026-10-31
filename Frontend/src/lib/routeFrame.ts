import { ASSERTIVE_EVENTS, POLITE_EVENTS, speakFromPayload, type ServerFrame } from "@/lib/events";
import { useTaskStore } from "@/stores/taskStore";

export function routeFrame(raw: unknown): ServerFrame | null {
  const result = useTaskStore.getState().applyFrame(raw);
  return result.accepted && result.frame ? result.frame : null;
}

export function speechPriorityForEvent(event: string): "polite" | "assertive" | null {
  if (ASSERTIVE_EVENTS.has(event)) {
    return "assertive";
  }
  if (POLITE_EVENTS.has(event)) {
    return "polite";
  }
  return null;
}

export function frameSpeak(frame: ServerFrame): string {
  return speakFromPayload(frame.payload);
}
