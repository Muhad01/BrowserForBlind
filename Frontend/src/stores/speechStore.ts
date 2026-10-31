import { create } from "zustand";

export type OutputMode = "voice" | "screenreader";

export interface SpeechSettings {
  rate: number;
  voiceURI: string;
  outputMode: OutputMode;
}

const STORAGE_KEY = "cight-speech-settings";
const DEFAULT_SETTINGS: SpeechSettings = {
  rate: 1.1,
  voiceURI: "",
  outputMode: "voice",
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
      outputMode: parsed.outputMode === "screenreader" ? "screenreader" : "voice",
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
  speaking: boolean;
  settings: SpeechSettings;
  politeLive: string;
  assertiveLive: string;
  voices: SpeechSynthesisVoice[];
  helpOpen: boolean;
  settingsOpen: boolean;
  setLastSpoken: (text: string) => void;
  setSpeaking: (speaking: boolean) => void;
  setLive: (text: string, mode: "polite" | "assertive") => void;
  setSettings: (patch: Partial<SpeechSettings>) => void;
  setVoices: (voices: SpeechSynthesisVoice[]) => void;
  setHelpOpen: (open: boolean) => void;
  setSettingsOpen: (open: boolean) => void;
}

export const useSpeechStore = create<SpeechState>((set) => ({
  lastSpoken: "",
  speaking: false,
  settings: { ...DEFAULT_SETTINGS },
  politeLive: "",
  assertiveLive: "",
  voices: [],
  helpOpen: false,
  settingsOpen: false,
  setLastSpoken: (text) => set({ lastSpoken: text }),
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
