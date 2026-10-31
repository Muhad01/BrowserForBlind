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
  setSupported: (supported: boolean) => void;
  setListening: (listening: boolean) => void;
  setTranscript: (transcript: string) => void;
  setInterim: (interim: string) => void;
  setError: (error: string | null) => void;
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
  setSupported: (supported) => set({ supported }),
  setListening: (listening) => set({ listening }),
  setTranscript: (transcript) => set({ lastTranscript: transcript, lastInterim: "" }),
  setInterim: (interim) => set({ lastInterim: interim }),
  setError: (error) => set({ lastError: error }),
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
