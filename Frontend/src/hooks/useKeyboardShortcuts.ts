"use client";

import { useEffect } from "react";

import { isTextInputTarget, shortcutFromKeyboardEvent, type ShortcutAction } from "@/lib/shortcuts";
import { useSpeechStore } from "@/stores/speechStore";

export function useKeyboardShortcuts(
  enabled: boolean,
  onAction: (action: ShortcutAction) => void,
) {
  useEffect(() => {
    if (!enabled) {
      return;
    }
    const onKeyDown = (event: KeyboardEvent) => {
      if (isTextInputTarget(event.target)) {
        return;
      }
      if (event.key === " " || event.code === "Space") {
        event.preventDefault();
        if (event.repeat) {
          return;
        }
        if (useSpeechStore.getState().settings.talkMode === "hold") {
          onAction("listen-start");
          return;
        }
        onAction("toggle-listen");
        return;
      }
      const action = shortcutFromKeyboardEvent(event);
      if (!action || action === "toggle-listen") {
        return;
      }
      event.preventDefault();
      onAction(action);
    };
    const onKeyUp = (event: KeyboardEvent) => {
      if (isTextInputTarget(event.target)) {
        return;
      }
      if (event.key !== " " && event.code !== "Space") {
        return;
      }
      if (useSpeechStore.getState().settings.talkMode !== "hold") {
        return;
      }
      event.preventDefault();
      onAction("listen-stop");
    };
    window.addEventListener("keydown", onKeyDown);
    window.addEventListener("keyup", onKeyUp);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("keyup", onKeyUp);
    };
  }, [enabled, onAction]);
}
