"use client";

import { useCallback, useEffect, useRef } from "react";

import { SpeechQueue, type SpeechItem, type SpeechPriority } from "@/lib/speechQueue";
import { loadSpeechSettings, useSpeechStore } from "@/stores/speechStore";

function canUseSynthesis(): boolean {
  return typeof window !== "undefined" && "speechSynthesis" in window && "SpeechSynthesisUtterance" in window;
}

export function useSpeechSynthesis() {
  const queueRef = useRef(new SpeechQueue());
  const playRef = useRef<(item: SpeechItem | null) => void>(() => undefined);

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

  useEffect(() => {
    playRef.current = (item) => {
      if (!item) {
        useSpeechStore.getState().setSpeaking(false);
        return;
      }
      useSpeechStore.getState().setLastSpoken(item.text);
      useSpeechStore.getState().setLive(item.text, item.priority);
      useSpeechStore.getState().setSpeaking(true);

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

      window.speechSynthesis.cancel();
      const utterance = new SpeechSynthesisUtterance(item.text);
      utterance.rate = settings.rate;
      const voices = window.speechSynthesis.getVoices();
      const selected = voices.find((voice) => voice.voiceURI === settings.voiceURI);
      if (selected) {
        utterance.voice = selected;
      }
      utterance.onend = () => {
        const next = queueRef.current.shiftNext();
        playRef.current(next);
      };
      utterance.onerror = () => {
        useSpeechStore.getState().setSpeaking(false);
      };
      window.speechSynthesis.speak(utterance);
    };
  }, []);

  const speak = useCallback((text: string, options: { priority?: SpeechPriority; event?: string } = {}) => {
    const trimmed = text.trim();
    if (!trimmed) {
      return;
    }
    const priority = options.priority ?? "polite";
    const result = queueRef.current.enqueue({
      text: trimmed,
      event: options.event,
      priority,
    });
    if (result.cancelCurrent && canUseSynthesis()) {
      window.speechSynthesis.cancel();
    }
    if (result.next) {
      playRef.current(result.next);
    }
  }, []);

  const cancel = useCallback(() => {
    queueRef.current.clear();
    if (canUseSynthesis()) {
      window.speechSynthesis.cancel();
    }
    useSpeechStore.getState().setSpeaking(false);
  }, []);

  const repeatLast = useCallback(() => {
    const last = useSpeechStore.getState().lastSpoken;
    if (last) {
      speak(last, { priority: "assertive" });
    }
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

  return { speak, cancel, repeatLast, unlock };
}
