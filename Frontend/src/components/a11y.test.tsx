import { render } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { axe } from "vitest-axe";

import { LoginForm } from "@/components/LoginForm";
import { VoiceConsole } from "@/components/VoiceConsole";
import HomePage from "@/app/page";
import { resetStores } from "@/test/resetStores";
import { useAuthStore } from "@/stores/authStore";

describe("accessibility", () => {
  beforeEach(() => {
    resetStores();
    Object.defineProperty(window, "speechSynthesis", {
      configurable: true,
      value: {
        speak: () => undefined,
        cancel: () => undefined,
        getVoices: () => [],
        addEventListener: () => undefined,
        removeEventListener: () => undefined,
      },
    });
    Object.defineProperty(window, "SpeechSynthesisUtterance", {
      configurable: true,
      value: class {
        text = "";
        constructor(text: string) {
          this.text = text;
        }
      },
    });
  });

  it("has no axe violations on the start screen", async () => {
    const { container } = render(<HomePage />);
    expect(await axe(container)).toHaveNoViolations();
  });

  it("has no axe violations on the login form", async () => {
    const { container } = render(<LoginForm onError={() => undefined} />);
    expect(await axe(container)).toHaveNoViolations();
  });

  it("has no axe violations on the main console", async () => {
    useAuthStore.getState().setUser({ id: "1", username: "demo" });
    const { container } = render(
      <VoiceConsole
        client={null}
        onToggleListen={() => undefined}
        onRepeat={() => undefined}
        onCancelSpeech={() => undefined}
        onSpeakHelp={() => undefined}
      />,
    );
    expect(await axe(container)).toHaveNoViolations();
  });
});
