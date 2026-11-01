import { classifyTranscript } from "@/lib/phrases";
import type { WsClient } from "@/lib/wsClient";
import { useSpeechStore } from "@/stores/speechStore";
import { useVoiceStore } from "@/stores/voiceStore";

export interface VoiceCommandExtra {
  spoken_text?: string;
  language?: "en" | "ur" | "mixed";
}

export interface TranscriptHandlers {
  sendVoiceCommand: (text: string, extra?: VoiceCommandExtra) => void;
  repeatLast: () => void;
  openHelp: () => void;
}

export function handleTranscript(text: string, handlers: TranscriptHandlers): "empty" | "repeat" | "help" | "command" {
  const kind = classifyTranscript(text);
  if (kind === "empty") {
    return kind;
  }
  useVoiceStore.getState().setTranscript(text.trim());
  if (kind === "repeat") {
    handlers.repeatLast();
    return kind;
  }
  if (kind === "help") {
    useSpeechStore.getState().setHelpOpen(true);
    handlers.openHelp();
    return kind;
  }
  handlers.sendVoiceCommand(text.trim());
  return kind;
}

export function sendVoiceCommand(
  client: WsClient | null,
  text: string,
  extra?: VoiceCommandExtra,
): void {
  const payload: Record<string, unknown> = { text };
  if (extra?.spoken_text) {
    payload.spoken_text = extra.spoken_text.slice(0, 500);
  }
  if (extra?.language) {
    payload.language = extra.language;
  }
  const envelope = client?.send("voice_command", payload);
  if (envelope) {
    useVoiceStore.getState().beginProcessing(envelope.request_id);
  }
}

export function sendStopTask(client: WsClient | null): void {
  client?.send("stop_task", { task_id: null });
}

export function sendConfirmation(
  client: WsClient | null,
  confirmationId: string,
  token: string,
  approved: boolean,
): void {
  client?.send("confirmation_response", {
    confirmation_id: confirmationId,
    token,
    approved,
  });
}
