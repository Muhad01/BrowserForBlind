import { beforeEach, describe, expect, it, vi } from "vitest";

import { handleTranscript } from "@/lib/handleTranscript";
import { MIC_ERROR_MESSAGES } from "@/lib/phrases";
import { resetStores } from "@/test/resetStores";
import { useSpeechStore } from "@/stores/speechStore";
import { useVoiceStore } from "@/stores/voiceStore";

describe("handleTranscript", () => {
  const sendVoiceCommand = vi.fn();
  const repeatLast = vi.fn();
  const openHelp = vi.fn();

  beforeEach(() => {
    resetStores();
    sendVoiceCommand.mockReset();
    repeatLast.mockReset();
    openHelp.mockReset();
  });

  it("ignores empty transcripts", () => {
    expect(handleTranscript("   ", { sendVoiceCommand, repeatLast, openHelp })).toBe("empty");
    expect(sendVoiceCommand).not.toHaveBeenCalled();
  });

  it("handles repeat locally", () => {
    handleTranscript("Say that again!", { sendVoiceCommand, repeatLast, openHelp });
    expect(repeatLast).toHaveBeenCalledOnce();
    expect(sendVoiceCommand).not.toHaveBeenCalled();
    expect(useVoiceStore.getState().lastTranscript).toBe("Say that again!");
  });

  it("handles help locally", () => {
    handleTranscript("what can I say", { sendVoiceCommand, repeatLast, openHelp });
    expect(openHelp).toHaveBeenCalledOnce();
    expect(useSpeechStore.getState().helpOpen).toBe(true);
    expect(sendVoiceCommand).not.toHaveBeenCalled();
  });

  it("sends other text as voice_command", () => {
    handleTranscript("Search Wikipedia for artificial intelligence", {
      sendVoiceCommand,
      repeatLast,
      openHelp,
    });
    expect(sendVoiceCommand).toHaveBeenCalledWith("Search Wikipedia for artificial intelligence");
  });

  it("maps each recognition error to retry guidance", () => {
    expect(MIC_ERROR_MESSAGES["not-allowed"]).toMatch(/Allow the microphone/);
    expect(MIC_ERROR_MESSAGES["service-not-allowed"]).toMatch(/Allow the microphone/);
    expect(MIC_ERROR_MESSAGES["no-speech"]).toMatch(/didn't hear/);
    expect(MIC_ERROR_MESSAGES["audio-capture"]).toMatch(/No microphone/);
    expect(MIC_ERROR_MESSAGES.network).toMatch(/internet connection/);
  });
});
