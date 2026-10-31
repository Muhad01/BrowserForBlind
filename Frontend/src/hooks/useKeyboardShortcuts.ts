"use client";

import { useEffect } from "react";

import { isTextInputTarget, shortcutFromKeyboardEvent, type ShortcutAction } from "@/lib/shortcuts";

export function useKeyboardShortcuts(
  enabled: boolean,
  onAction: (action: ShortcutAction) => void,
) {
  useEffect(() => {
    if (!enabled) {
      return;
    }
    const listener = (event: KeyboardEvent) => {
      if (isTextInputTarget(event.target)) {
        return;
      }
      const action = shortcutFromKeyboardEvent(event);
      if (!action) {
        return;
      }
      event.preventDefault();
      onAction(action);
    };
    window.addEventListener("keydown", listener);
    return () => window.removeEventListener("keydown", listener);
  }, [enabled, onAction]);
}
