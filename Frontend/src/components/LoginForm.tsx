"use client";

import { FormEvent, useId, useState } from "react";

import styles from "@/components/console.module.css";
import { ApiError, login } from "@/lib/api";
import { useAuthStore } from "@/stores/authStore";
import { useSpeechStore } from "@/stores/speechStore";

interface LoginFormProps {
  onError: (message: string) => void;
}

export function LoginForm({ onError }: LoginFormProps) {
  const usernameId = useId();
  const passwordId = useId();
  const errorId = useId();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setError("");
    try {
      const user = await login(username, password);
      useAuthStore.getState().setUser(user);
    } catch (err) {
      const message =
        err instanceof ApiError ? err.message : "Could not sign in. Check your username and password.";
      setError(message);
      useSpeechStore.getState().setLive(message, "assertive");
      onError(message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <section className={styles.card} aria-labelledby="login-heading">
      <h1 id="login-heading">Sign in to CIGHT Browser</h1>
      <form onSubmit={onSubmit}>
        <div className={styles.field}>
          <label htmlFor={usernameId}>Username</label>
          <input
            id={usernameId}
            className={styles.input}
            name="username"
            autoComplete="username"
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            required
          />
        </div>
        <div className={styles.field}>
          <label htmlFor={passwordId}>Password</label>
          <input
            id={passwordId}
            className={styles.input}
            name="password"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            required
          />
        </div>
        {error ? (
          <p className={styles.formError} id={errorId} role="alert">
            {error}
          </p>
        ) : null}
        <button className={styles.primary} type="submit" disabled={submitting}>
          {submitting ? "Signing in" : "Sign in"}
        </button>
      </form>
    </section>
  );
}
