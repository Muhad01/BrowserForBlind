import { resetDisconnectNarration } from "@/lib/disconnectNarration";
import { resetHeartbeatState } from "@/lib/speechGate";
import { resetNarrationPolicy } from "@/lib/narrationPolicy";
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
  resetNarrationPolicy();
  resetDisconnectNarration();
  resetHeartbeatState();
  useAuthStore.setState({ user: null, status: "unknown" });
  useConnectionStore.getState().client?.disconnect();
  useConnectionStore.setState({ status: "closed", client: null });
  useTaskStore.setState({
    task: null,
    events: [],
    pendingConfirmation: null,
    latestSpeak: "",
    perception: null,
  });
  useVoiceStore.setState({
    supported: true,
    listening: false,
    processing: false,
    pendingRequestId: null,
    lastTranscript: "",
    lastInterim: "",
    lastError: null,
  });
  useSpeechStore.setState({
    lastSpoken: "",
    lastAssertive: "",
    lastSpokenAt: 0,
    speaking: false,
    settings: { rate: 1.1, voiceURI: "", outputMode: "voice", verbosity: "brief", talkMode: "press" },
    politeLive: "",
    assertiveLive: "",
    voices: [],
    helpOpen: false,
    settingsOpen: false,
  });
}
