/** Keyboard shortcut helpers. NFR-ACC-01 */

export type ShortcutAction =
  | "toggle-listen"
  | "stop"
  | "repeat"
  | "help"
  | "confirm-yes"
  | "confirm-no"
  | "settings";

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
    return "stop";
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
  return null;
}
