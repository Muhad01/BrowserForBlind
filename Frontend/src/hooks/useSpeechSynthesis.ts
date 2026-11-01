"use client";

import { useCallback, useEffect, useRef } from "react";

import {
  compactHeld,
  dueForHeartbeat,
  GATE_RELEASE_MS,
  isSpeechGated,
  markHeartbeatSpoken,
  noteNonHeartbeatSpeech,
} from "@/lib/speechGate";
import { STILL_WORKING } from "@/lib/phrases";
import { SpeechQueue, type SpeechItem, type SpeechPriority } from "@/lib/speechQueue";
import { loadSpeechSettings, useSpeechStore } from "@/stores/speechStore";
import { useTaskStore } from "@/stores/taskStore";
import { useVoiceStore } from "@/stores/voiceStore";

function canUseSynthesis(): boolean {
  return typeof window !== "undefined" && "speechSynthesis" in window && "SpeechSynthesisUtterance" in window;
}

function logSpoken(text: string): void {
  if (process.env.NODE_ENV === "development") {
    console.log("[SPOKEN]", text);
  }
}

export function useSpeechSynthesis() {
  const queueRef = useRef(new SpeechQueue());
  const playRef = useRef<(item: SpeechItem | null) => void>(() => undefined);
  const flushTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    useSpeechStore.getState().setSettings(loadSpeechSettings());
  }, []);

  useEffect(() => {
    if (!canUseSynthesis()) {
      return;
    }
    const loadVoices = () => {
      useSpeechStore.getState().setVoices(window.speechSynthesis.getVoices());
    };
    loadVoices();
    window.speechSynthesis.addEventListener("voiceschanged", loadVoices);
    return () => {
      window.speechSynthesis.removeEventListener("voiceschanged", loadVoices);
    };
  }, []);

  const announce = useCallback((item: SpeechItem, liveText?: string) => {
    useSpeechStore.getState().setLastSpoken(item.text);
    if (item.priority === "assertive") {
      useSpeechStore.getState().setLastAssertive(item.text);
    }
    useSpeechStore.getState().setLive(liveText ?? item.text, item.priority);
  }, []);

  useEffect(() => {
    playRef.current = (item) => {
      if (!item) {
        useSpeechStore.getState().setSpeaking(false);
        return;
      }
      announce(item);
      if (isSpeechGated()) {
        queueRef.current.hold(item);
        queueRef.current.current = null;
        useSpeechStore.getState().setSpeaking(false);
        return;
      }

      const settings = useSpeechStore.getState().settings;
      if (settings.outputMode === "screenreader" || !canUseSynthesis()) {
        useSpeechStore.getState().setSpeaking(false);
        queueRef.current.current = null;
        const next = queueRef.current.shiftNext();
        if (next) {
          playRef.current(next);
        }
        return;
      }

      if (isSpeechGated()) {
        queueRef.current.hold(item);
        queueRef.current.current = null;
        useSpeechStore.getState().setSpeaking(false);
        return;
      }

      window.speechSynthesis.cancel();
      const utterance = new SpeechSynthesisUtterance(item.text);
      utterance.rate = settings.rate;
      const voices = window.speechSynthesis.getVoices();
      const selected = voices.find((voice) => voice.voiceURI === settings.voiceURI);
      if (selected) {
        utterance.voice = selected;
      }
      utterance.onend = () => {
        if (isSpeechGated()) {
          useSpeechStore.getState().setSpeaking(false);
          return;
        }
        const next = queueRef.current.shiftNext();
        playRef.current(next);
      };
      utterance.onerror = () => {
        useSpeechStore.getState().setSpeaking(false);
      };
      if (isSpeechGated()) {
        queueRef.current.hold(item);
        queueRef.current.current = null;
        useSpeechStore.getState().setSpeaking(false);
        return;
      }
      useSpeechStore.getState().setSpeaking(true);
      useSpeechStore.getState().markSpokenAt();
      logSpoken(item.text);
      window.speechSynthesis.speak(utterance);
    };
  }, [announce]);

  const flushHeld = useCallback(() => {
    if (isSpeechGated()) {
      return;
    }
    const verbosity = useSpeechStore.getState().settings.verbosity;
    const items = compactHeld(queueRef.current.takeHeld(), verbosity);
    for (const item of items) {
      const result = queueRef.current.enqueue(item);
      if (result.next) {
        playRef.current(result.next);
      }
    }
  }, []);

  useEffect(() => {
    const unsub = useVoiceStore.subscribe((state, previous) => {
      const gated = state.listening || state.processing;
      const wasGated = previous.listening || previous.processing;
      if (gated) {
        if (flushTimerRef.current) {
          clearTimeout(flushTimerRef.current);
          flushTimerRef.current = null;
        }
        return;
      }
      if (wasGated && !gated) {
        if (flushTimerRef.current) {
          clearTimeout(flushTimerRef.current);
        }
        flushTimerRef.current = setTimeout(() => {
          flushTimerRef.current = null;
          flushHeld();
        }, GATE_RELEASE_MS);
      }
    });
    return () => {
      unsub();
      if (flushTimerRef.current) {
        clearTimeout(flushTimerRef.current);
      }
    };
  }, [flushHeld]);

  const speak = useCallback((text: string, options: { priority?: SpeechPriority; event?: string; liveText?: string } = {}) => {
    const trimmed = text.trim();
    if (!trimmed) {
      return;
    }
    if (trimmed !== STILL_WORKING) {
      noteNonHeartbeatSpeech();
    }
    const item: SpeechItem = {
      text: trimmed,
      event: options.event ?? "local",
      priority: options.priority ?? "polite",
    };
    announce(item, options.liveText);
    if (useSpeechStore.getState().settings.verbosity === "brief" && item.event === "browser_action") {
      return;
    }
    if (isSpeechGated()) {
      queueRef.current.hold(item);
      return;
    }
    const result = queueRef.current.enqueue(item);
    if (result.cancelCurrent && canUseSynthesis()) {
      window.speechSynthesis.cancel();
    }
    if (result.next) {
      playRef.current(result.next);
    }
  }, [announce]);

  const bargeIn = useCallback(() => {
    queueRef.current.parkUnplayed();
    if (canUseSynthesis()) {
      window.speechSynthesis.cancel();
    }
    useSpeechStore.getState().setSpeaking(false);
  }, []);

  const cancel = useCallback((options: { held?: boolean } = { held: true }) => {
    queueRef.current.clear(options);
    if (canUseSynthesis()) {
      window.speechSynthesis.cancel();
    }
    useSpeechStore.getState().setSpeaking(false);
  }, []);

  const repeatLast = useCallback(() => {
    const lastAssertive = useSpeechStore.getState().lastAssertive;
    const last = lastAssertive || useSpeechStore.getState().lastSpoken;
    if (last) {
      speak(last, { priority: "assertive", event: "local" });
    }
  }, [speak]);

  useEffect(() => {
    const timer = setInterval(() => {
      if (useSpeechStore.getState().settings.verbosity !== "brief") {
        return;
      }
      if (isSpeechGated()) {
        return;
      }
      const status = useTaskStore.getState().task?.status;
      if (status !== "running" && status !== "pending") {
        return;
      }
      const speech = useSpeechStore.getState();
      const now = Date.now();
      if (!dueForHeartbeat(now, speech.lastSpokenAt)) {
        return;
      }
      markHeartbeatSpoken(now);
      speak(STILL_WORKING, { priority: "polite", event: "local" });
    }, 1000);
    return () => clearInterval(timer);
  }, [speak]);

  const unlock = useCallback(() => {
    if (!canUseSynthesis()) {
      return;
    }
    window.speechSynthesis.cancel();
    const priming = new SpeechSynthesisUtterance(" ");
    priming.volume = 0;
    window.speechSynthesis.speak(priming);
    window.speechSynthesis.cancel();
  }, []);

  return { speak, cancel, bargeIn, repeatLast, unlock };
}
