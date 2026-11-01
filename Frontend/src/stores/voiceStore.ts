import { create } from "zustand";

import { PROCESSING_MS } from "@/lib/speechGate";

let processingTimer: ReturnType<typeof setTimeout> | null = null;

interface VoiceState {
  supported: boolean;
  listening: boolean;
  processing: boolean;
  pendingRequestId: string | null;
  lastTranscript: string;
  lastInterim: string;
  lastError: string | null;
  level: number;
  statusWord: string;
  spokenText: string;
  lastLanguage: "en" | "ur" | "mixed";
  forceBrowserOnce: boolean;
  setSupported: (supported: boolean) => void;
  setListening: (listening: boolean) => void;
  setTranscript: (transcript: string) => void;
  setInterim: (interim: string) => void;
  setError: (error: string | null) => void;
  setLevel: (level: number) => void;
  setStatusWord: (statusWord: string) => void;
  setSpokenText: (spokenText: string, language?: "en" | "ur" | "mixed") => void;
  setForceBrowserOnce: (force: boolean) => void;
  beginProcessing: (requestId: string) => void;
  endProcessing: (requestId?: string | null) => void;
}

export const useVoiceStore = create<VoiceState>((set, get) => ({
  supported: true,
  listening: false,
  processing: false,
  pendingRequestId: null,
  lastTranscript: "",
  lastInterim: "",
  lastError: null,
  level: 0,
  statusWord: "",
  spokenText: "",
  lastLanguage: "en",
  forceBrowserOnce: false,
  setSupported: (supported) => set({ supported }),
  setListening: (listening) => set({ listening }),
  setTranscript: (transcript) => set({ lastTranscript: transcript, lastInterim: "" }),
  setInterim: (interim) => set({ lastInterim: interim }),
  setError: (error) => set({ lastError: error }),
  setLevel: (level) => set({ level }),
  setStatusWord: (statusWord) => set({ statusWord }),
  setSpokenText: (spokenText, language) =>
    set({ spokenText, lastLanguage: language ?? get().lastLanguage }),
  setForceBrowserOnce: (forceBrowserOnce) => set({ forceBrowserOnce }),
  beginProcessing: (requestId) => {
    if (processingTimer) {
      clearTimeout(processingTimer);
    }
    processingTimer = setTimeout(() => {
      useVoiceStore.getState().endProcessing();
    }, PROCESSING_MS);
    set({ processing: true, pendingRequestId: requestId });
  },
  endProcessing: (requestId) => {
    if (requestId && get().pendingRequestId && requestId !== get().pendingRequestId) {
      return;
    }
    if (processingTimer) {
      clearTimeout(processingTimer);
      processingTimer = null;
    }
    set({ processing: false, pendingRequestId: null });
  },
}));
