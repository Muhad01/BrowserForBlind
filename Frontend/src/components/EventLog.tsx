"use client";

import styles from "@/components/console.module.css";
import { useTaskStore } from "@/stores/taskStore";

export function EventLog() {
  const events = useTaskStore((state) => state.events);

  return (
    <section className={styles.card} aria-labelledby="event-log-heading">
      <h2 id="event-log-heading">Event log</h2>
      {events.length === 0 ? (
        <p>No events yet.</p>
      ) : (
        <ol className={styles.log}>
          {events.map((entry, index) => (
            <li className={styles.logItem} key={`${entry.receivedAt}-${entry.event}-${index}`}>
              {entry.event}: {entry.speak || "(no speech)"}
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
