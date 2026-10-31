"use client";

import { useEffect, useId, useRef } from "react";

import styles from "@/components/console.module.css";
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
      <h2 id={headingId}>Settings</h2>
      <div className={styles.field}>
        <label htmlFor={modeId}>Output mode</label>
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
        <label htmlFor={rateId}>Speech rate ({settings.rate.toFixed(1)})</label>
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
      <div className={styles.field}>
        <label htmlFor={voiceId}>Voice</label>
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
        Close settings
      </button>
    </dialog>
  );
}
