import { renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { useKeyboardShortcuts } from "@/hooks/useKeyboardShortcuts";
import { isTextInputTarget, shortcutFromKeyboardEvent } from "@/lib/shortcuts";

describe("keyboard shortcuts", () => {
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
