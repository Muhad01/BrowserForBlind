"use client";

import styles from "@/components/console.module.css";
import { useTaskStore } from "@/stores/taskStore";

function operationLabel(operation: string): string {
  if (operation === "read" || operation === "read_more") {
    return "Reading";
  }
  if (operation === "answer") {
    return "Answer";
  }
  return "Overview";
}

export function PageDescription() {
  const perception = useTaskStore((state) => state.perception);
  if (!perception) {
    return null;
  }

  return (
    <section className={styles.card} aria-labelledby="page-description-heading">
      <h2 id="page-description-heading">Page description</h2>
      <p className={styles.perceptionMeta}>
        {operationLabel(perception.operation)}
        {perception.uncertain ? " · Not sure" : ""}
      </p>
      {perception.uncertain ? (
        <p className={styles.uncertainLabel}>Not sure</p>
      ) : null}
      <p className={styles.perceptionText}>{perception.text}</p>
    </section>
  );
}
