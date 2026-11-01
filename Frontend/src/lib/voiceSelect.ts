export type VoiceGender = "female" | "male";

export const MALE_NAME_MARKERS = [
  "david",
  "mark",
  "guy",
  "ravi",
  "prabhat",
  "george",
  "james",
  "ryan",
  "asad",
  "male",
];

export const FEMALE_NAME_MARKERS = [
  "zira",
  "hazel",
  "heera",
  "neerja",
  "aria",
  "jenny",
  "susan",
  "sonia",
  "uzma",
  "female",
  "google uk english female",
];

export interface SpeechVoiceLike {
  name: string;
  lang: string;
  voiceURI: string;
}

function genderOf(voice: SpeechVoiceLike): VoiceGender | null {
  const name = voice.name.toLowerCase();
  if (FEMALE_NAME_MARKERS.some((marker) => name.includes(marker))) {
    return "female";
  }
  if (MALE_NAME_MARKERS.some((marker) => name.includes(marker))) {
    return "male";
  }
  return null;
}

function langRank(lang: string, wanted: "en" | "ur"): number {
  const lower = lang.toLowerCase();
  if (wanted === "ur") {
    if (lower.startsWith("ur-pk")) {
      return 0;
    }
    if (lower.startsWith("ur")) {
      return 1;
    }
    return 99;
  }
  if (lower.startsWith("en-in")) {
    return 0;
  }
  if (lower.startsWith("en-gb")) {
    return 1;
  }
  if (lower.startsWith("en-us")) {
    return 2;
  }
  if (lower.startsWith("en")) {
    return 3;
  }
  return 99;
}

export function pickVoice(
  voices: SpeechVoiceLike[],
  language: "en" | "ur",
  gender: VoiceGender,
  preferredURI = "",
): { voice: SpeechVoiceLike | null; missingGender: boolean; missingLanguage: boolean } {
  if (preferredURI) {
    const specific = voices.find((voice) => voice.voiceURI === preferredURI);
    if (specific) {
      return { voice: specific, missingGender: false, missingLanguage: false };
    }
  }
  const matchingLang = voices.filter((voice) => langRank(voice.lang, language) < 99);
  if (matchingLang.length === 0) {
    return { voice: voices[0] ?? null, missingGender: true, missingLanguage: language === "ur" };
  }
  const gendered = matchingLang.filter((voice) => genderOf(voice) === gender);
  if (gendered.length === 0) {
    const ranked = [...matchingLang].sort((a, b) => langRank(a.lang, language) - langRank(b.lang, language));
    return { voice: ranked[0], missingGender: true, missingLanguage: false };
  }
  const ranked = [...gendered].sort((a, b) => langRank(a.lang, language) - langRank(b.lang, language));
  return { voice: ranked[0], missingGender: false, missingLanguage: false };
}
