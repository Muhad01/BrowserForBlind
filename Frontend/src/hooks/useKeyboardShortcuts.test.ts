import { renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useKeyboardShortcuts } from "@/hooks/useKeyboardShortcuts";
import { isTextInputTarget, shortcutFromKeyboardEvent } from "@/lib/shortcuts";
import { resetStores } from "@/test/resetStores";
import { useSpeechStore } from "@/stores/speechStore";

describe("keyboard shortcuts", () => {
  beforeEach(() => {
    resetStores();
  });

  it("ignores shortcuts while typing in an input", () => {
    const input = document.createElement("input");
    expect(isTextInputTarget(input)).toBe(true);
    const button = document.createElement("button");
    expect(isTextInputTarget(button)).toBe(false);
  });

  it("maps the documented keys", () => {
    expect(shortcutFromKeyboardEvent(new KeyboardEvent("keydown", { key: " " }))).toBe("toggle-listen");
    expect(shortcutFromKeyboardEvent(new KeyboardEvent("keydown", { key: "Escape" }))).toBe("stop");
    expect(shortcutFromKeyboardEvent(new KeyboardEvent("keydown", { key: "R" }))).toBe("repeat");
    expect(shortcutFromKeyboardEvent(new KeyboardEvent("keydown", { key: "h" }))).toBe("help");
    expect(shortcutFromKeyboardEvent(new KeyboardEvent("keydown", { key: "y" }))).toBe("confirm-yes");
    expect(shortcutFromKeyboardEvent(new KeyboardEvent("keydown", { key: "n" }))).toBe("confirm-no");
    expect(shortcutFromKeyboardEvent(new KeyboardEvent("keydown", { key: "s" }))).toBe("settings");
    expect(shortcutFromKeyboardEvent(new KeyboardEvent("keydown", { key: "v" }))).toBe("toggle-verbosity");
    expect(shortcutFromKeyboardEvent(new KeyboardEvent("keydown", { key: "t" }))).toBe("toggle-talk-mode");
    expect(shortcutFromKeyboardEvent(new KeyboardEvent("keydown", { key: "l" }))).toBe("cycle-language");
    expect(shortcutFromKeyboardEvent(new KeyboardEvent("keydown", { key: "g" }))).toBe("toggle-voice-gender");
    expect(shortcutFromKeyboardEvent(new KeyboardEvent("keydown", { key: "Escape" }))).toBe("stop");
    expect(shortcutFromKeyboardEvent(new KeyboardEvent("keydown", { key: "Escape", shiftKey: true }))).toBe(
      "close-browser",
    );
  });

  it("hold mode starts on keydown, ignores repeat, and stops on keyup without abort semantics", () => {
    useSpeechStore.getState().setSettings({ talkMode: "hold" });
    const onAction = vi.fn();
    renderHook(() => useKeyboardShortcuts(true, onAction));
    window.dispatchEvent(new KeyboardEvent("keydown", { key: " ", repeat: true, bubbles: true }));
    expect(onAction).not.toHaveBeenCalled();
    window.dispatchEvent(new KeyboardEvent("keydown", { key: " ", repeat: false, bubbles: true }));
    expect(onAction).toHaveBeenCalledWith("listen-start");
    window.dispatchEvent(new KeyboardEvent("keyup", { key: " ", bubbles: true }));
    expect(onAction).toHaveBeenCalledWith("listen-stop");
  });

  it("ignores Space auto-repeat in press mode so capture is not toggled off", () => {
    useSpeechStore.getState().setSettings({ talkMode: "press" });
    const onAction = vi.fn();
    renderHook(() => useKeyboardShortcuts(true, onAction));
    window.dispatchEvent(new KeyboardEvent("keydown", { key: " ", repeat: false, bubbles: true }));
    window.dispatchEvent(new KeyboardEvent("keydown", { key: " ", repeat: true, bubbles: true }));
    expect(onAction).toHaveBeenCalledTimes(1);
    expect(onAction).toHaveBeenCalledWith("toggle-listen");
  });

  it("Shift+Escape closes the browser and Escape only stops", () => {
    const onAction = vi.fn();
    renderHook(() => useKeyboardShortcuts(true, onAction));
    window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", shiftKey: true, bubbles: true }));
    expect(onAction).toHaveBeenCalledWith("close-browser");
    onAction.mockReset();
    window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    expect(onAction).toHaveBeenCalledWith("stop");
    expect(onAction).not.toHaveBeenCalledWith("close-browser");
  });

  it("L cycles through the language shortcut", () => {
    const onAction = vi.fn();
    renderHook(() => useKeyboardShortcuts(true, onAction));
    window.dispatchEvent(new KeyboardEvent("keydown", { key: "l", bubbles: true }));
    expect(onAction).toHaveBeenCalledWith("cycle-language");
  });

  it("does not fire while focus is in a text field", () => {
    const onAction = vi.fn();
    renderHook(() => useKeyboardShortcuts(true, onAction));
    const input = document.createElement("input");
    document.body.appendChild(input);
    input.dispatchEvent(new KeyboardEvent("keydown", { key: " ", bubbles: true }));
    expect(onAction).not.toHaveBeenCalled();
    input.remove();
  });
});
