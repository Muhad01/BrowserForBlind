"use client";

import { FormEvent, useCallback, useMemo, useState } from "react";

import { ConfirmationPrompt } from "@/components/ConfirmationPrompt";
import { EventLog } from "@/components/EventLog";
import { PageDescription } from "@/components/PageDescription";
import { HelpDialog } from "@/components/HelpDialog";
import { SettingsPanel } from "@/components/SettingsPanel";
import styles from "@/components/console.module.css";
import { logout } from "@/lib/api";
import { sendConfirmation, sendStopTask, sendVoiceCommand } from "@/lib/handleTranscript";
import { classifyTranscript } from "@/lib/phrases";
import { msg, type UiLanguage } from "@/lib/i18n";
import {
  BRIEF_MODE_SPEAK,
  DETAILED_MODE_SPEAK,
  HOLD_MODE_SPEAK,
  PRESS_MODE_SPEAK,
} from "@/lib/phrases";
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
  onInterrupt: () => void;
  onSpeakHelp: () => void;
}

function uiLang(): UiLanguage {
  return useSpeechStore.getState().settings.language === "ur" ? "ur" : "en";
}

function connectionLabel(status: string, lang: UiLanguage): string {
  if (status === "open") {
    return msg("connected", lang);
  }
  if (status === "connecting") {
    return msg("connecting", lang);
  }
  if (status === "reconnecting") {
    return msg("reconnecting", lang);
  }
  return msg("disconnected", lang);
}

function mainStateWord(options: {
  listening: boolean;
  confirmation: boolean;
  taskStatus: string | undefined;
  statusWord: string;
  lang: UiLanguage;
}): string {
  if (options.statusWord) {
    return options.statusWord;
  }
  if (options.confirmation) {
    return msg("waitingAnswer", options.lang);
  }
  if (options.listening) {
    return msg("listening", options.lang);
  }
  const status = options.taskStatus;
  if (status === "running" || status === "pending" || status === "waiting_confirmation") {
    return msg("working", options.lang);
  }
  if (status === "completed") {
    return msg("done", options.lang);
  }
  if (status === "failed" || status === "cancelled") {
    return msg("problem", options.lang);
  }
  return msg("ready", options.lang);
}

export function VoiceConsole({
  client,
  onToggleListen,
  onRepeat,
  onInterrupt,
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
  const spokenText = useVoiceStore((state) => state.spokenText);
  const lastLanguage = useVoiceStore((state) => state.lastLanguage);
  const level = useVoiceStore((state) => state.level);
  const statusWord = useVoiceStore((state) => state.statusWord);
  const languageSetting = useSpeechStore((state) => state.settings.language);
  const [typed, setTyped] = useState("");
  const lang: UiLanguage = languageSetting === "ur" ? "ur" : "en";
  const youSaid = spokenText || lastTranscript || lastInterim;
  const youSaidRtl = lastLanguage === "ur" || lastLanguage === "mixed";

  const stateWord = mainStateWord({
    listening,
    confirmation: Boolean(confirmation),
    taskStatus: task?.status,
    statusWord,
    lang,
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
    onInterrupt();
  }, [onInterrupt]);

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
          <p className={styles.statusText}>
            {msg("connection", lang)}: {connectionLabel(connection, lang)}
          </p>
          <p>
            {msg("signedInAs", lang)} {user?.username ?? "unknown"}
          </p>
          <button className={styles.secondary} type="button" onClick={() => void onSignOut()}>
            {msg("signOut", lang)}
          </button>
        </div>
      </header>

      <section className={styles.card} aria-labelledby="main-status-heading">
        <h2 id="main-status-heading" className={styles.stateWord}>
          {stateWord}
        </h2>
        <p className={styles.latestSpeak}>{latestSpeak || msg("noSpoken", lang)}</p>
        <p className={styles.youSaid} dir={youSaidRtl ? "rtl" : "ltr"}>
          {msg("youSaid", lang)}: {youSaid || msg("nothingYet", lang)}
        </p>
        {listening ? (
          <div
            className={styles.levelMeter}
            role="meter"
            aria-label={msg("listening", lang)}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={Math.round(level * 100)}
          >
            <span className={styles.levelFill} style={{ width: `${Math.round(level * 100)}%` }} />
          </div>
        ) : null}
        {lastError ? <p className={styles.formError}>{lastError}</p> : null}
        {!supported ? <p>{msg("voiceUnsupported", lang)}</p> : null}

        <div className={styles.actions}>
          <button className={styles.primary} type="button" onClick={onToggleListen}>
            {listening ? msg("stopListening", lang) : msg("speak", lang)}
          </button>
          <button className={styles.danger} type="button" onClick={stopTask}>
            {msg("stopEscape", lang)}
          </button>
        </div>

        <div className={styles.shortcutRow}>
          <button className={styles.secondary} type="button" onClick={onRepeat}>
            {msg("repeat", lang)}
          </button>
          <button
            className={styles.secondary}
            type="button"
            onClick={() => {
              useSpeechStore.getState().setHelpOpen(true);
              onSpeakHelp();
            }}
          >
            {msg("help", lang)}
          </button>
          <button
            className={styles.secondary}
            type="button"
            onClick={() => useSpeechStore.getState().setSettingsOpen(true)}
          >
            {msg("settings", lang)}
          </button>
        </div>

        {confirmation ? <ConfirmationPrompt confirmation={confirmation} onRespond={respond} /> : null}

        <details open={!supported}>
          <summary>{msg("typeInstead", lang)}</summary>
          <form onSubmit={submitTyped}>
            <div className={styles.field}>
              <label htmlFor="typed-command">{msg("command", lang)}</label>
              <input
                id="typed-command"
                className={styles.input}
                value={typed}
                onChange={(event) => setTyped(event.target.value)}
                placeholder="Search Wikipedia for artificial intelligence"
              />
            </div>
            <button className={styles.secondary} type="submit">
              {msg("sendCommand", lang)}
            </button>
          </form>
        </details>
      </section>

      <PageDescription />
      <EventLog />
      <HelpDialog />
      <SettingsPanel />
    </div>
  );
}

export function interruptSession(
  client: WsClient | null,
  closeMic: () => void,
  cancelSpeech: () => void,
): void {
  closeMic();
  cancelSpeech();
  const status = useTaskStore.getState().task?.status;
  if (status === "running" || status === "pending" || status === "waiting_confirmation") {
    sendStopTask(client);
  }
}

export function useConsoleActions(options: {
  client: WsClient | null;
  speak: (text: string, options?: { priority?: "polite" | "assertive"; event?: string; lang?: string }) => void;
  cancelSpeech: () => void;
  closeMic: () => void;
  startListening: () => void;
  stopListening: () => void;
  toggleListening: () => void;
  repeatLast: () => void;
}) {
  const { client, speak, cancelSpeech, closeMic, startListening, stopListening, toggleListening, repeatLast } =
    options;
  return useMemo(
    () => ({
      handleShortcut(action: ShortcutAction) {
        if (action === "toggle-listen") {
          toggleListening();
          return;
        }
        if (action === "listen-start") {
          void startListening();
          return;
        }
        if (action === "listen-stop") {
          stopListening();
          return;
        }
        if (action === "stop") {
          interruptSession(client, closeMic, cancelSpeech);
          return;
        }
        if (action === "repeat") {
          repeatLast();
          return;
        }
        if (action === "help") {
          const lang = uiLang();
          useSpeechStore.getState().setHelpOpen(true);
          speak(msg("helpSpeak", lang), { priority: "assertive", event: "local", lang });
          return;
        }
        if (action === "close-browser") {
          sendVoiceCommand(client, "close the browser");
          return;
        }
        if (action === "cycle-language") {
          const current = useSpeechStore.getState().settings.language;
          const next = current === "auto" ? "en" : current === "en" ? "ur" : "auto";
          useSpeechStore.getState().setSettings({ language: next });
          const spokenLang = next === "ur" ? "ur" : "en";
          const key = next === "auto" ? "languageAuto" : next === "en" ? "languageEn" : "languageUr";
          speak(msg(key, next === "ur" ? "ur" : "en"), { priority: "assertive", event: "local", lang: spokenLang });
          return;
        }
        if (action === "toggle-voice-gender") {
          const current = useSpeechStore.getState().settings.voiceGender;
          const next = current === "female" ? "male" : "female";
          useSpeechStore.getState().setSettings({ voiceGender: next });
          const lang = uiLang();
          speak(msg("voiceNow", lang), { priority: "assertive", event: "local", lang });
          return;
        }
        if (action === "settings") {
          useSpeechStore.getState().setSettingsOpen(true);
          return;
        }
        if (action === "toggle-verbosity") {
          const current = useSpeechStore.getState().settings.verbosity;
          const next = current === "brief" ? "detailed" : "brief";
          useSpeechStore.getState().setSettings({ verbosity: next });
          speak(next === "brief" ? BRIEF_MODE_SPEAK : DETAILED_MODE_SPEAK, {
            priority: "assertive",
            event: "local",
          });
          return;
        }
        if (action === "toggle-talk-mode") {
          const current = useSpeechStore.getState().settings.talkMode;
          const next = current === "press" ? "hold" : "press";
          useSpeechStore.getState().setSettings({ talkMode: next });
          speak(next === "hold" ? HOLD_MODE_SPEAK : PRESS_MODE_SPEAK, {
            priority: "assertive",
            event: "local",
          });
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
    [cancelSpeech, client, closeMic, repeatLast, speak, startListening, stopListening, toggleListening],
  );
}
