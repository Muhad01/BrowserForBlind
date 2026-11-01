"use client";

import { useEffect, useId, useRef } from "react";

import styles from "@/components/console.module.css";
import { msg, type UiLanguage } from "@/lib/i18n";
import { useSpeechStore } from "@/stores/speechStore";

export function SettingsPanel() {
  const open = useSpeechStore((state) => state.settingsOpen);
  const settings = useSpeechStore((state) => state.settings);
  const voices = useSpeechStore((state) => state.voices);
  const dialogRef = useRef<HTMLDialogElement>(null);
  const headingId = useId();
  const rateId = useId();
  const voiceId = useId();
  const modeId = useId();
  const verbosityId = useId();
  const talkModeId = useId();
  const languageId = useId();
  const engineId = useId();
  const genderId = useId();
  const lang: UiLanguage = settings.language === "ur" ? "ur" : "en";

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) {
      return;
    }
    if (open && !dialog.open) {
      dialog.showModal();
    } else if (!open && dialog.open) {
      dialog.close();
    }
  }, [open]);

  return (
    <dialog
      ref={dialogRef}
      className={styles.dialog}
      aria-labelledby={headingId}
      onClose={() => useSpeechStore.getState().setSettingsOpen(false)}
    >
      <h2 id={headingId}>{msg("settings", lang)}</h2>
      <div className={styles.field}>
        <label htmlFor={languageId}>{msg("language", lang)}</label>
        <select
          id={languageId}
          className={styles.select}
          value={settings.language}
          onChange={(event) =>
            useSpeechStore.getState().setSettings({
              language: event.target.value === "ur" || event.target.value === "en" ? event.target.value : "auto",
            })
          }
        >
          <option value="auto">{msg("automatic", lang)}</option>
          <option value="en">{msg("english", lang)}</option>
          <option value="ur">{msg("urdu", lang)}</option>
        </select>
      </div>
      <div className={styles.field}>
        <label htmlFor={engineId}>{msg("sttEngine", lang)}</label>
        <select
          id={engineId}
          className={styles.select}
          value={settings.sttEngine}
          onChange={(event) =>
            useSpeechStore.getState().setSettings({
              sttEngine: event.target.value === "browser" ? "browser" : "gemini",
            })
          }
        >
          <option value="gemini">{msg("engineGemini", lang)}</option>
          <option value="browser">{msg("engineBrowser", lang)}</option>
        </select>
      </div>
      <div className={styles.field}>
        <label htmlFor={modeId}>{msg("outputMode", lang)}</label>
        <select
          id={modeId}
          className={styles.select}
          value={settings.outputMode}
          onChange={(event) =>
            useSpeechStore.getState().setSettings({
              outputMode: event.target.value === "screenreader" ? "screenreader" : "voice",
            })
          }
        >
          <option value="voice">Voice and screen reader</option>
          <option value="screenreader">Screen reader only</option>
        </select>
      </div>
      <div className={styles.field}>
        <label htmlFor={rateId}>
          {msg("speechRate", lang)} ({settings.rate.toFixed(1)})
        </label>
        <input
          id={rateId}
          className={styles.input}
          type="range"
          min={0.8}
          max={1.6}
          step={0.1}
          value={settings.rate}
          onChange={(event) => useSpeechStore.getState().setSettings({ rate: Number(event.target.value) })}
        />
      </div>
      <fieldset className={styles.fieldset} aria-labelledby={verbosityId}>
        <legend id={verbosityId}>{msg("narrationDetail", lang)}</legend>
        <label className={styles.radio}>
          <input
            type="radio"
            name="verbosity"
            value="brief"
            checked={settings.verbosity === "brief"}
            onChange={() => useSpeechStore.getState().setSettings({ verbosity: "brief" })}
          />
          {msg("brief", lang)}
        </label>
        <label className={styles.radio}>
          <input
            type="radio"
            name="verbosity"
            value="detailed"
            checked={settings.verbosity === "detailed"}
            onChange={() => useSpeechStore.getState().setSettings({ verbosity: "detailed" })}
          />
          {msg("detailed", lang)}
        </label>
      </fieldset>
      <fieldset className={styles.fieldset} aria-labelledby={talkModeId}>
        <legend id={talkModeId}>{msg("talkMode", lang)}</legend>
        <label className={styles.radio}>
          <input
            type="radio"
            name="talkMode"
            value="press"
            checked={settings.talkMode === "press"}
            onChange={() => useSpeechStore.getState().setSettings({ talkMode: "press" })}
          />
          {msg("pressTalk", lang)}
        </label>
        <label className={styles.radio}>
          <input
            type="radio"
            name="talkMode"
            value="hold"
            checked={settings.talkMode === "hold"}
            onChange={() => useSpeechStore.getState().setSettings({ talkMode: "hold" })}
          />
          {msg("holdTalk", lang)}
        </label>
      </fieldset>
      <fieldset className={styles.fieldset} aria-labelledby={genderId}>
        <legend id={genderId}>{msg("voice", lang)}</legend>
        <label className={styles.radio}>
          <input
            type="radio"
            name="voiceGender"
            value="female"
            checked={settings.voiceGender === "female"}
            onChange={() => useSpeechStore.getState().setSettings({ voiceGender: "female", voiceURI: "" })}
          />
          {msg("female", lang)}
        </label>
        <label className={styles.radio}>
          <input
            type="radio"
            name="voiceGender"
            value="male"
            checked={settings.voiceGender === "male"}
            onChange={() => useSpeechStore.getState().setSettings({ voiceGender: "male", voiceURI: "" })}
          />
          {msg("male", lang)}
        </label>
      </fieldset>
      <div className={styles.field}>
        <label htmlFor={voiceId}>{msg("specificVoice", lang)}</label>
        <select
          id={voiceId}
          className={styles.select}
          value={settings.voiceURI}
          onChange={(event) => useSpeechStore.getState().setSettings({ voiceURI: event.target.value })}
        >
          <option value="">Browser default</option>
          {voices.map((voice) => (
            <option key={voice.voiceURI} value={voice.voiceURI}>
              {voice.name} ({voice.lang})
            </option>
          ))}
        </select>
      </div>
      <button className={styles.secondary} type="button" onClick={() => dialogRef.current?.close()}>
        {msg("closeSettings", lang)}
      </button>
    </dialog>
  );
}
