"use client";

import { useEffect, useId, useRef } from "react";

import styles from "@/components/console.module.css";
import { msg, type UiLanguage } from "@/lib/i18n";
import { useSpeechStore } from "@/stores/speechStore";

export function HelpDialog() {
  const open = useSpeechStore((state) => state.helpOpen);
  const language = useSpeechStore((state) => state.settings.language);
  const dialogRef = useRef<HTMLDialogElement>(null);
  const headingId = useId();
  const lang: UiLanguage = language === "ur" ? "ur" : "en";

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
      onClose={() => useSpeechStore.getState().setHelpOpen(false)}
    >
      <h2 id={headingId}>{msg("help", lang)}</h2>
      <p>{msg("helpSpeak", lang)}</p>
      <ul>
        <li>Space: start or stop listening. In hold mode, hold Space to talk and release to send.</li>
        <li>Escape: stop speech and the current task</li>
        <li>Shift+Escape or &quot;close the browser&quot;: close Chromium</li>
        <li>L: cycle language (automatic, English, Urdu)</li>
        <li>G: switch male or female voice</li>
        <li>T: switch between press and hold talk modes</li>
        <li>V: switch between brief and detailed narration</li>
        <li>R: repeat the last important message</li>
        <li>H: help</li>
        <li>S: settings</li>
      </ul>
      <button className={styles.secondary} type="button" onClick={() => dialogRef.current?.close()}>
        {msg("closeHelp", lang)}
      </button>
    </dialog>
  );
}
