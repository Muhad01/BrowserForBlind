"use client";

import { FormEvent, useCallback, useMemo, useState } from "react";

import { ConfirmationPrompt } from "@/components/ConfirmationPrompt";
import { EventLog } from "@/components/EventLog";
import { HelpDialog } from "@/components/HelpDialog";
import { SettingsPanel } from "@/components/SettingsPanel";
import styles from "@/components/console.module.css";
import { logout } from "@/lib/api";
import { sendConfirmation, sendStopTask, sendVoiceCommand } from "@/lib/handleTranscript";
import { classifyTranscript } from "@/lib/phrases";
import { HELP_SPEAK, VOICE_UNSUPPORTED_SPEAK } from "@/lib/phrases";
import type { ShortcutAction } from "@/lib/shortcuts";
import type { WsClient } from "@/lib/wsClient";
import { useAuthStore } from "@/stores/authStore";
import { useConnectionStore } from "@/stores/connectionStore";
import { useSpeechStore } from "@/stores/speechStore";
import { useTaskStore } from "@/stores/taskStore";
import { useVoiceStore } from "@/stores/voiceStore";

interface VoiceConsoleProps {
  client: WsClient | null;
  onToggleListen: () => void;
  onRepeat: () => void;
  onCancelSpeech: () => void;
  onSpeakHelp: () => void;
}

function connectionLabel(status: string): string {
  if (status === "open") {
    return "Connected";
  }
  if (status === "connecting") {
    return "Connecting";
  }
  if (status === "reconnecting") {
    return "Reconnecting";
  }
  return "Disconnected";
}

function mainStateWord(options: {
  listening: boolean;
  confirmation: boolean;
  taskStatus: string | undefined;
}): string {
  if (options.confirmation) {
    return "Waiting for your answer";
  }
  if (options.listening) {
    return "Listening";
  }
  const status = options.taskStatus;
  if (status === "running" || status === "pending" || status === "waiting_confirmation") {
    return "Working";
  }
  if (status === "completed") {
    return "Done";
  }
  if (status === "failed" || status === "cancelled") {
    return "Problem";
  }
  return "Ready";
}

export function VoiceConsole({
  client,
  onToggleListen,
  onRepeat,
  onCancelSpeech,
  onSpeakHelp,
}: VoiceConsoleProps) {
  const user = useAuthStore((state) => state.user);
  const connection = useConnectionStore((state) => state.status);
  const task = useTaskStore((state) => state.task);
  const latestSpeak = useTaskStore((state) => state.latestSpeak);
  const confirmation = useTaskStore((state) => state.pendingConfirmation);
  const listening = useVoiceStore((state) => state.listening);
  const lastTranscript = useVoiceStore((state) => state.lastTranscript);
  const lastInterim = useVoiceStore((state) => state.lastInterim);
  const lastError = useVoiceStore((state) => state.lastError);
  const supported = useVoiceStore((state) => state.supported);
  const [typed, setTyped] = useState("");

  const stateWord = mainStateWord({
    listening,
    confirmation: Boolean(confirmation),
    taskStatus: task?.status,
  });

  const submitTyped = useCallback(
    (event: FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      const text = typed.trim();
      if (!text) {
        return;
      }
      useVoiceStore.getState().setTranscript(text);
      const kind = classifyTranscript(text);
      if (kind === "repeat") {
        onRepeat();
      } else if (kind === "help") {
        useSpeechStore.getState().setHelpOpen(true);
        onSpeakHelp();
      } else {
        sendVoiceCommand(client, text);
      }
      setTyped("");
    },
    [client, onRepeat, onSpeakHelp, typed],
  );

  const respond = useCallback(
    (approved: boolean) => {
      const pending = useTaskStore.getState().pendingConfirmation;
      if (!pending) {
        return;
      }
      sendConfirmation(client, pending.confirmation_id, pending.token, approved);
      useTaskStore.getState().clearConfirmation();
    },
    [client],
  );

  const stopTask = useCallback(() => {
    sendStopTask(client);
    onCancelSpeech();
  }, [client, onCancelSpeech]);

  async function onSignOut() {
    try {
      await logout();
    } finally {
      useAuthStore.getState().clearAuth();
    }
  }

  return (
    <div className={styles.shell}>
      <header className={styles.header}>
        <h1 className={styles.brand}>CIGHT Browser</h1>
        <div className={styles.meta}>
          <p className={styles.statusText}>Connection: {connectionLabel(connection)}</p>
          <p>Signed in as {user?.username ?? "unknown"}</p>
          <button className={styles.secondary} type="button" onClick={() => void onSignOut()}>
            Sign out
          </button>
        </div>
      </header>

      <section className={styles.card} aria-labelledby="main-status-heading">
        <h2 id="main-status-heading" className={styles.stateWord}>
          {stateWord}
        </h2>
        <p className={styles.latestSpeak}>{latestSpeak || "No spoken update yet."}</p>
        <p className={styles.youSaid}>You said: {lastTranscript || lastInterim || "nothing yet"}</p>
        {lastError ? <p className={styles.formError}>{lastError}</p> : null}
        {!supported ? <p>{VOICE_UNSUPPORTED_SPEAK}</p> : null}

        <div className={styles.actions}>
          <button className={styles.primary} type="button" onClick={onToggleListen}>
            {listening ? "Stop listening (Space)" : "Speak (Space)"}
          </button>
          <button className={styles.danger} type="button" onClick={stopTask}>
            Stop (Escape)
          </button>
        </div>

        <div className={styles.shortcutRow}>
          <button className={styles.secondary} type="button" onClick={onRepeat}>
            Repeat last message (R)
          </button>
          <button
            className={styles.secondary}
            type="button"
            onClick={() => {
              useSpeechStore.getState().setHelpOpen(true);
              onSpeakHelp();
            }}
          >
            Help (H)
          </button>
          <button
            className={styles.secondary}
            type="button"
            onClick={() => useSpeechStore.getState().setSettingsOpen(true)}
          >
            Settings (S)
          </button>
        </div>

        {confirmation ? <ConfirmationPrompt confirmation={confirmation} onRespond={respond} /> : null}

        <details open={!supported}>
          <summary>Type a command instead</summary>
          <form onSubmit={submitTyped}>
            <div className={styles.field}>
              <label htmlFor="typed-command">Command</label>
              <input
                id="typed-command"
                className={styles.input}
                value={typed}
                onChange={(event) => setTyped(event.target.value)}
                placeholder="Search Wikipedia for artificial intelligence"
              />
            </div>
            <button className={styles.secondary} type="submit">
              Send command
            </button>
          </form>
        </details>
      </section>

      <EventLog />
      <HelpDialog />
      <SettingsPanel />
    </div>
  );
}

export function useConsoleActions(
  client: WsClient | null,
  speak: (text: string, options?: { priority?: "polite" | "assertive"; event?: string }) => void,
  cancelSpeech: () => void,
  toggleListening: () => void,
  repeatLast: () => void,
) {
  return useMemo(
    () => ({
      handleShortcut(action: ShortcutAction) {
        if (action === "toggle-listen") {
          toggleListening();
          return;
        }
        if (action === "stop") {
          sendStopTask(client);
          cancelSpeech();
          return;
        }
        if (action === "repeat") {
          repeatLast();
          return;
        }
        if (action === "help") {
          useSpeechStore.getState().setHelpOpen(true);
          speak(HELP_SPEAK, { priority: "assertive" });
          return;
        }
        if (action === "settings") {
          useSpeechStore.getState().setSettingsOpen(true);
          return;
        }
        const pending = useTaskStore.getState().pendingConfirmation;
        if (!pending) {
          return;
        }
        if (action === "confirm-yes") {
          sendConfirmation(client, pending.confirmation_id, pending.token, true);
          useTaskStore.getState().clearConfirmation();
        }
        if (action === "confirm-no") {
          sendConfirmation(client, pending.confirmation_id, pending.token, false);
          useTaskStore.getState().clearConfirmation();
        }
      },
    }),
    [cancelSpeech, client, repeatLast, speak, toggleListening],
  );
}
