import { create } from "zustand";

export type OutputMode = "voice" | "screenreader";
export type Verbosity = "brief" | "detailed";
export type TalkMode = "press" | "hold";
export type LanguageSetting = "auto" | "en" | "ur";
export type SttEngine = "gemini" | "browser";
export type VoiceGender = "female" | "male";

export interface SpeechSettings {
  rate: number;
  voiceURI: string;
  voiceURIByLang: { en: string; ur: string };
  voiceGender: VoiceGender;
  outputMode: OutputMode;
  verbosity: Verbosity;
  talkMode: TalkMode;
  language: LanguageSetting;
  sttEngine: SttEngine;
}

const STORAGE_KEY = "cight-speech-settings";
const DEFAULT_SETTINGS: SpeechSettings = {
  rate: 1.1,
  voiceURI: "",
  voiceURIByLang: { en: "", ur: "" },
  voiceGender: "female",
  outputMode: "voice",
  verbosity: "brief",
  talkMode: "press",
  language: "auto",
  sttEngine: "gemini",
};

function clampRate(rate: number): number {
  if (Number.isNaN(rate)) {
    return DEFAULT_SETTINGS.rate;
  }
  return Math.min(1.6, Math.max(0.8, rate));
}

export function loadSpeechSettings(): SpeechSettings {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) {
      return { ...DEFAULT_SETTINGS };
    }
    const parsed = JSON.parse(raw) as Partial<SpeechSettings>;
    return {
      rate: clampRate(typeof parsed.rate === "number" ? parsed.rate : DEFAULT_SETTINGS.rate),
      voiceURI: typeof parsed.voiceURI === "string" ? parsed.voiceURI : "",
      voiceURIByLang: {
        en: typeof parsed.voiceURIByLang?.en === "string" ? parsed.voiceURIByLang.en : "",
        ur: typeof parsed.voiceURIByLang?.ur === "string" ? parsed.voiceURIByLang.ur : "",
      },
      voiceGender: parsed.voiceGender === "male" ? "male" : "female",
      outputMode: parsed.outputMode === "screenreader" ? "screenreader" : "voice",
      verbosity: parsed.verbosity === "detailed" ? "detailed" : "brief",
      talkMode: parsed.talkMode === "hold" ? "hold" : "press",
      language: parsed.language === "ur" || parsed.language === "en" ? parsed.language : "auto",
      sttEngine: parsed.sttEngine === "browser" ? "browser" : "gemini",
    };
  } catch {
    return { ...DEFAULT_SETTINGS };
  }
}

export function persistSpeechSettings(settings: SpeechSettings): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(settings));
  } catch {
    // localStorage may be blocked; settings still apply for the session.
  }
}

interface SpeechState {
  lastSpoken: string;
  lastAssertive: string;
  lastSpokenAt: number;
  speaking: boolean;
  settings: SpeechSettings;
  politeLive: string;
  assertiveLive: string;
  voices: SpeechSynthesisVoice[];
  helpOpen: boolean;
  settingsOpen: boolean;
  setLastSpoken: (text: string) => void;
  setLastAssertive: (text: string) => void;
  markSpokenAt: () => void;
  setSpeaking: (speaking: boolean) => void;
  setLive: (text: string, mode: "polite" | "assertive") => void;
  setSettings: (patch: Partial<SpeechSettings>) => void;
  setVoices: (voices: SpeechSynthesisVoice[]) => void;
  setHelpOpen: (open: boolean) => void;
  setSettingsOpen: (open: boolean) => void;
}

export const useSpeechStore = create<SpeechState>((set) => ({
  lastSpoken: "",
  lastAssertive: "",
  lastSpokenAt: 0,
  speaking: false,
  settings: { ...DEFAULT_SETTINGS },
  politeLive: "",
  assertiveLive: "",
  voices: [],
  helpOpen: false,
  settingsOpen: false,
  setLastSpoken: (text) => set({ lastSpoken: text }),
  setLastAssertive: (text) => set({ lastAssertive: text }),
  markSpokenAt: () => set({ lastSpokenAt: Date.now() }),
  setSpeaking: (speaking) => set({ speaking }),
  setLive: (text, mode) =>
    set(mode === "assertive" ? { assertiveLive: text } : { politeLive: text }),
  setSettings: (patch) =>
    set((state) => {
      const settings = {
        ...state.settings,
        ...patch,
        rate: clampRate(patch.rate ?? state.settings.rate),
      };
      persistSpeechSettings(settings);
      return { settings };
    }),
  setVoices: (voices) => set({ voices }),
  setHelpOpen: (helpOpen) => set({ helpOpen }),
  setSettingsOpen: (settingsOpen) => set({ settingsOpen }),
}));
