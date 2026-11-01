/** Keyboard shortcut helpers. NFR-ACC-01 */

export type ShortcutAction =
  | "toggle-listen"
  | "listen-start"
  | "listen-stop"
  | "stop"
  | "repeat"
  | "help"
  | "confirm-yes"
  | "confirm-no"
  | "settings"
  | "toggle-verbosity"
  | "toggle-talk-mode"
  | "cycle-language"
  | "toggle-voice-gender"
  | "close-browser";

export function isTextInputTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) {
    return false;
  }
  const tag = target.tagName;
  if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") {
    return true;
  }
  return Boolean(target.isContentEditable);
}

export function shortcutFromKeyboardEvent(event: KeyboardEvent): ShortcutAction | null {
  if (event.altKey || event.ctrlKey || event.metaKey) {
    return null;
  }
  if (event.key === " " || event.code === "Space") {
    return "toggle-listen";
  }
  if (event.key === "Escape") {
    return event.shiftKey ? "close-browser" : "stop";
  }
  const key = event.key.length === 1 ? event.key.toLowerCase() : event.key;
  if (key === "r") {
    return "repeat";
  }
  if (key === "h") {
    return "help";
  }
  if (key === "y") {
    return "confirm-yes";
  }
  if (key === "n") {
    return "confirm-no";
  }
  if (key === "s") {
    return "settings";
  }
  if (key === "v") {
    return "toggle-verbosity";
  }
  if (key === "t") {
    return "toggle-talk-mode";
  }
  if (key === "l") {
    return "cycle-language";
  }
  if (key === "g") {
    return "toggle-voice-gender";
  }
  return null;
}
