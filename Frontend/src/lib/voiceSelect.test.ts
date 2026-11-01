import { describe, expect, it } from "vitest";

import { pickVoice } from "@/lib/voiceSelect";

const voices = [
  { name: "Microsoft David", lang: "en-US", voiceURI: "david" },
  { name: "Microsoft Zira", lang: "en-US", voiceURI: "zira" },
  { name: "Google UK English Female", lang: "en-GB", voiceURI: "ukf" },
  { name: "Microsoft Ravi", lang: "en-IN", voiceURI: "ravi" },
  { name: "Microsoft Neerja", lang: "en-IN", voiceURI: "neerja" },
  { name: "Microsoft Asad", lang: "ur-PK", voiceURI: "asad" },
  { name: "Microsoft Uzma", lang: "ur-PK", voiceURI: "uzma" },
];

describe("pickVoice", () => {
  it("prefers en-IN then gender", () => {
    const male = pickVoice(voices, "en", "male");
    expect(male.voice?.voiceURI).toBe("ravi");
    const female = pickVoice(voices, "en", "female");
    expect(female.voice?.voiceURI).toBe("neerja");
  });

  it("picks Urdu gender voices", () => {
    expect(pickVoice(voices, "ur", "male").voice?.voiceURI).toBe("asad");
    expect(pickVoice(voices, "ur", "female").voice?.voiceURI).toBe("uzma");
  });

  it("reports missing gender and language", () => {
    const onlyEnglish = voices.filter((voice) => voice.lang.startsWith("en"));
    const missing = pickVoice(onlyEnglish, "ur", "female");
    expect(missing.missingLanguage).toBe(true);
    const noMaleUrdu = voices.filter((voice) => voice.voiceURI !== "asad");
    expect(pickVoice(noMaleUrdu, "ur", "male").missingGender).toBe(true);
  });
});
