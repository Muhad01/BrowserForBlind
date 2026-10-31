import { create } from "zustand";

interface VoiceState {
  supported: boolean;
  listening: boolean;
  lastTranscript: string;
  lastInterim: string;
  lastError: string | null;
  setSupported: (supported: boolean) => void;
  setListening: (listening: boolean) => void;
  setTranscript: (transcript: string) => void;
  setInterim: (interim: string) => void;
  setError: (error: string | null) => void;
}

export const useVoiceStore = create<VoiceState>((set) => ({
  supported: true,
  listening: false,
  lastTranscript: "",
  lastInterim: "",
  lastError: null,
  setSupported: (supported) => set({ supported }),
  setListening: (listening) => set({ listening }),
  setTranscript: (transcript) => set({ lastTranscript: transcript, lastInterim: "" }),
  setInterim: (interim) => set({ lastInterim: interim }),
  setError: (error) => set({ lastError: error }),
}));
