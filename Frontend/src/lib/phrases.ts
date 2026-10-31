/** Local voice phrases handled in the UI, not sent to the server. FR-04 */

export const SPEECH_LANG = "en-US"; // TBD-07

export const HELP_SPEAK =
  "Press Space to speak. Press Escape to stop. Press R to repeat. Press H for help. Press S for settings. Press Y or N to answer a confirmation. You can say: Search Wikipedia for artificial intelligence.";

export const WELCOME_SPEAK =
  "Ready. Press Space and say what you want to do. Press H for help.";

export const SIGN_IN_AGAIN_SPEAK = "Please sign in again.";

export const RECONNECTED_SPEAK = "Reconnected.";

export const VOICE_UNSUPPORTED_SPEAK =
  "Voice input isn't supported in this browser. Please use Google Chrome, or type your command.";

export const MIC_ERROR_MESSAGES: Record<string, string> = {
  "not-allowed":
    "Microphone access is blocked. Allow the microphone in Chrome's address bar, then press Space to try again.",
  "service-not-allowed":
    "Microphone access is blocked. Allow the microphone in Chrome's address bar, then press Space to try again.",
  "no-speech": "I didn't hear anything. Press Space and try again.",
  "audio-capture": "No microphone was found. Check that it's connected, then press Space.",
  network: "Voice recognition needs an internet connection. Check your connection and press Space.",
};

export function normalizePhrase(text: string): string {
  return text
    .toLowerCase()
    .replace(/[^\p{L}\p{N}\s]/gu, "")
    .replace(/\s+/g, " ")
    .trim();
}

export function isRepeatPhrase(text: string): boolean {
  const normalized = normalizePhrase(text);
  return normalized === "repeat" || normalized === "say that again";
}

export function isHelpPhrase(text: string): boolean {
  const normalized = normalizePhrase(text);
  return normalized === "help" || normalized === "what can i say";
}

export type TranscriptKind = "empty" | "repeat" | "help" | "command";

export function classifyTranscript(text: string): TranscriptKind {
  if (!text.trim()) {
    return "empty";
  }
  if (isRepeatPhrase(text)) {
    return "repeat";
  }
  if (isHelpPhrase(text)) {
    return "help";
  }
  return "command";
}
