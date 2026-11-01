import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import { shouldRunCommand, transcribeWav } from "@/lib/transcribe";

describe("shouldRunCommand", () => {
  it("refuses incomplete or low-confidence results", () => {
    expect(
      shouldRunCommand({
        spoken_text: "open",
        language: "en",
        english_command: "open",
        confidence: "low",
        complete: false,
      }),
    ).toBe(false);
    expect(
      shouldRunCommand({
        spoken_text: "open Wikipedia",
        language: "en",
        english_command: "open Wikipedia",
        confidence: "high",
        complete: true,
      }),
    ).toBe(true);
  });
});

describe("transcribeWav", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("returns the success shape", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({
          spoken_text: "open Wikipedia",
          language: "en",
          english_command: "open Wikipedia",
          confidence: "high",
          complete: true,
          model: "gemini-3.5-flash-lite",
        }),
      }),
    );
    const result = await transcribeWav(new ArrayBuffer(8), "en");
    expect(result.english_command).toBe("open Wikipedia");
    expect(result.complete).toBe(true);
  });

  it("throws ApiError on 503", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 503,
        statusText: "Unavailable",
        json: async () => ({ error_code: "TRANSCRIPTION_UNAVAILABLE", message: "down" }),
      }),
    );
    await expect(transcribeWav(new ArrayBuffer(8), "auto")).rejects.toBeInstanceOf(ApiError);
  });
});
