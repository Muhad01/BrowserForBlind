"use client";

import styles from "@/components/console.module.css";
import { useSpeechStore } from "@/stores/speechStore";

export function StatusRegions() {
  const politeLive = useSpeechStore((state) => state.politeLive);
  const assertiveLive = useSpeechStore((state) => state.assertiveLive);

  return (
    <>
      <div className={styles.hidden} role="status" aria-live="polite" aria-atomic="true">
        {politeLive}
      </div>
      <div className={styles.hidden} role="alert" aria-live="assertive" aria-atomic="true">
        {assertiveLive}
      </div>
    </>
  );
}
