"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { LoginForm } from "@/components/LoginForm";
import { StatusRegions } from "@/components/StatusRegions";
import { VoiceConsole, useConsoleActions } from "@/components/VoiceConsole";
import styles from "@/components/console.module.css";
import { useKeyboardShortcuts } from "@/hooks/useKeyboardShortcuts";
import { useRealtime } from "@/hooks/useRealtime";
import { useVoiceInput } from "@/hooks/useVoiceInput";
import { useSpeechSynthesis } from "@/hooks/useSpeechSynthesis";
import { ensureCsrfCookie, fetchMe } from "@/lib/api";
import { unlockAudio } from "@/lib/earcons";
import { sendStopTask, sendVoiceCommand, type TranscriptHandlers } from "@/lib/handleTranscript";
import { msg } from "@/lib/i18n";
import { HELP_SPEAK } from "@/lib/phrases";
import { useSpeechStore } from "@/stores/speechStore";
import { useAuthStore } from "@/stores/authStore";
import { useConnectionStore } from "@/stores/connectionStore";
import { useTaskStore } from "@/stores/taskStore";
import { useVoiceStore } from "@/stores/voiceStore";

export default function HomePage() {
  const [started, setStarted] = useState(false);
  const user = useAuthStore((state) => state.user);
  const authStatus = useAuthStore((state) => state.status);
  const { speak, cancel, bargeIn, repeatLast, unlock } = useSpeechSynthesis();
  const startButtonRef = useRef<HTMLButtonElement>(null);

  const client = useRealtime({
    enabled: started && Boolean(user),
    speak,
  });

  const handlersRef = useRef<TranscriptHandlers>({
    sendVoiceCommand: (text, extra) => sendVoiceCommand(useConnectionStore.getState().client, text, extra),
    repeatLast,
    openHelp: () => speak(HELP_SPEAK, { priority: "assertive" }),
  });

  useEffect(() => {
    handlersRef.current = {
      sendVoiceCommand: (text, extra) => sendVoiceCommand(useConnectionStore.getState().client, text, extra),
      repeatLast,
      openHelp: () => speak(HELP_SPEAK, { priority: "assertive" }),
    };
  }, [repeatLast, speak]);

  const transcriptHandlers = useMemo<TranscriptHandlers>(
    () => ({
      sendVoiceCommand: (text, extra) => handlersRef.current.sendVoiceCommand(text, extra),
      repeatLast: () => handlersRef.current.repeatLast(),
      openHelp: () => handlersRef.current.openHelp(),
    }),
    [],
  );

  const { toggleListening, startListening, stopListening, closeMic, warmMic } = useVoiceInput({
    handlers: transcriptHandlers,
    bargeIn,
    speakAssertive: (text, lang) => speak(text, { priority: "assertive", event: "local", lang }),
  });

  const interrupt = useCallback(() => {
    closeMic();
    cancel();
    const status = useTaskStore.getState().task?.status;
    if (status === "running" || status === "pending" || status === "waiting_confirmation") {
      sendStopTask(useConnectionStore.getState().client);
    }
  }, [cancel, closeMic]);

  const actions = useConsoleActions({
    client,
    speak,
    cancelSpeech: cancel,
    closeMic,
    startListening: () => {
      void startListening();
    },
    stopListening,
    toggleListening,
    repeatLast,
  });

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
    void warmMic();
    const lang = useSpeechStore.getState().settings.language === "ur" ? "ur" : "en";
    speak(msg("welcome", lang), { priority: "assertive", lang });
    if (!useVoiceStore.getState().supported) {
      speak(msg("voiceUnsupported", lang), { priority: "assertive", lang });
    }
  }, [speak, unlock, warmMic]);

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
          onInterrupt={interrupt}
          onSpeakHelp={() => speak(HELP_SPEAK, { priority: "assertive" })}
        />
      ) : null}
    </div>
  );
}
