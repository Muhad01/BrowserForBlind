"use client";

import styles from "@/components/console.module.css";
import type { PendingConfirmation } from "@/lib/events";

interface ConfirmationPromptProps {
  confirmation: PendingConfirmation;
  onRespond: (approved: boolean) => void;
}

export function ConfirmationPrompt({ confirmation, onRespond }: ConfirmationPromptProps) {
  return (
    <section className={styles.confirmBox} aria-labelledby="confirmation-heading">
      <h2 id="confirmation-heading">Waiting for your answer</h2>
      <p>{confirmation.speak}</p>
      <div className={styles.shortcutRow}>
        <button className={styles.primary} type="button" onClick={() => onRespond(true)}>
          Yes (Y)
        </button>
        <button className={styles.danger} type="button" onClick={() => onRespond(false)}>
          No (N)
        </button>
      </div>
    </section>
  );
}
