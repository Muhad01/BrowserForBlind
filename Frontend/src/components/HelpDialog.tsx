"use client";

import { useEffect, useId, useRef } from "react";

import styles from "@/components/console.module.css";
import { HELP_SPEAK } from "@/lib/phrases";
import { useSpeechStore } from "@/stores/speechStore";

export function HelpDialog() {
  const open = useSpeechStore((state) => state.helpOpen);
  const dialogRef = useRef<HTMLDialogElement>(null);
  const headingId = useId();

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
      <h2 id={headingId}>Help</h2>
      <p>{HELP_SPEAK}</p>
      <ul>
        <li>Space: start or stop listening. In hold mode, hold Space to talk and release to send.</li>
        <li>T: switch between press and hold talk modes</li>
        <li>V: switch between brief and detailed narration</li>
        <li>Escape: close the microphone, silence speech, and stop the current task</li>
        <li>R: repeat the last important message</li>
        <li>H: help</li>
        <li>S: settings</li>
        <li>Y or N: answer a confirmation</li>
        <li>Headphones are recommended so the microphone does not hear the app.</li>
        <li>Say: what&apos;s on this page, read this page, continue, or ask a question about the page.</li>
      </ul>
      <button className={styles.secondary} type="button" onClick={() => dialogRef.current?.close()}>
        Close help
      </button>
    </dialog>
  );
}
