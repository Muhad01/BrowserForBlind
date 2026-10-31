"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { LoginForm } from "@/components/LoginForm";
import { StatusRegions } from "@/components/StatusRegions";
import { VoiceConsole, useConsoleActions } from "@/components/VoiceConsole";
import styles from "@/components/console.module.css";
import { useKeyboardShortcuts } from "@/hooks/useKeyboardShortcuts";
import { useRealtime } from "@/hooks/useRealtime";
import { useSpeechRecognition } from "@/hooks/useSpeechRecognition";
import { useSpeechSynthesis } from "@/hooks/useSpeechSynthesis";
import { ensureCsrfCookie, fetchMe } from "@/lib/api";
import { unlockAudio } from "@/lib/earcons";
import { sendVoiceCommand, type TranscriptHandlers } from "@/lib/handleTranscript";
import { HELP_SPEAK, VOICE_UNSUPPORTED_SPEAK, WELCOME_SPEAK } from "@/lib/phrases";
import { useAuthStore } from "@/stores/authStore";
import { useConnectionStore } from "@/stores/connectionStore";
import { useVoiceStore } from "@/stores/voiceStore";

export default function HomePage() {
  const [started, setStarted] = useState(false);
  const user = useAuthStore((state) => state.user);
  const authStatus = useAuthStore((state) => state.status);
  const { speak, cancel, repeatLast, unlock } = useSpeechSynthesis();
  const startButtonRef = useRef<HTMLButtonElement>(null);

  const client = useRealtime({
    enabled: started && Boolean(user),
    speak,
  });

  const handlersRef = useRef<TranscriptHandlers>({
    sendVoiceCommand: (text) => sendVoiceCommand(useConnectionStore.getState().client, text),
    repeatLast,
    openHelp: () => speak(HELP_SPEAK, { priority: "assertive" }),
  });

  useEffect(() => {
    handlersRef.current = {
      sendVoiceCommand: (text) => sendVoiceCommand(useConnectionStore.getState().client, text),
      repeatLast,
      openHelp: () => speak(HELP_SPEAK, { priority: "assertive" }),
    };
  }, [repeatLast, speak]);

  const transcriptHandlers = useMemo<TranscriptHandlers>(
    () => ({
      sendVoiceCommand: (text) => handlersRef.current.sendVoiceCommand(text),
      repeatLast: () => handlersRef.current.repeatLast(),
      openHelp: () => handlersRef.current.openHelp(),
    }),
    [],
  );

  const { toggleListening } = useSpeechRecognition({
    handlers: transcriptHandlers,
    cancelSpeech: cancel,
    speakAssertive: (text) => speak(text, { priority: "assertive" }),
  });

  const actions = useConsoleActions(client, speak, cancel, toggleListening, repeatLast);

  useKeyboardShortcuts(started && Boolean(user), actions.handleShortcut);

  useEffect(() => {
    startButtonRef.current?.focus();
  }, []);

  useEffect(() => {
    if (!started) {
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        await ensureCsrfCookie();
        const me = await fetchMe();
        if (cancelled) {
          return;
        }
        if (me) {
          useAuthStore.getState().setUser(me);
        } else {
          useAuthStore.getState().setUnauthenticated();
        }
      } catch {
        if (!cancelled) {
          useAuthStore.getState().setUnauthenticated();
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [started]);

  const begin = useCallback(() => {
    unlockAudio();
    unlock();
    setStarted(true);
    speak(WELCOME_SPEAK, { priority: "assertive" });
    if (!useVoiceStore.getState().supported) {
      speak(VOICE_UNSUPPORTED_SPEAK, { priority: "assertive" });
    }
  }, [speak, unlock]);

  return (
    <div className={styles.page}>
      <StatusRegions />
      {!started ? (
        <div className={styles.start}>
          <div className={styles.startInner}>
            <h1>CIGHT Browser. Press Enter to start.</h1>
            <button ref={startButtonRef} className={styles.primary} type="button" onClick={begin}>
              Press Enter to start
            </button>
          </div>
        </div>
      ) : null}

      {started && authStatus === "unknown" ? (
        <div className={styles.shell}>
          <p>Checking whether you are signed in.</p>
        </div>
      ) : null}

      {started && authStatus === "unauthenticated" ? (
        <div className={styles.shell}>
          <LoginForm onError={(message) => speak(message, { priority: "assertive" })} />
        </div>
      ) : null}

      {started && user ? (
        <VoiceConsole
          client={client}
          onToggleListen={toggleListening}
          onRepeat={repeatLast}
          onCancelSpeech={cancel}
          onSpeakHelp={() => speak(HELP_SPEAK, { priority: "assertive" })}
        />
      ) : null}
    </div>
  );
}
