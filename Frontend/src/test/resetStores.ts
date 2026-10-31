import { useAuthStore } from "@/stores/authStore";
import { useConnectionStore } from "@/stores/connectionStore";
import { useSpeechStore } from "@/stores/speechStore";
import { useTaskStore } from "@/stores/taskStore";
import { useVoiceStore } from "@/stores/voiceStore";

export function resetStores() {
  try {
    localStorage.clear();
  } catch {
    // jsdom may not expose storage in every test.
  }
  useAuthStore.setState({ user: null, status: "unknown" });
  useConnectionStore.setState({ status: "closed", client: null });
  useTaskStore.setState({
    task: null,
    events: [],
    pendingConfirmation: null,
    latestSpeak: "",
  });
  useVoiceStore.setState({
    supported: true,
    listening: false,
    lastTranscript: "",
    lastInterim: "",
    lastError: null,
  });
  useSpeechStore.setState({
    lastSpoken: "",
    speaking: false,
    settings: { rate: 1.1, voiceURI: "", outputMode: "voice" },
    politeLive: "",
    assertiveLive: "",
    voices: [],
    helpOpen: false,
    settingsOpen: false,
  });
}
